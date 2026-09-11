-- add_source_native_id_column.sql
-- Adds source_native_id to the EXISTING player_source_crosswalk table.
-- NULL for fbref/whoscored rows (neither source has a real numeric
-- player ID -- name is the whole identity there). Populated for
-- transfermarkt rows with Transfermarkt's own player_id -- the one
-- genuinely clean numeric ID across all three sources, and the actual
-- payoff of matching Transfermarkt in at all: it's what lets
-- eredivisie_transfers/eredivisie_transfermarkt_player_bio be joined
-- to a canonical player directly by ID, not by fuzzy name matching
-- every time.

ALTER TABLE player_source_crosswalk ADD COLUMN source_native_id INTEGER;

SELECT * FROM player_source_crosswalk WHERE player_id = 271 ORDER BY source;