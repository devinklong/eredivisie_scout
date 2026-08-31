-- eredivisie_player_season_stats.sql
-- Player-season stats from FBref via soccerdata (standard, shooting,
-- playing_time, misc categories combined -- the 4 non-keeper categories
-- confirmed working, per docs/stat_source_tracker.md). One row per
-- player, per season, per team. Covers all outfield AND keeper players
-- for these general categories; keeper-specific stats (saves, GA, etc.)
-- live in the separate eredivisie_keeper_season_stats table.
--
-- IMPORTANT LIMITATION: soccerdata's FBref output does NOT expose a
-- numeric player ID -- player identity here is name + team + season
-- only (the DataFrame's own index, not a stable ID like Transfermarkt's
-- spieler/{id}). Entity resolution against eredivisie_transfers will
-- need fuzzy name matching, not a clean ID join. Flagged in
-- v1_roadmap.md's entity-resolution item.
--
-- Duplicate columns across FBref's own categories (e.g. CrdY/CrdR appear
-- in both 'standard' and 'misc') are deduplicated here in favor of
-- misc's version, since it additionally includes 2CrdY (second yellow).

DROP TABLE IF EXISTS eredivisie_player_season_stats CASCADE;

CREATE TABLE eredivisie_player_season_stats (
    stat_id                 SERIAL PRIMARY KEY,
    player_name             TEXT NOT NULL,           -- No numeric ID available from this source -- see limitation note above
    team                    TEXT NOT NULL,
    season_id                INTEGER NOT NULL,        -- Starting year of the season, matching eredivisie_transfers/eredivisie_club_status convention
    nation                   TEXT,
    position                 TEXT,
    age                      TEXT,                     -- FBref returns this as text (e.g. '23-105'), not cleanly numeric -- parse downstream if a plain age integer is needed
    born                     INTEGER,                  -- Birth year
    -- Playing time (from 'playing_time' category -- more complete than 'standard'/duplicate fields)
    matches_played            INTEGER,
    minutes                   INTEGER,
    minutes_per_match         NUMERIC(5,1),
    minutes_pct               NUMERIC(5,1),
    nineties                  NUMERIC(5,1),
    starts                    INTEGER,
    minutes_per_start         NUMERIC(5,1),
    complete_matches          INTEGER,
    substitute_appearances    INTEGER,
    minutes_per_sub           NUMERIC(5,1),
    unused_sub                INTEGER,
    points_per_match           NUMERIC(4,2),
    team_goals_while_on_pitch  INTEGER,
    team_goals_against_while_on_pitch INTEGER,
    plus_minus                 INTEGER,
    plus_minus_per90           NUMERIC(5,2),
    on_off                     NUMERIC(5,2),
    -- Standard (goals/assists/cards)
    goals                     INTEGER,
    assists                   INTEGER,
    goals_plus_assists         INTEGER,
    non_penalty_goals          INTEGER,
    penalty_goals               INTEGER,
    penalty_attempts            INTEGER,
    goals_per90                 NUMERIC(5,2),
    assists_per90                NUMERIC(5,2),
    goals_plus_assists_per90     NUMERIC(5,2),
    non_penalty_goals_per90       NUMERIC(5,2),
    non_penalty_goals_plus_assists_per90 NUMERIC(5,2),
    -- Shooting
    shots                     INTEGER,
    shots_on_target            INTEGER,
    shots_on_target_pct        NUMERIC(5,1),
    shots_per90                 NUMERIC(5,2),
    shots_on_target_per90        NUMERIC(5,2),
    goals_per_shot               NUMERIC(5,2),
    goals_per_shot_on_target      NUMERIC(5,2),
    -- Misc (includes cards -- dedup'd from standard's version, adds 2CrdY)
    yellow_cards                INTEGER,
    red_cards                   INTEGER,
    second_yellow_cards          INTEGER,
    fouls_committed              INTEGER,
    fouls_drawn                  INTEGER,
    offsides                    INTEGER,
    crosses                     INTEGER,
    interceptions                INTEGER,
    tackles_won                  INTEGER,
    penalty_kicks_won             INTEGER,
    penalty_kicks_conceded         INTEGER,
    own_goals                    INTEGER,
    UNIQUE (player_name, team, season_id)
);
SELECT COUNT(*) FROM eredivisie_player_season_stats;
SELECT player_name, team, season_id, COUNT(*) -- trying to find missing 2 player rows 
FROM eredivisie_player_season_stats
GROUP BY player_name, team, season_id
HAVING COUNT(*) > 1;