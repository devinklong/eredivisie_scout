-- check_team_name_mismatches.sql
--
-- Audits team-name mismatches ACROSS ALL THREE data sources this project
-- joins on team identity: eredivisie_soccerdata_player_season_stats
-- (FBref), eredivisie_whoscored_player_season_stats (WhoScored), and
-- eredivisie_club_status / eredivisie_transfers (Transfermarkt).
--
-- Originally built (2026-09-15/16) scoped to just 2016/2017, after
-- fix_shots_with_whoscored_derivation.sql's sanity check 3 turned up 129
-- rows with a confirmed player match but no team match -- e.g.
-- "Groningen" (FBref) vs "FC Groningen" (WhoScored). That mismatch also
-- turned out to be silently blocking entity-resolution candidate
-- generation itself (fbref_whoscored_candidate_pairs.sql blocks on
-- team + season_id), not just this one fix's join -- so a hidden
-- mismatch anywhere in this pipeline has real, compounding downstream
-- cost. Extended (2026-09-16) to cover all 13 seasons for FBref/WhoScored,
-- plus a first check against Transfermarkt's club_name, which uses yet a
-- THIRD naming convention (e.g. "Sparta", vs FBref's "Sparta R." and
-- WhoScored's pre-fix "Sparta Rotterdam").
--
-- NOTE: Transfermarkt's PLAYER-level crosswalk (build_players_
-- transfermarkt_crosswalk.py) does NOT depend on team-name matching --
-- it joins on canonical_player_id, so entity resolution itself is not
-- at risk from anything found here. The queries below matter only if/
-- when something joins eredivisie_club_status or eredivisie_transfers
-- to FBref/WhoScored by matching team-name text directly.
--
-- Run order: query 5 (season-by-season summary counts) first for a
-- quick overview of where problems exist, THEN drill into 1-4/6 for
-- the specific seasons/pairs it flags. Queries 1-4 are the original
-- 2016/2017-scoped checks, kept for reference/reproducibility.

-- 1. Full pairwise audit -- catches near-matches (substring pairs) like the
-- confirmed Groningen/FC Groningen case. May include some false-positive
-- substring matches between unrelated clubs -- eyeball the results.
SELECT DISTINCT ws.team AS whoscored_team, fbref.team AS fbref_team
FROM eredivisie_whoscored_player_season_stats ws
JOIN eredivisie_soccerdata_player_season_stats fbref
  ON fbref.season_id = ws.season_id
WHERE ws.season_id IN (2016, 2017)
  AND ws.team <> fbref.team
  AND (LOWER(ws.team) LIKE '%' || LOWER(fbref.team) || '%' OR LOWER(fbref.team) LIKE '%' || LOWER(ws.team) || '%');

-- 2. Side-by-side: every distinct team name in each table for those seasons.
-- Useful if a mismatch isn't a simple substring/prefix variant (e.g. an
-- abbreviation vs. a full name) and query 1 misses it.
SELECT DISTINCT team, 'fbref' AS source, season_id
FROM eredivisie_soccerdata_player_season_stats
WHERE season_id IN (2016, 2017)
UNION ALL
SELECT DISTINCT team, 'whoscored' AS source, season_id
FROM eredivisie_whoscored_player_season_stats
WHERE season_id IN (2016, 2017)
ORDER BY season_id, team;

-- 3. Targeted: team names present in one table but not the other for the
-- same season, SCOPED TO 2016/2017 ONLY (kept for reference -- see query 6
-- for the all-season version). Cleanest signal -- a genuinely matching
-- name is excluded entirely, leaving only the mismatched pairs to sort
-- out manually.
SELECT team, season_id, 'whoscored only' AS note
FROM eredivisie_whoscored_player_season_stats
WHERE season_id IN (2016, 2017)
  AND team NOT IN (SELECT team FROM eredivisie_soccerdata_player_season_stats WHERE season_id IN (2016, 2017))

UNION ALL

SELECT team, season_id, 'fbref only' AS note
FROM eredivisie_soccerdata_player_season_stats
WHERE season_id IN (2016, 2017)
  AND team NOT IN (SELECT team FROM eredivisie_whoscored_player_season_stats WHERE season_id IN (2016, 2017))

ORDER BY season_id, team;

-- 4. VERIFICATION: applies the confirmed team-name mapping (7 pairs, found
-- via queries 1 and 3 across both 2016 and 2017) and re-checks for any
-- team names still unmatched between the two tables. Should return ZERO
-- rows if the mapping is complete -- this is the sweep that was
-- screenshotted to confirm the fix, kept here for reference.
SELECT team, season_id, 'whoscored only' AS note
FROM (
    SELECT
        CASE team
            WHEN 'FC Groningen' THEN 'Groningen'
            WHEN 'FC Utrecht' THEN 'Utrecht'
            WHEN 'PEC Zwolle' THEN 'Zwolle'
            WHEN 'SC Heerenveen' THEN 'Heerenveen'
            WHEN 'Heracles' THEN 'Heracles Almelo'
            WHEN 'Roda' THEN 'Roda JC'
            WHEN 'Sparta Rotterdam' THEN 'Sparta R.'
            ELSE team
        END AS team,
        season_id
    FROM eredivisie_whoscored_player_season_stats
    WHERE season_id IN (2016, 2017)
) ws
WHERE ws.team NOT IN (SELECT team FROM eredivisie_soccerdata_player_season_stats WHERE season_id IN (2016, 2017))

UNION ALL

SELECT team, season_id, 'fbref only' AS note
FROM eredivisie_soccerdata_player_season_stats
WHERE season_id IN (2016, 2017)
  AND team NOT IN (
    SELECT
        CASE team
            WHEN 'FC Groningen' THEN 'Groningen'
            WHEN 'FC Utrecht' THEN 'Utrecht'
            WHEN 'PEC Zwolle' THEN 'Zwolle'
            WHEN 'SC Heerenveen' THEN 'Heerenveen'
            WHEN 'Heracles' THEN 'Heracles Almelo'
            WHEN 'Roda' THEN 'Roda JC'
            WHEN 'Sparta Rotterdam' THEN 'Sparta R.'
            ELSE team
        END
    FROM eredivisie_whoscored_player_season_stats
    WHERE season_id IN (2016, 2017)
  )

ORDER BY season_id, team;

-- 5. ALL-SEASON SUMMARY: DISTINCT mismatched team-name count per season,
-- both FBref/WhoScored AND FBref/Transfermarkt. Run this FIRST.
-- IMPORTANT: counts DISTINCT team names, not rows -- an earlier version
-- of this query counted rows (one per player), which badly inflated the
-- apparent scope: a single mismatched club name with 25-30 players on
-- its roster showed up as 25-30 "violations" instead of the 1 real
-- naming problem it actually is. This version reports the true number
-- of distinct club-name strings that don't reconcile.
SELECT season_id, 'fbref_vs_whoscored' AS pair, COUNT(DISTINCT team) AS mismatched_team_names
FROM (
    SELECT DISTINCT team, season_id
    FROM eredivisie_whoscored_player_season_stats
    WHERE team NOT IN (SELECT DISTINCT team FROM eredivisie_soccerdata_player_season_stats)
    UNION
    SELECT DISTINCT team, season_id
    FROM eredivisie_soccerdata_player_season_stats
    WHERE team NOT IN (SELECT DISTINCT team FROM eredivisie_whoscored_player_season_stats)
) ws_mismatches
GROUP BY season_id

UNION ALL

SELECT season_id, 'fbref_vs_transfermarkt' AS pair, COUNT(DISTINCT team) AS mismatched_team_names
FROM (
    SELECT DISTINCT club_name AS team, season_id
    FROM eredivisie_club_status
    WHERE was_eredivisie = TRUE
      AND club_name NOT IN (SELECT DISTINCT team FROM eredivisie_soccerdata_player_season_stats)
    UNION
    SELECT DISTINCT team, season_id
    FROM eredivisie_soccerdata_player_season_stats
    WHERE season_id IN (SELECT DISTINCT season_id FROM eredivisie_club_status)
      AND team NOT IN (SELECT DISTINCT club_name FROM eredivisie_club_status WHERE was_eredivisie = TRUE)
) tm_mismatches
GROUP BY season_id

ORDER BY season_id, pair;

-- 6. ALL-SEASON DETAIL: DISTINCT team names present in one table but not
-- the other, per season, across every season both tables have data for.
-- A completely clean pipeline returns ZERO rows. (Fixed to use DISTINCT --
-- see query 5's note on why the earlier row-count version overstated
-- the real scope.)
SELECT DISTINCT team, season_id, 'whoscored only' AS note
FROM eredivisie_whoscored_player_season_stats
WHERE team NOT IN (SELECT DISTINCT team FROM eredivisie_soccerdata_player_season_stats)

UNION

SELECT DISTINCT team, season_id, 'fbref only (vs whoscored)' AS note
FROM eredivisie_soccerdata_player_season_stats
WHERE team NOT IN (SELECT DISTINCT team FROM eredivisie_whoscored_player_season_stats)

ORDER BY season_id, team;

-- 7. ALL-SEASON DETAIL, TRANSFERMARKT: same idea as query 6, but against
-- eredivisie_club_status.club_name instead of WhoScored. Only checks
-- was_eredivisie = TRUE rows (a club's off-flight seasons aren't
-- expected to appear in FBref/WhoScored's Eredivisie-only data anyway,
-- so including them would produce noise, not signal).
SELECT DISTINCT club_name AS team, season_id, 'transfermarkt only' AS note
FROM eredivisie_club_status
WHERE was_eredivisie = TRUE
  AND club_name NOT IN (SELECT DISTINCT team FROM eredivisie_soccerdata_player_season_stats)

UNION

SELECT DISTINCT team, season_id, 'fbref only (vs transfermarkt)' AS note
FROM eredivisie_soccerdata_player_season_stats
WHERE season_id IN (SELECT DISTINCT season_id FROM eredivisie_club_status)
  AND team NOT IN (SELECT DISTINCT club_name FROM eredivisie_club_status WHERE was_eredivisie = TRUE)

ORDER BY season_id, team;
