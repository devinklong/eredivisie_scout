-- add_whoscored_player_id_column.sql
-- Adds WhoScored's own native player_id to eredivisie_whoscored_player_season_stats.
-- This is a SEPARATE ID namespace from Transfermarkt's player_id -- do not
-- join the two directly. The entity-resolution crosswalk table is what
-- links a whoscored_player_id to a canonical player_id, not a direct join.

-- Option A: altering the existing table in place (keeps current data,
-- new column starts NULL until aggregate_and_load_whoscored_season.py
-- is rerun to backfill it).
ALTER TABLE eredivisie_whoscored_player_season_stats
ADD COLUMN whoscored_player_id INTEGER;

-- Option B: if regenerating the table fresh from schema (the existing
-- eredivisie_whoscored_player_season_stats.sql already does
-- DROP TABLE IF EXISTS ... CASCADE), add this column into that
-- CREATE TABLE block instead, right after matches_with_data:
--
-- matches_with_data            INTEGER NOT NULL,
-- whoscored_player_id          INTEGER,  -- WhoScored's own native player ID, carried through
--                                         -- from raw events (see derive_*.py). NOT the same ID
--                                         -- namespace as Transfermarkt's player_id -- do not join
--                                         -- the two directly without going through the
--                                         -- entity-resolution crosswalk table.

SELECT COUNT(*) FROM eredivisie_whoscored_player_season_stats WHERE whoscored_player_id IS NOT NULL;
