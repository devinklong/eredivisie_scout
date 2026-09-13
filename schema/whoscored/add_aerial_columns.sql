-- add_aerial_columns.sql
-- Adds aerial duel stats to the EXISTING eredivisie_whoscored_player_season_stats
-- table. Run once, before the 13-season re-run -- the re-run's aggregation
-- step (aggregate_and_load_whoscored_season.py) needs these columns to
-- already exist.

ALTER TABLE eredivisie_whoscored_player_season_stats ADD COLUMN aerials INTEGER;
ALTER TABLE eredivisie_whoscored_player_season_stats ADD COLUMN aerials_won INTEGER;
ALTER TABLE eredivisie_whoscored_player_season_stats ADD COLUMN aerials_won_pct NUMERIC(5,1);
