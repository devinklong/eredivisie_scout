-- fbref_whoscored_candidate_pairs.sql
--
-- REFACTORED (2026-09-16): blocking now joins on team_id (resolved via
-- team_name_alias) instead of raw team string equality. The original
-- version's `ON f.season_id = w.season_id AND f.team = w.team` silently
-- excluded every player at a club whose FBref/WhoScored spellings
-- disagreed -- confirmed 2026-09-15/16 to be a real, previously hidden
-- gap (7 clubs, 2016-17/2017-18, ~112 recovered players once fixed).
-- Joining through team_id makes this immune to naming convention
-- differences going forward, as long as team_name_alias is kept
-- complete -- see team_source_crosswalk.sql's gap report for what
-- still needs a real alias row.
--
-- Uses pg_trgm's trigram similarity() as a cheap, loose first pass to
-- cut the candidate set down before real scoring (Jaro-Winkler +
-- token-sort, layered on top in Python -- see match_fbref_whoscored.py
-- in this same folder). The similarity() threshold here is
-- intentionally loose (0.3) -- this query's job is only to avoid an
-- all-pairs comparison within each (team, season) block, not to make
-- the real matching decision.
--
-- NOTE: no birth-year signal is available for this particular match --
-- eredivisie_whoscored_player_season_stats has no birth-year column at
-- all (only the FBref/soccerdata side has 'born'). Birth year becomes
-- usable once Transfermarkt bio data is loaded, not before.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

SELECT
    f.player_name AS fbref_name,
    w.player_name AS whoscored_name,
    canon.source_name AS team,
    fbref_alias.club_id AS team_id,
    f.season_id AS season_id,
    similarity(f.player_name, w.player_name) AS trgm_similarity
FROM eredivisie_soccerdata_player_season_stats f
JOIN team_name_alias fbref_alias
    ON fbref_alias.source = 'fbref' AND fbref_alias.source_name = f.team
JOIN team_name_alias ws_alias
    ON ws_alias.source = 'whoscored' AND ws_alias.club_id = fbref_alias.club_id
JOIN team_name_alias canon
    ON canon.source = 'transfermarkt' AND canon.club_id = fbref_alias.club_id
JOIN eredivisie_whoscored_player_season_stats w
    ON w.team = ws_alias.source_name AND w.season_id = f.season_id
WHERE similarity(f.player_name, w.player_name) > 0.3
ORDER BY f.season_id, fbref_alias.club_id, trgm_similarity DESC;
