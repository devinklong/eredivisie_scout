-- eredivisie_whoscored_player_season_stats.sql
-- Player-season totals derived from WhoScored raw events (passing,
-- possession, defense, final-third categories -- see
-- pipelines/whoscored/derive_*.py). Aggregated from per-match JSON
-- (data/whoscored/{season}/{match_id}.json) via
-- pipelines/whoscored/aggregate_and_load_whoscored_season.py.
--
-- FIXED (2026-09-02): earlier versions of this table had no team
-- column at all -- the derive_*.py functions only grouped by player
-- name, silently dropping which club they played for. Fixed by adding
-- team to every derive_*.py groupby; this table's unique key is now
-- (player_name, team, season_id). A player who genuinely transfers
-- between two Eredivisie clubs mid-season now correctly gets two
-- separate rows (one per club), rather than being silently merged.
--
-- Same identity limitation as soccerdata: no numeric player ID, name +
-- team + season only. WhoScored's raw events DO carry player_id -- the
-- derive_*.py functions just don't currently preserve it in their
-- output. Worth fixing before entity resolution work leans on this
-- table, since Transfermarkt's spieler/{id} would be a much cleaner
-- join target than fuzzy name matching, and the ID is sitting right
-- there in source data not yet captured.

DROP TABLE IF EXISTS eredivisie_whoscored_player_season_stats CASCADE;

CREATE TABLE eredivisie_whoscored_player_season_stats (
    stat_id                    SERIAL PRIMARY KEY,
    player_name                 TEXT NOT NULL,
    team                        TEXT NOT NULL,
    season_id                   INTEGER NOT NULL,
    matches_with_data            INTEGER NOT NULL,  -- how many match files this player appeared in at all -- NOT the same as matches_played (soccerdata's), since a player appearing once in ANY category counts here even with 0 in every stat
    -- Passing
    passes                      INTEGER,
    passes_completed              INTEGER,
    passes_pct                   NUMERIC(5,1),  -- recomputed from summed passes/passes_completed, NOT averaged across matches
    -- Possession (touches)
    touches                     INTEGER,
    touches_def_3rd               INTEGER,
    touches_mid_3rd               INTEGER,
    touches_att_3rd               INTEGER,
    touches_def_pen_area           INTEGER,
    touches_att_pen_area           INTEGER,
    -- Take-ons
    take_ons                    INTEGER,
    take_ons_won                  INTEGER,
    take_ons_won_pct              NUMERIC(5,1),  -- recomputed, not averaged
    dispossessed                 INTEGER,
    -- Defense
    tackles                     INTEGER,
    tackles_won                   INTEGER,
    tackles_def_3rd                INTEGER,
    tackles_mid_3rd                INTEGER,
    tackles_att_3rd                INTEGER,
    interceptions                 INTEGER,
    interceptions_def_3rd            INTEGER,
    interceptions_mid_3rd            INTEGER,
    interceptions_att_3rd            INTEGER,
    clearances                   INTEGER,
    dribbled_past                 INTEGER,  -- see docs/whoscored_qualifier_taxonomy.md -- this is the losing side of a Challenge, not a general duel stat
    errors                      INTEGER,
    -- Final-third / SCA proxy
    final_third_entries            INTEGER,
    pen_area_entries               INTEGER,
    UNIQUE (player_name, team, season_id)
);
SELECT COUNT(*) FROM eredivisie_whoscored_player_season_stats;
SELECT DISTINCT season_id FROM eredivisie_whoscored_player_season_stats ORDER BY season_id;
SELECT * FROM eredivisie_whoscored_player_season_stats WHERE team = 'Ajax' AND season_id = 2025;