-- fix_player_team_season_history_disambiguation.sql
-- FIXES A SECOND INSTANCE of the same underlying bug that caused the
-- Marcus Pedersen merge (see fix_marcus_pedersen_split.sql): once the
-- split created a SECOND fbref crosswalk row also reading
-- 'Marcus Pedersen' (for the new player_id), player_team_season_history
-- -- which joins purely on NAME STRING, with no disambiguator -- had
-- BOTH player_ids independently matching ALL 7 rows in
-- eredivisie_soccerdata_player_season_stats named 'Marcus Pedersen'
-- (both eras, both real people), confirmed via a real query showing
-- both 271 and 999 with the full combined Vitesse+Feyenoord history.
--
-- FIX: add players.canonical_born (nullable -- only populated for
-- players where a real collision was found and resolved, NOT
-- backfilled for the other ~1700 players who don't have this problem)
-- and use it to filter the FBref-side join wherever it's set.
--
-- REAL LIMITATION, NOW FIXED: eredivisie_whoscored_player_season_stats
-- has no birth-year column, but it DOES have whoscored_player_id (the
-- native ID backfilled earlier specifically for this kind of
-- disambiguation). Confirmed (2026-09-10) via a real query that the
-- Vitesse/2013 row and the Feyenoord rows for "Marcus Pedersen" carry
-- DIFFERENT whoscored_player_id values -- WhoScored's own data already
-- distinguishes these two real people internally, this view just
-- wasn't using that signal yet. Fixed the same way as the FBref side:
-- a nullable canonical_whoscored_player_id column on players,
-- populated only for known collisions.

-- canonical_born already exists and is populated from the previous
-- run of this file (271=1990, 999=2000) -- not repeated here.

ALTER TABLE players ADD COLUMN canonical_whoscored_player_id INTEGER;

-- Replace these two placeholder values with the REAL whoscored_player_id
-- each era actually returned from the query above before running.
UPDATE players SET canonical_whoscored_player_id = 22291 WHERE player_id = 271;
UPDATE players SET canonical_whoscored_player_id = 357133 WHERE player_id = 999;

CREATE OR REPLACE VIEW player_team_season_history AS
SELECT psc.player_id, s.team, s.season_id
FROM player_source_crosswalk psc
JOIN players p ON p.player_id = psc.player_id
JOIN eredivisie_soccerdata_player_season_stats s
    ON psc.source = 'fbref' AND psc.source_name = s.player_name
WHERE p.canonical_born IS NULL OR p.canonical_born = s.born
UNION
SELECT psc.player_id, w.team, w.season_id
FROM player_source_crosswalk psc
JOIN players p ON p.player_id = psc.player_id
JOIN eredivisie_whoscored_player_season_stats w
    ON psc.source = 'whoscored' AND psc.source_name = w.player_name
WHERE p.canonical_whoscored_player_id IS NULL
   OR p.canonical_whoscored_player_id = w.whoscored_player_id;

-- Sanity check: 271 should show ONLY Vitesse 2010/2011/2013 now,
-- 999 should show ONLY Feyenoord 2021-2024 -- no cross-contamination
-- on either side this time.
SELECT * FROM player_team_season_history WHERE player_id IN (271, 999) ORDER BY player_id, season_id;
