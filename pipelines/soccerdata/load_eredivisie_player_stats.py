"""
Loads Eredivisie player-season stats from FBref (via soccerdata) into
Postgres, covering the same season range as the Transfermarkt pipeline:
2010-11 through 2025-26 (16 seasons). Uses the 5 confirmed-working
soccerdata stat_types (standard, shooting, playing_time, misc, keeper --
see docs/stat_source_tracker.md). passing/possession/defense/GCA are NOT
included -- confirmed unavailable sitewide (January 2026 Opta license
termination), not a soccerdata limitation.

Combines standard + shooting + playing_time + misc into one wide table
per player-season (they share the same player population). keeper stats
go into a separate table (only applies to goalkeepers).

IMPORTANT: unlike Transfermarkt, this source has NO numeric player ID --
identity is name + team + season only. Flagged in the schema files and
v1_roadmap.md's entity-resolution item.

Note the scope difference from the Transfermarkt pipeline: this pulls
ALL 18 clubs active in a given season directly from one soccerdata call
per season (soccerdata returns the whole league at once) -- no per-club
looping needed, since FBref/soccerdata already scopes to "who was
actually in the Eredivisie that season," unlike Transfermarkt's
club-history pages which needed the separate eredivisie_club_status
filter.
"""

import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASONS = [f"{y}-{str(y + 1)[-2:]}" for y in range(2010, 2026)]  # 2010-11 through 2025-26


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def season_to_id(season_str):
    """'2010-11' -> 2010, matching the season_id convention used in the
    Transfermarkt tables."""
    return int(season_str.split("-")[0])


def flatten_columns(df):
    df.columns = ["_".join([str(x) for x in col if x]) if isinstance(col, tuple) else col
                   for col in df.columns]
    return df


def fetch_season_player_stats(fbref, season_id):
    """Pulls standard/shooting/playing_time/misc for one season and
    merges them into one combined DataFrame, keyed on the shared index
    (league, season, team, player)."""
    standard = flatten_columns(fbref.read_player_season_stats(stat_type="standard"))
    shooting = flatten_columns(fbref.read_player_season_stats(stat_type="shooting"))
    playing_time = flatten_columns(fbref.read_player_season_stats(stat_type="playing_time"))
    misc = flatten_columns(fbref.read_player_season_stats(stat_type="misc"))

    combined = standard.join(
        shooting, how="outer", lsuffix="_std", rsuffix="_sht"
    ).join(
        playing_time, how="outer", rsuffix="_pt"
    ).join(
        misc, how="outer", rsuffix="_misc"
    )
    return combined


def build_player_rows(combined_df, season_id):
    rows = []
    for idx, row in combined_df.iterrows():
        # idx is (league, season, team, player) per soccerdata's multi-index
        team = idx[2]
        player = idx[3]

        def g(col, default=None):
            if col not in row:
                return default
            value = row[col]
            return default if pd.isna(value) else value

        rows.append((
            player, team, season_id,
            g("nation"), g("pos"), g("age"), g("born"),
            g("Playing Time_MP_pt"), g("Playing Time_Min_pt"), g("Playing Time_Mn/MP"),
            g("Playing Time_Min%"), g("Playing Time_90s_pt"), g("Starts_Starts"),
            g("Starts_Mn/Start"), g("Starts_Compl"), g("Subs_Subs"), g("Subs_Mn/Sub"),
            g("Subs_unSub"), g("Team Success_PPM"), g("Team Success_onG"),
            g("Team Success_onGA"), g("Team Success_+/-"), g("Team Success_+/-90"),
            g("Team Success_On-Off"),
            g("Performance_Gls_std"), g("Performance_Ast"), g("Performance_G+A"),
            g("Performance_G-PK"), g("Performance_PK"), g("Performance_PKatt_std"),
            g("Per 90 Minutes_Gls"), g("Per 90 Minutes_Ast"), g("Per 90 Minutes_G+A"),
            g("Per 90 Minutes_G-PK"), g("Per 90 Minutes_G+A-PK"),
            g("Standard_Sh"), g("Standard_SoT"), g("Standard_SoT%"),
            g("Standard_Sh/90"), g("Standard_SoT/90"), g("Standard_G/Sh"), g("Standard_G/SoT"),
            g("Performance_CrdY_misc"), g("Performance_CrdR_misc"), g("Performance_2CrdY"),
            g("Performance_Fls"), g("Performance_Fld"), g("Performance_Off"),
            g("Performance_Crs"), g("Performance_Int"), g("Performance_TklW"),
            g("Performance_PKwon"), g("Performance_PKcon"), g("Performance_OG"),
        ))
    return rows


def build_keeper_rows(keeper_df, season_id):
    rows = []
    for idx, row in keeper_df.iterrows():
        team = idx[2]
        player = idx[3]

        def g(col, default=None):
            if col not in row:
                return default
            value = row[col]
            return default if pd.isna(value) else value

        rows.append((
            player, team, season_id,
            g("nation"), g("pos"), g("age"), g("born"),
            g("Playing Time_MP"), g("Playing Time_Starts"), g("Playing Time_Min"),
            g("Playing Time_90s"), g("Performance_GA"), g("Performance_GA90"),
            g("Performance_SoTA"), g("Performance_Saves"), g("Performance_Save%"),
            g("Performance_W"), g("Performance_D"), g("Performance_L"),
            g("Performance_CS"), g("Performance_CS%"),
            g("Penalty Kicks_PKatt"), g("Penalty Kicks_PKA"), g("Penalty Kicks_PKsv"),
            g("Penalty Kicks_PKm"), g("Penalty Kicks_Save%"),
        ))
    return rows


def main():
    conn = get_connection()

    player_insert_sql = """
        INSERT INTO eredivisie_player_season_stats
            (player_name, team, season_id, nation, position, age, born,
             matches_played, minutes, minutes_per_match, minutes_pct, nineties,
             starts, minutes_per_start, complete_matches, substitute_appearances,
             minutes_per_sub, unused_sub, points_per_match, team_goals_while_on_pitch,
             team_goals_against_while_on_pitch, plus_minus, plus_minus_per90, on_off,
             goals, assists, goals_plus_assists, non_penalty_goals, penalty_goals,
             penalty_attempts, goals_per90, assists_per90, goals_plus_assists_per90,
             non_penalty_goals_per90, non_penalty_goals_plus_assists_per90,
             shots, shots_on_target, shots_on_target_pct, shots_per90,
             shots_on_target_per90, goals_per_shot, goals_per_shot_on_target,
             yellow_cards, red_cards, second_yellow_cards, fouls_committed,
             fouls_drawn, offsides, crosses, interceptions, tackles_won,
             penalty_kicks_won, penalty_kicks_conceded, own_goals)
        VALUES %s
        ON CONFLICT (player_name, team, season_id) DO NOTHING
    """

    keeper_insert_sql = """
        INSERT INTO eredivisie_keeper_season_stats
            (player_name, team, season_id, nation, position, age, born,
             matches_played, starts, minutes, nineties, goals_against,
             goals_against_per90, shots_on_target_against, saves, save_pct,
             wins, draws, losses, clean_sheets, clean_sheet_pct,
             penalty_kicks_faced, penalty_kicks_allowed, penalty_kicks_saved,
             penalty_kicks_missed_by_opponent, penalty_kick_save_pct)
        VALUES %s
        ON CONFLICT (player_name, team, season_id) DO NOTHING
    """

    total_players = 0
    total_keepers = 0

    with conn.cursor() as cur:
        for season in SEASONS:
            season_id = season_to_id(season)
            print(f"\nFetching {season}...")
            try:
                fbref = sd.FBref(LEAGUE, season)
                combined = fetch_season_player_stats(fbref, season_id)
                keeper_df = flatten_columns(fbref.read_player_season_stats(stat_type="keeper"))
            except Exception as e:
                print(f"  FAILED for {season}: {type(e).__name__}: {e}")
                continue

            player_rows = build_player_rows(combined, season_id)
            keeper_rows = build_keeper_rows(keeper_df, season_id)

            if player_rows:
                execute_values(cur, player_insert_sql, player_rows)
            if keeper_rows:
                execute_values(cur, keeper_insert_sql, keeper_rows)
            conn.commit()

            total_players += len(player_rows)
            total_keepers += len(keeper_rows)
            print(f"  Inserted {len(player_rows)} player-season rows, "
                  f"{len(keeper_rows)} keeper-season rows")

    conn.close()
    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    print(f"Total player-season rows inserted: {total_players}")
    print(f"Total keeper-season rows inserted: {total_keepers}")


if __name__ == "__main__":
    main()
