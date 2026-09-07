-- player_source_crosswalk.sql
-- Junction table: links a canonical player (players.player_id) to how
-- each source refers to that same person. One row per (player, source)
-- pair -- e.g. a confirmed FBref<->WhoScored match produces exactly 2
-- rows here (one 'fbref' row, one 'whoscored' row), both pointing at
-- the same player_id.
--
-- Deliberately a junction table, not one column per source on
-- players.sql -- decided during entity-resolution planning so adding a
-- future source (Transfermarkt, or anything else) doesn't require a
-- schema migration on the players table itself.

DROP TABLE IF EXISTS player_source_crosswalk CASCADE;

CREATE TABLE player_source_crosswalk (
    crosswalk_id     SERIAL PRIMARY KEY,
    player_id         INTEGER NOT NULL REFERENCES players(player_id),
    source             TEXT NOT NULL CHECK (source IN ('fbref', 'whoscored', 'transfermarkt')),
    source_name        TEXT NOT NULL,   -- the name exactly as that source uses it -- e.g. 'Klaas-Jan Huntelaar' (fbref) vs 'Klaas Jan Huntelaar' (whoscored) for the same player_id
    confidence          NUMERIC(5,4),    -- working_confidence at match time, for exact_normalized matches; NULL for manual_review matches (a human decision doesn't have a numeric score attached)
    match_method        TEXT NOT NULL CHECK (match_method IN ('exact_normalized', 'manual_review')),
    verified             BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE for manual_review matches (a human confirmed it); FALSE for exact_normalized until/unless separately spot-checked
    notes                TEXT,            -- carried over from fbref_whoscored_review_queue.csv's notes column, for manual_review rows
    UNIQUE (player_id, source, source_name)
);

SELECT COUNT(*) FROM player_source_crosswalk;
