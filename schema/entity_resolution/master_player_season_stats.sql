-- master_player_season_stats.sql
--
-- One row per (player_id, team, season_id) -- a player-team-season
-- stint, matching the grain FBref/WhoScored's own tables already use.
-- A mid-season transfer produces two separate rows, same convention
-- used everywhere else in this project (never merged into one).
--
-- ANCHOR: the raw eredivisie_soccerdata_player_season_stats table
-- drives the base rows via LEFT JOIN, NOT the players/crosswalk
-- table. Confirmed via a real run (2026-09-12): anchoring on the
-- crosswalk instead undercounted real players by ~3,000 rows, since
-- any FBref player never matched to a WhoScored candidate at all
-- (every 2010-11 through 2012-13 player, since WhoScored has nothing
-- before 2013-14; or anyone whose name never crossed the similarity
-- threshold) never got a players/crosswalk row created for them at
-- all. Anchoring on the raw FBref table guarantees every real
-- player-season row appears; player_id/canonical_name are simply
-- NULL/fall back to the raw fbref name for anyone not yet
-- cross-source-linked.
--
-- COLUMN PREFIXING: fbref_* (outfield), gk_* (keeper-specific), ws_*
-- (WhoScored), tm_* (Transfermarkt bio). REQUIRED, not stylistic --
-- FBref's outfield stats and WhoScored's derived stats both have
-- columns literally named tackles_won and interceptions, with
-- different definitions and different methodologies. An unprefixed
-- join would silently produce ambiguous duplicate column names.
-- Deliberately kept BOTH sources' versions rather than dropping
-- either -- see compare_fbref_whoscored_defensive_stats.sql for how
-- much they actually agree before deciding whether to merge them at
-- the feature-engineering stage.
--
-- DISAMBIGUATION: the fbref_x join uses a SUBQUERY (not a plain join)
-- specifically to apply players.canonical_born BEFORE player_id gets
-- attached, not just downstream on the keeper/WhoScored joins.
-- CONFIRMED BUG (2026-09-12): an earlier version filtered born only
-- on the keeper-stats join, but the fbref_x/players join itself had
-- no disambiguator at all -- since BOTH split Marcus Pedersen
-- identities (271, 999) have an fbref crosswalk row reading the exact
-- same source_name "Marcus Pedersen", every real fbref row for either
-- of them matched BOTH player_ids, doubling his 7 real rows into 14
-- (both player_ids showing the full combined Vitesse+Feyenoord
-- history). Filtering at the point player_id is attached, not after,
-- fixes it for the fan-out's actual source. NULL for the ~1,700+
-- players with no known collision, so this doesn't restrict anyone
-- else -- same disambiguation reused from player_team_season_history.
--
-- Transfermarkt bio (height_cm, foot) is a SNAPSHOT, not season-
-- specific -- the same value repeats across every season row for that
-- player. Deliberate: a wide feature table for modeling benefits from
-- having it on every row rather than requiring a separate join
-- downstream.
--
-- FORMATTING NOTE: the CREATE VIEW statement below has NO blank lines
-- anywhere inside it, deliberately -- VS Code's SQL runner appears to
-- split execution on blank lines, not just semicolons, which
-- previously caused only a fragment of this statement to run. Keep it
-- that way if you edit this file -- add new columns/joins as extra
-- lines within the existing blocks, don't introduce blank lines to
-- "space things out."

DROP VIEW IF EXISTS master_player_season_stats;
CREATE VIEW master_player_season_stats AS
SELECT
    COALESCE(p.canonical_name, fbref.player_name) AS canonical_name,
    p.player_id,
    fbref.team,
    fbref.season_id,
    fbref.nation AS fbref_nation,
    fbref.position AS fbref_position,
    fbref.age AS fbref_age,
    fbref.born AS fbref_born,
    fbref.matches_played AS fbref_matches_played,
    fbref.minutes AS fbref_minutes,
    fbref.minutes_per_match AS fbref_minutes_per_match,
    fbref.minutes_pct AS fbref_minutes_pct,
    fbref.nineties AS fbref_nineties,
    fbref.starts AS fbref_starts,
    fbref.minutes_per_start AS fbref_minutes_per_start,
    fbref.complete_matches AS fbref_complete_matches,
    fbref.substitute_appearances AS fbref_substitute_appearances,
    fbref.minutes_per_sub AS fbref_minutes_per_sub,
    fbref.unused_sub AS fbref_unused_sub,
    fbref.points_per_match AS fbref_points_per_match,
    fbref.team_goals_while_on_pitch AS fbref_team_goals_while_on_pitch,
    fbref.team_goals_against_while_on_pitch AS fbref_team_goals_against_while_on_pitch,
    fbref.plus_minus AS fbref_plus_minus,
    fbref.plus_minus_per90 AS fbref_plus_minus_per90,
    fbref.on_off AS fbref_on_off,
    fbref.goals AS fbref_goals,
    fbref.assists AS fbref_assists,
    fbref.goals_plus_assists AS fbref_goals_plus_assists,
    fbref.non_penalty_goals AS fbref_non_penalty_goals,
    fbref.penalty_goals AS fbref_penalty_goals,
    fbref.penalty_attempts AS fbref_penalty_attempts,
    fbref.goals_per90 AS fbref_goals_per90,
    fbref.assists_per90 AS fbref_assists_per90,
    fbref.goals_plus_assists_per90 AS fbref_goals_plus_assists_per90,
    fbref.non_penalty_goals_per90 AS fbref_non_penalty_goals_per90,
    fbref.non_penalty_goals_plus_assists_per90 AS fbref_non_penalty_goals_plus_assists_per90,
    fbref.shots AS fbref_shots,
    fbref.shots_on_target AS fbref_shots_on_target,
    fbref.shots_on_target_pct AS fbref_shots_on_target_pct,
    fbref.shots_per90 AS fbref_shots_per90,
    fbref.shots_on_target_per90 AS fbref_shots_on_target_per90,
    fbref.goals_per_shot AS fbref_goals_per_shot,
    fbref.goals_per_shot_on_target AS fbref_goals_per_shot_on_target,
    fbref.yellow_cards AS fbref_yellow_cards,
    fbref.red_cards AS fbref_red_cards,
    fbref.second_yellow_cards AS fbref_second_yellow_cards,
    fbref.fouls_committed AS fbref_fouls_committed,
    fbref.fouls_drawn AS fbref_fouls_drawn,
    fbref.offsides AS fbref_offsides,
    fbref.crosses AS fbref_crosses,
    fbref.interceptions AS fbref_interceptions,
    fbref.tackles_won AS fbref_tackles_won,
    fbref.penalty_kicks_won AS fbref_penalty_kicks_won,
    fbref.penalty_kicks_conceded AS fbref_penalty_kicks_conceded,
    fbref.own_goals AS fbref_own_goals,
    gk.goals_against AS gk_goals_against,
    gk.goals_against_per90 AS gk_goals_against_per90,
    gk.shots_on_target_against AS gk_shots_on_target_against,
    gk.saves AS gk_saves,
    gk.save_pct AS gk_save_pct,
    gk.wins AS gk_wins,
    gk.draws AS gk_draws,
    gk.losses AS gk_losses,
    gk.clean_sheets AS gk_clean_sheets,
    gk.clean_sheet_pct AS gk_clean_sheet_pct,
    gk.penalty_kicks_faced AS gk_penalty_kicks_faced,
    gk.penalty_kicks_allowed AS gk_penalty_kicks_allowed,
    gk.penalty_kicks_saved AS gk_penalty_kicks_saved,
    gk.penalty_kicks_missed_by_opponent AS gk_penalty_kicks_missed_by_opponent,
    gk.penalty_kick_save_pct AS gk_penalty_kick_save_pct,
    ws.whoscored_player_id AS ws_whoscored_player_id,
    ws.matches_with_data AS ws_matches_with_data,
    ws.passes AS ws_passes,
    ws.passes_completed AS ws_passes_completed,
    ws.passes_pct AS ws_passes_pct,
    ws.touches AS ws_touches,
    ws.touches_def_3rd AS ws_touches_def_3rd,
    ws.touches_mid_3rd AS ws_touches_mid_3rd,
    ws.touches_att_3rd AS ws_touches_att_3rd,
    ws.touches_def_pen_area AS ws_touches_def_pen_area,
    ws.touches_att_pen_area AS ws_touches_att_pen_area,
    ws.take_ons AS ws_take_ons,
    ws.take_ons_won AS ws_take_ons_won,
    ws.take_ons_won_pct AS ws_take_ons_won_pct,
    ws.dispossessed AS ws_dispossessed,
    ws.tackles AS ws_tackles,
    ws.tackles_won AS ws_tackles_won,
    ws.tackles_def_3rd AS ws_tackles_def_3rd,
    ws.tackles_mid_3rd AS ws_tackles_mid_3rd,
    ws.tackles_att_3rd AS ws_tackles_att_3rd,
    ws.interceptions AS ws_interceptions,
    ws.interceptions_def_3rd AS ws_interceptions_def_3rd,
    ws.interceptions_mid_3rd AS ws_interceptions_mid_3rd,
    ws.interceptions_att_3rd AS ws_interceptions_att_3rd,
    ws.clearances AS ws_clearances,
    ws.dribbled_past AS ws_dribbled_past,
    ws.errors AS ws_errors,
    ws.final_third_entries AS ws_final_third_entries,
    ws.pen_area_entries AS ws_pen_area_entries,
    ws.aerials AS ws_aerials,
    ws.aerials_won AS ws_aerials_won,
    ws.aerials_won_pct AS ws_aerial_duel_win_pct,
    ROUND(((COALESCE(ws.tackles_won, 0) + COALESCE(ws.take_ons_won, 0))::numeric / NULLIF(COALESCE(ws.tackles, 0) + COALESCE(ws.dribbled_past, 0) + COALESCE(ws.take_ons, 0), 0)) * 100, 1) AS ws_ground_duel_win_pct,
    tm_bio.height_cm AS tm_height_cm,
    tm_bio.foot AS tm_foot,
    ROUND(fbref.yellow_cards / NULLIF(fbref.nineties, 0), 2) AS fbref_yellow_cards_per90,
    ROUND(fbref.red_cards / NULLIF(fbref.nineties, 0), 2) AS fbref_red_cards_per90,
    ROUND(fbref.second_yellow_cards / NULLIF(fbref.nineties, 0), 2) AS fbref_second_yellow_cards_per90,
    ROUND(fbref.fouls_committed / NULLIF(fbref.nineties, 0), 2) AS fbref_fouls_committed_per90,
    ROUND(fbref.fouls_drawn / NULLIF(fbref.nineties, 0), 2) AS fbref_fouls_drawn_per90,
    ROUND(fbref.offsides / NULLIF(fbref.nineties, 0), 2) AS fbref_offsides_per90,
    ROUND(fbref.crosses / NULLIF(fbref.nineties, 0), 2) AS fbref_crosses_per90,
    ROUND(fbref.interceptions / NULLIF(fbref.nineties, 0), 2) AS fbref_interceptions_per90,
    ROUND(fbref.tackles_won / NULLIF(fbref.nineties, 0), 2) AS fbref_tackles_won_per90,
    ROUND(fbref.penalty_kicks_won / NULLIF(fbref.nineties, 0), 2) AS fbref_penalty_kicks_won_per90,
    ROUND(fbref.penalty_kicks_conceded / NULLIF(fbref.nineties, 0), 2) AS fbref_penalty_kicks_conceded_per90,
    ROUND(fbref.own_goals / NULLIF(fbref.nineties, 0), 2) AS fbref_own_goals_per90,
    ROUND(gk.saves / NULLIF(fbref.nineties, 0), 2) AS gk_saves_per90,
    ROUND(ws.passes / NULLIF(fbref.nineties, 0), 2) AS ws_passes_per90,
    ROUND(ws.passes_completed / NULLIF(fbref.nineties, 0), 2) AS ws_passes_completed_per90,
    ROUND(ws.touches / NULLIF(fbref.nineties, 0), 2) AS ws_touches_per90,
    ROUND(ws.touches_def_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_touches_def_3rd_per90,
    ROUND(ws.touches_mid_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_touches_mid_3rd_per90,
    ROUND(ws.touches_att_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_touches_att_3rd_per90,
    ROUND(ws.touches_def_pen_area / NULLIF(fbref.nineties, 0), 2) AS ws_touches_def_pen_area_per90,
    ROUND(ws.touches_att_pen_area / NULLIF(fbref.nineties, 0), 2) AS ws_touches_att_pen_area_per90,
    ROUND(ws.take_ons / NULLIF(fbref.nineties, 0), 2) AS ws_take_ons_per90,
    ROUND(ws.take_ons_won / NULLIF(fbref.nineties, 0), 2) AS ws_take_ons_won_per90,
    ROUND(ws.dispossessed / NULLIF(fbref.nineties, 0), 2) AS ws_dispossessed_per90,
    ROUND(ws.tackles / NULLIF(fbref.nineties, 0), 2) AS ws_tackles_per90,
    ROUND(ws.tackles_won / NULLIF(fbref.nineties, 0), 2) AS ws_tackles_won_per90,
    ROUND(ws.tackles_def_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_tackles_def_3rd_per90,
    ROUND(ws.tackles_mid_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_tackles_mid_3rd_per90,
    ROUND(ws.tackles_att_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_tackles_att_3rd_per90,
    ROUND(ws.interceptions / NULLIF(fbref.nineties, 0), 2) AS ws_interceptions_per90,
    ROUND(ws.interceptions_def_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_interceptions_def_3rd_per90,
    ROUND(ws.interceptions_mid_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_interceptions_mid_3rd_per90,
    ROUND(ws.interceptions_att_3rd / NULLIF(fbref.nineties, 0), 2) AS ws_interceptions_att_3rd_per90,
    ROUND(ws.clearances / NULLIF(fbref.nineties, 0), 2) AS ws_clearances_per90,
    ROUND(ws.dribbled_past / NULLIF(fbref.nineties, 0), 2) AS ws_dribbled_past_per90,
    ROUND(ws.errors / NULLIF(fbref.nineties, 0), 2) AS ws_errors_per90,
    ROUND(ws.final_third_entries / NULLIF(fbref.nineties, 0), 2) AS ws_final_third_entries_per90,
    ROUND(ws.pen_area_entries / NULLIF(fbref.nineties, 0), 2) AS ws_pen_area_entries_per90,
    ROUND(ws.aerials / NULLIF(fbref.nineties, 0), 2) AS ws_aerials_per90,
    ROUND(ws.aerials_won / NULLIF(fbref.nineties, 0), 2) AS ws_aerials_won_per90
FROM eredivisie_soccerdata_player_season_stats fbref
LEFT JOIN (SELECT psc.source_name, psc.player_id, pl.canonical_born FROM player_source_crosswalk psc JOIN players pl ON pl.player_id = psc.player_id WHERE psc.source = 'fbref') fbref_x ON fbref_x.source_name = fbref.player_name AND (fbref_x.canonical_born IS NULL OR fbref_x.canonical_born = fbref.born)
LEFT JOIN players p ON p.player_id = fbref_x.player_id
LEFT JOIN eredivisie_keeper_season_stats gk ON gk.player_name = fbref.player_name AND gk.team = fbref.team AND gk.season_id = fbref.season_id AND (p.canonical_born IS NULL OR p.canonical_born = gk.born)
LEFT JOIN (SELECT psc.player_id, w.team, w.season_id, w.whoscored_player_id, w.matches_with_data, w.passes, w.passes_completed, w.passes_pct, w.touches, w.touches_def_3rd, w.touches_mid_3rd, w.touches_att_3rd, w.touches_def_pen_area, w.touches_att_pen_area, w.take_ons, w.take_ons_won, w.take_ons_won_pct, w.dispossessed, w.tackles, w.tackles_won, w.tackles_def_3rd, w.tackles_mid_3rd, w.tackles_att_3rd, w.interceptions, w.interceptions_def_3rd, w.interceptions_mid_3rd, w.interceptions_att_3rd, w.clearances, w.dribbled_past, w.errors, w.final_third_entries, w.pen_area_entries, w.aerials, w.aerials_won, w.aerials_won_pct FROM player_source_crosswalk psc JOIN eredivisie_whoscored_player_season_stats w ON w.player_name = psc.source_name JOIN players pl ON pl.player_id = psc.player_id WHERE psc.source = 'whoscored' AND (pl.canonical_whoscored_player_id IS NULL OR pl.canonical_whoscored_player_id = w.whoscored_player_id)) ws ON ws.player_id = p.player_id AND ws.team = fbref.team AND ws.season_id = fbref.season_id
LEFT JOIN player_source_crosswalk tm_x ON tm_x.player_id = p.player_id AND tm_x.source = 'transfermarkt'
LEFT JOIN eredivisie_transfermarkt_player_bio tm_bio ON tm_bio.player_id = tm_x.source_native_id;

-- Sanity checks below -- run these separately, after the CREATE VIEW above:
SELECT COUNT(*) FROM master_player_season_stats;
SELECT COUNT(*) FROM master_player_season_stats WHERE ws_whoscored_player_id IS NOT NULL;
SELECT COUNT(*) FROM master_player_season_stats WHERE tm_height_cm IS NOT NULL;
SELECT * FROM master_player_season_stats WHERE player_id IN (271, 999) ORDER BY player_id, season_id;
