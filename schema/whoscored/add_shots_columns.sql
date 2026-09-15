-- add_shots_columns.sql
-- Adds shots stats to eredivisie_whoscored_player_season_stats. Run
-- once, before the 13-season re-run.

ALTER TABLE eredivisie_whoscored_player_season_stats ADD COLUMN shots INTEGER;
ALTER TABLE eredivisie_whoscored_player_season_stats ADD COLUMN shots_on_target INTEGER;
ALTER TABLE eredivisie_whoscored_player_season_stats ADD COLUMN shots_on_target_pct NUMERIC(5,1);
