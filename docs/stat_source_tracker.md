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

## FBref (custom scraper, league-level pages)

Table structure and columns confirmed via `data-stat` attributes. Values for these categories are currently blank league-wide — FBref's Opta-sourced advanced data feed was pulled sitewide in January 2026. Columns listed here reflect what the tables are structured to hold, not what currently returns real values.

### passing
ranker, player, nationality, position, team, age, birth_year, minutes_90s, passes_completed, passes, passes_pct, passes_total_distance, passes_progressive_distance, passes_completed_short, passes_short, passes_pct_short, passes_completed_medium, passes_medium, passes_pct_medium, passes_completed_long, passes_long, passes_pct_long, assists, xg_assist_net, assisted_shots, passes_into_final_third, passes_into_penalty_area, crosses_into_penalty_area, matches

### possession
ranker, player, nationality, position, team, age, birth_year, minutes_90s, touches, touches_def_pen_area, touches_def_3rd, touches_mid_3rd, touches_att_3rd, touches_att_pen_area, touches_live_ball, take_ons, take_ons_won, take_ons_won_pct, take_ons_tackled, take_ons_tackled_pct, carries, carries_distance, carries_progressive_distance, carries_into_final_third, carries_into_penalty_area, miscontrols, dispossessed, passes_received, matches

### defense
ranker, player, nationality, position, team, age, birth_year, minutes_90s, tackles, tackles_won, tackles_def_3rd, tackles_mid_3rd, tackles_att_3rd, challenge_tackles, challenges, challenge_tackles_pct, challenges_lost, blocks, blocked_shots, blocked_passes, interceptions, tackles_interceptions, clearances, errors, matches

### goal_shot_creation
ranker, player, nationality, position, team, age, birth_year, minutes_90s, sca, sca_per90, sca_passes_live, sca_passes_dead, sca_take_ons, sca_shots, sca_fouled, sca_defense, gca, gca_per90, gca_passes_live, gca_passes_dead, gca_take_ons, gca_shots, gca_fouled, gca_defense, matches

## WhoScored

Not yet built. Planned as the source for shot-level event data to train an in-house xG model, and general match-event data (passes, touches, duels). No confirmed field list yet — to be filled in once a scraper is built and tested.

### shots (planned)
TBD

### events (planned)
TBD
