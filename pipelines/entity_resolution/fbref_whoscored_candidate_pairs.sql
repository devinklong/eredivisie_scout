-- fbref_whoscored_candidate_pairs.sql
-- First-pass candidate-pair filter for FBref <-> WhoScored entity
-- resolution -- blocks on season_id + team (team now normalized on
-- both sides, see aggregate_and_load_whoscored_season.py's
-- TEAM_NAME_NORMALIZATION), then uses pg_trgm's trigram similarity()
-- as a cheap, loose first pass to cut the candidate set down before
-- real scoring (Jaro-Winkler + token-sort, layered on top in Python --
-- see match_fbref_whoscored.py in this same folder).
--
-- The similarity() threshold here is intentionally loose (0.3) --
-- this query's job is only to avoid an all-pairs comparison within
-- each (team, season) block, not to make the real matching decision.
-- Read and executed directly by match_fbref_whoscored.py -- if you
-- change this file, the Python script picks up the change automatically
-- on next run (no need to update both places).
--
-- NOTE: no birth-year signal is available for this particular match --
-- eredivisie_whoscored_player_season_stats has no birth-year column at
-- all (only the FBref/soccerdata side has 'born'). Birth year becomes
-- usable once Transfermarkt bio data is loaded, not before.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

SELECT
    f.player_name AS fbref_name,
    w.player_name AS whoscored_name,
    f.team AS team,
    f.season_id AS season_id,
    similarity(f.player_name, w.player_name) AS trgm_similarity
FROM eredivisie_soccerdata_player_season_stats f
JOIN eredivisie_whoscored_player_season_stats w
    ON f.season_id = w.season_id AND f.team = w.team
WHERE similarity(f.player_name, w.player_name) > 0.3
ORDER BY f.season_id, f.team, trgm_similarity DESC;
