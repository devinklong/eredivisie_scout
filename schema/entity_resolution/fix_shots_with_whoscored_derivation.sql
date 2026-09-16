-- fix_shots_with_whoscored_derivation.sql
--
-- Replaces eredivisie_soccerdata_player_season_stats' own shots/
-- shots_on_target/shots_on_target_pct with the WhoScored-derived,
-- validated definition, for every season WhoScored can cover
-- (2013-2025). This is a deliberate, full replacement -- not just a
-- patch for the confirmed 2016-17/2017-18 FBref gap -- decided
-- 2026-09-14: this project wants ONE consistent shots_on_target
-- definition across every year it can have one, using the narrower
-- "reached the keeper or scored" convention (see derive_shots_stats.py
-- for the full reasoning), rather than FBref's original numbers for
-- most years and a different source for two specific broken ones.
--
-- Run steps 1 and 2 below, IN ORDER, only after the 13-season
-- WhoScored re-run and aggregation load (with shots wired in) are
-- complete.

-- STEP 1: seasons 2013-2025 -- overwrite with the WhoScored-derived
-- values, joined through the entity-resolution crosswalk (same
-- disambiguation discipline as master_player_season_stats.sql: guards
-- on canonical_born/canonical_whoscored_player_id where a known
-- collision exists).

UPDATE eredivisie_soccerdata_player_season_stats fbref SET shots = ws.shots, shots_on_target = ws.shots_on_target, shots_on_target_pct = ws.shots_on_target_pct FROM player_source_crosswalk fbref_x JOIN players p ON p.player_id = fbref_x.player_id JOIN player_source_crosswalk ws_x ON ws_x.player_id = p.player_id AND ws_x.source = 'whoscored' JOIN eredivisie_whoscored_player_season_stats ws ON ws.player_name = ws_x.source_name AND (p.canonical_whoscored_player_id IS NULL OR p.canonical_whoscored_player_id = ws.whoscored_player_id) WHERE fbref_x.source = 'fbref' AND fbref_x.source_name = fbref.player_name AND (p.canonical_born IS NULL OR p.canonical_born = fbref.born) AND fbref.season_id >= 2013 AND ws.team = fbref.team AND ws.season_id = fbref.season_id;

-- STEP 2: seasons 2010-2012 -- WhoScored has zero coverage, no
-- alternative source exists. NULL rather than keep FBref's original
-- (mixed-definition) numbers, per project decision.
UPDATE eredivisie_soccerdata_player_season_stats SET shots = NULL, shots_on_target = NULL, shots_on_target_pct = NULL WHERE season_id < 2013;

-- SANITY CHECKS -- run after both steps above:
-- Should be a large, non-zero number (every 2013-2025 player who has
-- a confirmed WhoScored link):
SELECT COUNT(*) FROM eredivisie_soccerdata_player_season_stats WHERE season_id >= 2013 AND shots IS NOT NULL;
-- Should be ZERO (every pre-2013 row nulled out):
SELECT COUNT(*) FROM eredivisie_soccerdata_player_season_stats WHERE season_id < 2013 AND shots IS NOT NULL;
-- Should be ZERO -- the whole reason for this fix, re-confirmed at the source:
SELECT COUNT(*) FROM eredivisie_soccerdata_player_season_stats WHERE shots_on_target > shots;

