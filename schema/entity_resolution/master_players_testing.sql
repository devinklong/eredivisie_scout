-- master_players_testing.sql
--
-- Validation suite for master_player_season_stats, run before trusting
-- this table for any modeling work. Every section below states what a
-- HEALTHY result looks like -- read the comment before the query, not
-- just the output. Given how much real data-quality churn this table
-- has already had (the anchor-undercounting bug, the Marcus Pedersen
-- and Eric Botteghin fan-out bugs, the orphaned-row and numeric-name
-- issues in the underlying WhoScored aggregation), this is not a
-- formality -- run the whole thing, not just a couple of sections.

-- SECTION 1: Row count and season coverage.
-- Healthy: every season from the earliest FBref season through the
-- most recent should appear, with no gaps.
SELECT season_id, COUNT(*) AS num_rows, COUNT(DISTINCT team) AS num_teams
FROM master_player_season_stats
GROUP BY season_id
ORDER BY season_id;

-- SECTION 1b: total row count, cross-checked LIVE against the real
-- source table -- NOT a hardcoded number. An earlier version of this
-- file compared against a fixed "~9,229" figure copied from the
-- README, which goes stale every time the underlying tables change
-- (a fix, a rerun, a backfill). Since master_player_season_stats
-- anchors on eredivisie_soccerdata_player_season_stats via LEFT
-- JOINs (never INNER, confirmed fixed 2026-09-12), row count should
-- match that source table EXACTLY, every time this is run, regardless
-- of what the source table's total happens to be on any given day.
-- Healthy: difference = 0. Any non-zero difference means a join
-- somewhere in the view is fanning out or dropping rows again --
-- treat this as seriously as the duplicate check in Section 2.
SELECT (SELECT COUNT(*) FROM eredivisie_soccerdata_player_season_stats) AS fbref_source_rows, (SELECT COUNT(*) FROM master_player_season_stats) AS master_table_rows, (SELECT COUNT(*) FROM eredivisie_soccerdata_player_season_stats) - (SELECT COUNT(*) FROM master_player_season_stats) AS difference;

-- SECTION 2: Duplicate check -- the final confirmation.
-- Healthy: ZERO rows returned. If this returns anything, stop here --
-- nothing else in this file is trustworthy until this is empty.
SELECT player_id, team, season_id, COUNT(*) AS num_rows
FROM master_player_season_stats
WHERE player_id IS NOT NULL
GROUP BY player_id, team, season_id
HAVING COUNT(*) > 1;

-- SECTION 3: Coverage rates by source, overall and by season.
-- Healthy: ws_whoscored_player_id populated only from season_id 2013
-- onward (WhoScored's real coverage start) -- should be exactly zero
-- before that.
--
-- tm_height_cm coverage: DO NOT compare this against the ~76.7%
-- figure from the original bio-scraper run, or assume it should rise
-- steadily by season. Both were real, correctly-verified findings --
-- but for a DIFFERENT population (every distinct player who ever had
-- a scraped TRANSFER EVENT in eredivisie_transfers, checked BEFORE
-- master_player_season_stats existed), not this table's population
-- (every FBref season-row, including players never matched into
-- entity resolution at all). Treating that earlier finding as still
-- applicable here without re-checking it was a real mistake, caught
-- and corrected 2026-09-14 -- see Section 3c below for what actually
-- explains this table's coverage pattern.
SELECT season_id, COUNT(*) AS total_rows, COUNT(ws_whoscored_player_id) AS has_whoscored, COUNT(tm_height_cm) AS has_height, ROUND(COUNT(ws_whoscored_player_id)::numeric / COUNT(*) * 100, 1) AS pct_whoscored, ROUND(COUNT(tm_height_cm)::numeric / COUNT(*) * 100, 1) AS pct_height
FROM master_player_season_stats
GROUP BY season_id
ORDER BY season_id;

-- SECTION 3b: WHY is tm_height_cm missing, broken down by actual cause
-- -- confirmed (2026-09-14) this is the real diagnostic that matters,
-- not just the raw percentage above. Splits missing-height rows into
-- three distinguishable causes per season: never got a canonical
-- player_id at all, has a player_id but no confirmed Transfermarkt
-- link, or is linked but Transfermarkt's own data just doesn't have
-- his height. A large no_canonical_identity count is NOT simply
-- fixed by re-running entity resolution -- see Section 3c, which
-- splits that population further and found only ~19% of it is
-- actually fixable that way.
SELECT season_id, COUNT(*) AS total_rows, COUNT(*) FILTER (WHERE player_id IS NULL) AS no_canonical_identity, COUNT(*) FILTER (WHERE player_id IS NOT NULL AND canonical_name NOT IN (SELECT source_name FROM player_source_crosswalk WHERE source = 'transfermarkt')) AS no_transfermarkt_link, COUNT(*) FILTER (WHERE player_id IS NOT NULL AND tm_height_cm IS NULL AND canonical_name IN (SELECT source_name FROM player_source_crosswalk WHERE source = 'transfermarkt')) AS linked_but_no_bio_data
FROM master_player_season_stats
GROUP BY season_id
ORDER BY season_id;

-- SECTION 3c: for rows with NO canonical identity at all, splits by
-- whether WhoScored even HAS data for that player's team/season --
-- the real distinction between "a genuine WhoScored coverage gap,
-- nothing to match against" and "a real candidate likely exists but
-- didn't get matched." Built 2026-09-14 after re-running
-- match_fbref_whoscored.py found almost no new candidates despite a
-- large no_canonical_identity population, disproving the simpler
-- "just re-run entity resolution" theory. Confirmed via a full count
-- (not a sample) for 2023-2025: 558 of 688 (81.1%) have no WhoScored
-- data at all for their team/season -- a real, likely permanent
-- coverage gap. Only 130 (18.9%) have real WhoScored data and are
-- worth investigating further (individual-level WhoScored gaps, the
-- pg_trgm blocking threshold, or an unfixed team-name mismatch).
-- This section runs the same check across ALL seasons, not just
-- 2023-2025, so any future season showing a similarly lopsided split
-- is caught the same way.
SELECT m.season_id, COUNT(*) AS no_canonical_identity_total, COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM eredivisie_whoscored_player_season_stats w WHERE w.team = m.team AND w.season_id = m.season_id)) AS has_whoscored_data_but_unmatched, COUNT(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM eredivisie_whoscored_player_season_stats w WHERE w.team = m.team AND w.season_id = m.season_id)) AS no_whoscored_data_at_all
FROM master_player_season_stats m
WHERE m.player_id IS NULL
GROUP BY m.season_id
ORDER BY m.season_id;

-- SECTION 4: Percentage-field range sanity.
-- Healthy: ZERO rows returned. Every stored percentage must be between
-- 0 and 100 -- anything outside that range means a computation bug
-- somewhere upstream (a percentage computed on the wrong denominator,
-- a units error, etc.).
SELECT canonical_name, team, season_id, 'fbref_shots_on_target_pct' AS field, fbref_shots_on_target_pct AS value FROM master_player_season_stats WHERE fbref_shots_on_target_pct NOT BETWEEN 0 AND 100
UNION ALL
SELECT canonical_name, team, season_id, 'gk_save_pct', gk_save_pct FROM master_player_season_stats WHERE gk_save_pct NOT BETWEEN 0 AND 100
UNION ALL
SELECT canonical_name, team, season_id, 'gk_clean_sheet_pct', gk_clean_sheet_pct FROM master_player_season_stats WHERE gk_clean_sheet_pct NOT BETWEEN 0 AND 100
UNION ALL
SELECT canonical_name, team, season_id, 'ws_passes_pct', ws_passes_pct FROM master_player_season_stats WHERE ws_passes_pct NOT BETWEEN 0 AND 100
UNION ALL
SELECT canonical_name, team, season_id, 'ws_take_ons_won_pct', ws_take_ons_won_pct FROM master_player_season_stats WHERE ws_take_ons_won_pct NOT BETWEEN 0 AND 100
UNION ALL
SELECT canonical_name, team, season_id, 'ws_aerial_duel_win_pct', ws_aerial_duel_win_pct FROM master_player_season_stats WHERE ws_aerial_duel_win_pct NOT BETWEEN 0 AND 100
UNION ALL
SELECT canonical_name, team, season_id, 'ws_ground_duel_win_pct', ws_ground_duel_win_pct FROM master_player_season_stats WHERE ws_ground_duel_win_pct NOT BETWEEN 0 AND 100;

-- SECTION 5: Cross-column consistency -- a "won"/"completed" count can
-- never exceed its own attempt count.
-- Healthy: ZERO rows returned.
SELECT canonical_name, team, season_id, 'fbref_shots_on_target > fbref_shots' AS problem FROM master_player_season_stats WHERE fbref_shots_on_target > fbref_shots
UNION ALL
SELECT canonical_name, team, season_id, 'ws_passes_completed > ws_passes' FROM master_player_season_stats WHERE ws_passes_completed > ws_passes
UNION ALL
SELECT canonical_name, team, season_id, 'ws_take_ons_won > ws_take_ons' FROM master_player_season_stats WHERE ws_take_ons_won > ws_take_ons
UNION ALL
SELECT canonical_name, team, season_id, 'ws_tackles_won > ws_tackles' FROM master_player_season_stats WHERE ws_tackles_won > ws_tackles
UNION ALL
SELECT canonical_name, team, season_id, 'ws_aerials_won > ws_aerials' FROM master_player_season_stats WHERE ws_aerials_won > ws_aerials
UNION ALL
SELECT canonical_name, team, season_id, 'gk_saves > gk_shots_on_target_against' FROM master_player_season_stats WHERE gk_saves > gk_shots_on_target_against;

-- SECTION 6: Per-90 sanity bounds -- catches a bad denominator or a
-- units error (e.g. a stat accidentally left un-divided).
-- Healthy: ZERO rows returned. Thresholds here are deliberately loose
-- (well above any plausible real single-player rate) -- the point is
-- catching genuine computation errors, not flagging legitimately busy
-- players.
SELECT canonical_name, team, season_id, ws_passes_per90 FROM master_player_season_stats WHERE ws_passes_per90 > 150
UNION ALL
SELECT canonical_name, team, season_id, ws_touches_per90 FROM master_player_season_stats WHERE ws_touches_per90 > 200
UNION ALL
SELECT canonical_name, team, season_id, fbref_yellow_cards_per90 FROM master_player_season_stats WHERE fbref_yellow_cards_per90 > 2;

-- SECTION 7: Known problem-player spot checks -- confirms the specific
-- fixes made tonight actually hold, not just "no duplicates in general."
-- Healthy: Marcus Pedersen (271) shows ONLY Vitesse rows (2010, 2011,
-- 2013); the split identity (999, Marcus Holmgren Pedersen) shows ONLY
-- Feyenoord rows (2021-2024); Eric Botteghin (1710) shows exactly ONE
-- row for Feyenoord 2019, not two; Ricardo Ippel shows born=1990 on
-- every row, not a mix of 1990/1991.
SELECT canonical_name, player_id, team, season_id FROM master_player_season_stats WHERE player_id IN (271, 999, 1710) ORDER BY player_id, season_id;

SELECT canonical_name, team, season_id, fbref_born FROM master_player_season_stats WHERE canonical_name = 'Ricardo Ippel' ORDER BY season_id;

-- SECTION 8: Team name consistency -- confirms no other PSV-Eindhoven-
-- style mismatch slipped through. Replaced an earlier version of this
-- check (2026-09-14) that asked you to eyeball a list against a
-- GUESSED club count ("~34-36") that was never actually verified.
--
-- UPDATED (2026-09-16): now checks against team_name_alias instead of
-- eredivisie_club_status.club_name directly. eredivisie_club_status
-- only has Transfermarkt's OWN canonical spelling (29 rows) -- but
-- FBref legitimately uses 6 different spellings for real clubs
-- (Sparta R., Heracles Almelo, Roda JC, AZ Alkmaar, VVV-Venlo,
-- Zwolle -- all confirmed real, all cataloged in team_name_alias
-- during tonight's team_id refactor). Checking against
-- eredivisie_club_status alone would false-flag every one of those
-- as if it were a new PSV/PSV-Eindhoven-style bug. team_name_alias is
-- the definitive, up-to-date source now -- every real FBref spelling
-- should have a row there.
-- Healthy: ZERO rows returned. Any team name here exists in
-- master_player_season_stats but has no registered alias for FBref at
-- all -- a genuinely new, unresolved mismatch.
SELECT DISTINCT team FROM master_player_season_stats WHERE team NOT IN (SELECT source_name FROM team_name_alias WHERE source = 'fbref');

-- SECTION 9a: verify the position label real goalkeepers actually
-- carry, BEFORE trusting Section 9's filter below. The '%GK%' pattern
-- in Section 9 was an assumption based on the general shape of
-- fbref_position values seen elsewhere in this project ("DF", "FW",
-- "DF,MF") -- never independently confirmed against real keepers.
-- Uses gk_saves being populated as the real signal for "is a
-- keeper" (a fact, not an assumption), then shows what
-- fbref_position value(s) those real keepers actually carry.
SELECT DISTINCT fbref_position FROM master_player_season_stats WHERE gk_saves IS NOT NULL ORDER BY fbref_position;

-- SECTION 9: Goalkeeper stats should only be populated for goalkeepers.
-- Healthy: ZERO rows returned. DEPENDS ON SECTION 9a ABOVE -- if that
-- query shows a position value NOT containing "GK", update this
-- filter to match the real value before trusting this section's
-- result.
SELECT canonical_name, team, season_id, fbref_position, gk_saves
FROM master_player_season_stats
WHERE gk_saves IS NOT NULL AND fbref_position NOT LIKE '%GK%';

-- SECTION 10: Referential integrity -- every non-null player_id should
-- actually exist in the players table (no FK constraint is enforced,
-- per this project's convention of joining at query time -- this
-- confirms that convention hasn't silently broken).
-- Healthy: ZERO rows returned.
SELECT DISTINCT m.player_id
FROM master_player_season_stats m
LEFT JOIN players p ON p.player_id = m.player_id
WHERE m.player_id IS NOT NULL AND p.player_id IS NULL;

SELECT p.player_id, p.canonical_name, p.created_at
FROM players p
LEFT JOIN player_source_crosswalk psc ON psc.player_id = p.player_id
WHERE psc.player_id IS NULL;