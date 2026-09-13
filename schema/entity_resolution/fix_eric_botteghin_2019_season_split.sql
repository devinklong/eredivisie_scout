-- fix_eric_botteghin_2019_season_split.sql
-- Confirmed (2026-09-12) via master_player_season_stats' WhoScored
-- fan-out fix surfacing it, then verified via a systemic audit that
-- this is the ONLY such case in the whole table (exactly 1 result):
-- Eric Botteghin's 2019 Feyenoord season is split across two rows --
-- 'Eric Botteghin' and 'Eric Fernando Botteghin' -- same
-- whoscored_player_id (24260), same real season, split purely because
-- WhoScored used both spellings across different matches within that
-- one season and aggregate_and_load_whoscored_season.py grouped by
-- the literal name string, not whoscored_player_id. NOT the same as
-- his already-documented cross-SEASON spelling difference (that one
-- is fine, does not need fixing) -- this is specifically the two 2019
-- rows for the SAME season.
--
-- Sums every additive field directly from both real rows via SQL
-- (not manually copied from a screenshot, to avoid missing a column)
-- into whichever row is kept, recomputing percentage fields from the
-- summed totals rather than averaging -- same convention already used
-- in aggregate_and_load_whoscored_season.py and the original Ippel
-- duplicate-row fix.

UPDATE eredivisie_whoscored_player_season_stats AS keep SET matches_with_data = keep.matches_with_data + drop_row.matches_with_data, passes = keep.passes + drop_row.passes, passes_completed = keep.passes_completed + drop_row.passes_completed, passes_pct = CASE WHEN (keep.passes + drop_row.passes) > 0 THEN ROUND(((keep.passes_completed + drop_row.passes_completed)::numeric / (keep.passes + drop_row.passes)) * 100, 1) ELSE NULL END, touches = keep.touches + drop_row.touches, touches_def_3rd = keep.touches_def_3rd + drop_row.touches_def_3rd, touches_mid_3rd = keep.touches_mid_3rd + drop_row.touches_mid_3rd, touches_att_3rd = keep.touches_att_3rd + drop_row.touches_att_3rd, touches_def_pen_area = keep.touches_def_pen_area + drop_row.touches_def_pen_area, touches_att_pen_area = keep.touches_att_pen_area + drop_row.touches_att_pen_area, take_ons = keep.take_ons + drop_row.take_ons, take_ons_won = keep.take_ons_won + drop_row.take_ons_won, take_ons_won_pct = CASE WHEN (keep.take_ons + drop_row.take_ons) > 0 THEN ROUND(((keep.take_ons_won + drop_row.take_ons_won)::numeric / (keep.take_ons + drop_row.take_ons)) * 100, 1) ELSE NULL END, dispossessed = keep.dispossessed + drop_row.dispossessed, tackles = keep.tackles + drop_row.tackles, tackles_won = keep.tackles_won + drop_row.tackles_won, tackles_def_3rd = keep.tackles_def_3rd + drop_row.tackles_def_3rd, tackles_mid_3rd = keep.tackles_mid_3rd + drop_row.tackles_mid_3rd, tackles_att_3rd = keep.tackles_att_3rd + drop_row.tackles_att_3rd, interceptions = keep.interceptions + drop_row.interceptions, interceptions_def_3rd = keep.interceptions_def_3rd + drop_row.interceptions_def_3rd, interceptions_mid_3rd = keep.interceptions_mid_3rd + drop_row.interceptions_mid_3rd, interceptions_att_3rd = keep.interceptions_att_3rd + drop_row.interceptions_att_3rd, clearances = keep.clearances + drop_row.clearances, dribbled_past = keep.dribbled_past + drop_row.dribbled_past, errors = keep.errors + drop_row.errors, final_third_entries = keep.final_third_entries + drop_row.final_third_entries, pen_area_entries = keep.pen_area_entries + drop_row.pen_area_entries FROM eredivisie_whoscored_player_season_stats AS drop_row WHERE keep.whoscored_player_id = 24260 AND keep.team = 'Feyenoord' AND keep.season_id = 2019 AND keep.player_name = 'Eric Botteghin' AND drop_row.whoscored_player_id = 24260 AND drop_row.team = 'Feyenoord' AND drop_row.season_id = 2019 AND drop_row.player_name = 'Eric Fernando Botteghin';

DELETE FROM eredivisie_whoscored_player_season_stats WHERE whoscored_player_id = 24260 AND team = 'Feyenoord' AND season_id = 2019 AND player_name = 'Eric Fernando Botteghin';

-- Sanity check: should return exactly 1 row now, with summed stats.
SELECT * FROM eredivisie_whoscored_player_season_stats WHERE whoscored_player_id = 24260 AND team = 'Feyenoord' AND season_id = 2019;
