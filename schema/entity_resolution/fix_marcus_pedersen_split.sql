-- fix_marcus_pedersen_split.sql
-- FBref/WhoScored's exact-name matching silently merged TWO different
-- real people named "Marcus Pedersen" under one canonical player_id
-- (271) -- confirmed via eredivisie_soccerdata_player_season_stats.born:
-- 1990 (Vitesse, 2010-2013) vs 2000 (Feyenoord, 2021-2024).
--
-- ROOT CAUSE, confirmed precisely (2026-09-10): player_id=271 has
-- exactly ONE fbref crosswalk row and ONE whoscored crosswalk row
-- (crosswalk_id 541/542) -- not a per-row lookup bug. The original
-- FBref<->WhoScored matching WAS correctly blocked by team+season, so
-- within the Vitesse/2010 block it correctly matched the real
-- 1990-born Marcus Pedersen to his real WhoScored entry, and
-- separately within the Feyenoord/2021 block it correctly matched the
-- real 2000-born Marcus Pedersen to HIS real WhoScored entry -- two
-- individually-correct matches. The bug is in
-- build_players_crosswalk.py's load_exact_matches(), which deduplicates
-- by (fbref_name, whoscored_name) ALONE -- exactly the logic that
-- correctly collapses one real person's genuine multi-season repeats
-- (e.g. Klaas-Jan Huntelaar appearing once per season). Since both
-- string pairs here were identically ("Marcus Pedersen", "Marcus
-- Pedersen"), the dedup collapsed two DIFFERENT real people's
-- correct-in-isolation matches into one row, with nothing checking
-- whether continuous team/season history across all the collapsed
-- rows actually makes sense as one real career. GENERALIZABLE RISK,
-- NOT YET AUDITED: any other name shared by two unrelated real players
-- across disconnected eras in this dataset could have the same
-- problem, silently.
--
-- Real people, confirmed via external search (2026-09-10):
--   - Marcus Pedersen, b. 8 June 1990, Hamar, Norway. Vitesse 2010-2014.
--     Transfermarkt player_id 41609.
--   - Marcus Holmgren Pedersen, b. 16 July 2000, Hammerfest, Norway.
--     Feyenoord (this era), later Sassuolo/Torino/Olympiacos.
--     Transfermarkt player_id 583404.
--
-- STEP 1: run this alone, note the new player_id it returns.
INSERT INTO players (canonical_name) VALUES ('Marcus Holmgren Pedersen')
RETURNING player_id;


-- STEP 2: replace 999 (all 3 places) with the player_id from STEP 1,
-- then run this alone. Moves the WHOSCORED crosswalk row for the
-- Feyenoord-era player to the new player_id. Confirmed safe as-is
-- (2026-09-10): player_id=271 has exactly ONE whoscored row
-- (crosswalk_id 542), so no source_name filtering is needed.
UPDATE player_source_crosswalk
SET player_id = 999
WHERE player_id = 271
  AND source = 'whoscored';


-- STEP 3: add a fresh fbref crosswalk row for the split-off player
-- (271's existing fbref row stays put, describing the 1990-born
-- Vitesse player -- it does NOT need to move).
INSERT INTO player_source_crosswalk
    (player_id, source, source_name, confidence, match_method, verified, notes)
VALUES
    (999, 'fbref', 'Marcus Pedersen', NULL, 'manual_review', TRUE,
     'Split from player_id=271 (2026-09-10): FBref''s own born column '
     'confirms two different real people share this exact name -- '
     '1990 (Vitesse) vs 2000 (Feyenoord). This row is the 2000-born '
     'Marcus Holmgren Pedersen.');


-- STEP 4: attach the correct Transfermarkt link to EACH real person
-- separately -- replace 999 with the split-off player_id.
INSERT INTO player_source_crosswalk
    (player_id, source, source_name, source_native_id, confidence, match_method, verified, notes)
VALUES
    (271, 'transfermarkt', 'Marcus Pedersen', 41609, NULL, 'manual_review', TRUE,
     'Verified via external search (2026-09-10): b. 8 June 1990, Hamar, Norway. Vitesse 2010-2014.'),
    (999, 'transfermarkt', 'Marcus Pedersen', 583404, NULL, 'manual_review', TRUE,
     'Verified via external search (2026-09-10): b. 16 July 2000, Hammerfest, Norway (Marcus Holmgren Pedersen). Feyenoord this era.');


-- STEP 5 (sanity check): confirm the split, and that each player_id
-- now has a clean, single-era history.
SELECT * FROM player_source_crosswalk WHERE player_id IN (271, 999) ORDER BY player_id, source;
SELECT * FROM player_team_season_history WHERE player_id IN (271, 999) ORDER BY player_id, season_id;
