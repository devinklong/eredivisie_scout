# Stat Source Tracker

Internal tracker of stat types from scraping for Postgres.

Scoped to player-level stats. Team-level stats are a potential future addition, not covered here.

## soccerdata (FBref-backed)

Confirmed working — `stat_type` values return real data.

### standard
nation, pos, age, born, Playing Time_MP, Playing Time_Starts, Playing Time_Min, Playing Time_90s, Performance_Gls, Performance_Ast, Performance_G+A, Performance_G-PK, Performance_PK, Performance_PKatt, Performance_CrdY, Performance_CrdR, Per 90 Minutes_Gls, Per 90 Minutes_Ast, Per 90 Minutes_G+A, Per 90 Minutes_G-PK, Per 90 Minutes_G+A-PK

### shooting
nation, pos, age, born, 90s, Standard_Gls, Standard_Sh, Standard_SoT, Standard_SoT%, Standard_Sh/90, Standard_SoT/90, Standard_G/Sh, Standard_G/SoT, Standard_PK, Standard_PKatt

### playing_time
nation, pos, age, born, Playing Time_MP, Playing Time_Min, Playing Time_Mn/MP, Playing Time_Min%, Playing Time_90s, Starts_Starts, Starts_Mn/Start, Starts_Compl, Subs_Subs, Subs_Mn/Sub, Subs_unSub, Team Success_PPM, Team Success_onG, Team Success_onGA, Team Success_+/-, Team Success_+/-90, Team Success_On-Off

### misc
nation, pos, age, born, 90s, Performance_CrdY, Performance_CrdR, Performance_2CrdY, Performance_Fls, Performance_Fld, Performance_Off, Performance_Crs, Performance_Int, Performance_TklW, Performance_PKwon, Performance_PKcon, Performance_OG

### keeper
nation, pos, age, born, Playing Time_MP, Playing Time_Starts, Playing Time_Min, Playing Time_90s, Performance_GA, Performance_GA90, Performance_SoTA, Performance_Saves, Performance_Save%, Performance_W, Performance_D, Performance_L, Performance_CS, Performance_CS%, Penalty Kicks_PKatt, Penalty Kicks_PKA, Penalty Kicks_PKsv, Penalty Kicks_PKm, Penalty Kicks_Save%

## FBref (custom scraper, league-level pages) — VALUES NOT ACCESSIBLE

Every category below is confirmed **NOT USABLE**. Table structure and columns are real (confirmed via `data-stat` attributes), but every cell is blank. This is not a scraper problem — FBref's Opta-sourced advanced data feed was pulled sitewide in January 2026, retroactively across all seasons.

**Confirmed retroactive, not just a current-season gap:** blank values verified directly (both via scraper and manual browser check) across three separate points in time — the current in-progress season, the fully completed 2025-26 season, and the fully completed 2021-22 season. Only non-Opta counting stats (e.g. assists) still populate; every Opta-derived metric (completions, distances, xG-family) is empty regardless of how far back the season is. No season, however old, has a free FBref fallback for this data category.

Columns are listed for reference only (e.g. to match naming conventions if this data is ever sourced elsewhere) — do not build a pipeline expecting real values from these.

### passing — NO DATA
ranker, player, nationality, position, team, age, birth_year, minutes_90s, passes_completed, passes, passes_pct, passes_total_distance, passes_progressive_distance, passes_completed_short, passes_short, passes_pct_short, passes_completed_medium, passes_medium, passes_pct_medium, passes_completed_long, passes_long, passes_pct_long, assists, xg_assist_net, assisted_shots, passes_into_final_third, passes_into_penalty_area, crosses_into_penalty_area, matches

### possession — NO DATA
ranker, player, nationality, position, team, age, birth_year, minutes_90s, touches, touches_def_pen_area, touches_def_3rd, touches_mid_3rd, touches_att_3rd, touches_att_pen_area, touches_live_ball, take_ons, take_ons_won, take_ons_won_pct, take_ons_tackled, take_ons_tackled_pct, carries, carries_distance, carries_progressive_distance, carries_into_final_third, carries_into_penalty_area, miscontrols, dispossessed, passes_received, matches

### defense — NO DATA
ranker, player, nationality, position, team, age, birth_year, minutes_90s, tackles, tackles_won, tackles_def_3rd, tackles_mid_3rd, tackles_att_3rd, challenge_tackles, challenges, challenge_tackles_pct, challenges_lost, blocks, blocked_shots, blocked_passes, interceptions, tackles_interceptions, clearances, errors, matches

### goal_shot_creation — NO DATA
ranker, player, nationality, position, team, age, birth_year, minutes_90s, sca, sca_per90, sca_passes_live, sca_passes_dead, sca_take_ons, sca_shots, sca_fouled, sca_defense, gca, gca_per90, gca_passes_live, gca_passes_dead, gca_take_ons, gca_shots, gca_fouled, gca_defense, matches

## WhoScored (via soccerdata) — CONFIRMED WORKING

Confirmed available through soccerdata directly for NED-Eredivisie specifically (required adding a custom `WhoScored` entry to `league_dict.json` — see FBref's entry in the same file). `read_schedule()` and `read_events()` both tested successfully against real Eredivisie matches.

### schedule
stage_id, game_id, status, start_time, home_team_id, home_team, home_yellow_cards, home_red_cards, away_team_id, away_team, away_yellow_cards, away_red_cards, has_incidents_summary, has_preview, score_changed_at, elapsed, last_scorer, is_top_match, home_team_country_code, away_team_country_code, comment_count, is_lineup_confirmed, is_stream_available, match_is_opta, home_team_country_name, away_team_country_name, date, home_score, away_score, incidents, bets, period, home_extratime_score, away_extratime_score, home_penalty_score, away_penalty_score, started_at_utc, first_half_ended_at_utc, second_half_started_at_utc, stage

### missing_players
game_id, player_id, reason, status

### events (default format)
game_id, period, minute, second, expanded_minute, type, outcome_type, team_id, team, player_id, player, x, y, end_x, end_y, goal_mouth_y, goal_mouth_z, blocked_x, blocked_y, qualifiers, is_touch, is_shot, is_goal, card_type, related_event_id, related_player_id

### events (spadl format — standardized, includes shot location/outcome for xG modeling)
game_id, original_event_id, period_id, time_seconds, team_id, player_id, start_x, end_x, start_y, end_y, type_id, result_id, bodypart_id, action_id, player, team

### events (atomic-spadl format)
game_id, original_event_id, action_id, period_id, time_seconds, team_id, player_id, x, y, dx, dy, type_id, bodypart_id, player, team

### events (loader format — returns games/teams/players/events as separate DataFrames)
- games: game_id, season_id, competition_id, game_day, game_date, home_team_id, away_team_id, home_score, away_score, duration, referee, venue, attendance, home_manager, away_manager
- teams: team_id, team_name
- players: game_id, team_id, player_id, player_name, is_starter, minutes_played, jersey_number, starting_position
- events: game_id, event_id, period_id, team_id, player_id, type_id, timestamp, minute, second, outcome, start_x, start_y, end_x, end_y, qualifiers, related_player_id, touch, goal, shot, type_name

## WhoScored derived output (this project's own pipelines/whoscored/derive_*.py)

Not raw source fields — this is what this project computes FROM the raw events above. Keyed `(player, team)` in every category as of the 2026-09-02 team-attribution fix (originally player-only, a real bug — see patch_list.md). Aggregated to player-season totals in `eredivisie_whoscored_player_season_stats`, keyed `(player_name, team, season_id)`.

### passing
player, team, passes, passes_completed, passes_pct

### touches (possession)
player, team, touches, touches_def_3rd, touches_mid_3rd, touches_att_3rd, touches_def_pen_area, touches_att_pen_area

### take_ons
player, team, take_ons, take_ons_won, take_ons_won_pct

### dispossessed
player, team, dispossessed (count only)

### tackles
player, team, tackles, tackles_won, tackles_def_3rd, tackles_mid_3rd, tackles_att_3rd

### interceptions
player, team, interceptions, interceptions_def_3rd, interceptions_mid_3rd, interceptions_att_3rd

### clearances / dribbled_past / errors
player, team, count only for each — `dribbled_past` is NOT a win/loss stat, see whoscored_qualifier_taxonomy.md's cross-event relationships table for why

### final_third_entries
player, team, final_third_entries, pen_area_entries — pass-based only (SCA proxy), carries out of scope for v1
