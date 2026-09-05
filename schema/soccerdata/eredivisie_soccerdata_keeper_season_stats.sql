-- eredivisie_keeper_season_stats.sql
-- Goalkeeper-specific season stats from FBref via soccerdata ('keeper'
-- stat_type -- confirmed working, per docs/stat_source_tracker.md).
-- Separate from eredivisie_player_season_stats since these columns only
-- apply to keepers -- avoids a mostly-NULL table for outfield players.
-- Same identity/entity-resolution limitation applies: no numeric player
-- ID from this source, name + team + season only.

DROP TABLE IF EXISTS eredivisie_keeper_season_stats CASCADE;

CREATE TABLE eredivisie_keeper_season_stats (
    keeper_stat_id           SERIAL PRIMARY KEY,
    player_name               TEXT NOT NULL,
    team                      TEXT NOT NULL,
    season_id                  INTEGER NOT NULL,
    nation                     TEXT,
    position                   TEXT,
    age                        TEXT,
    born                       INTEGER,
    matches_played              INTEGER,
    starts                      INTEGER,
    minutes                     INTEGER,
    nineties                    NUMERIC(5,1),
    goals_against                INTEGER,
    goals_against_per90           NUMERIC(5,2),
    shots_on_target_against       INTEGER,
    saves                       INTEGER,
    save_pct                    NUMERIC(5,1),
    wins                        INTEGER,
    draws                       INTEGER,
    losses                      INTEGER,
    clean_sheets                 INTEGER,
    clean_sheet_pct              NUMERIC(5,1),
    penalty_kicks_faced           INTEGER,
    penalty_kicks_allowed          INTEGER,
    penalty_kicks_saved            INTEGER,
    penalty_kicks_missed_by_opponent INTEGER,
    penalty_kick_save_pct          NUMERIC(5,1),
    UNIQUE (player_name, team, season_id)
);
SELECT COUNT(*) FROM eredivisie_keeper_season_stats;
SELECT * FROM eredivisie_keeper_season_stats;
