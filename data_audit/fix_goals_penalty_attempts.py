"""
Targeted fix for the fbref_goals/fbref_penalty_attempts bug found
2026-09-28: load_eredivisie_player_stats.py's build_player_rows() was
looking up 'Performance_Gls_std'/'Performance_PKatt_std', but real
soccerdata output has no _std suffix on those two specific columns
(confirmed via direct inspection) -- so both were silently NULL for
every row, every season, since this project's very first load.

Does NOT re-run the full loader: eredivisie_soccerdata_player_season_stats
already has 9,229 real rows, and player_insert_sql's ON CONFLICT DO
NOTHING means a plain re-run would just skip every existing row rather
than fix them. This pulls only the 'standard' stat type (the one
Gls/PKatt live in) for each season and UPDATEs just those two columns
by (player_name, team, season_id) -- the same key the rows are already
stored under -- instead of re-pulling and re-inserting everything.
"""

import psycopg2
import pandas as pd
import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASONS = [f"{y}-{str(y + 1)[-2:]}" for y in range(2010, 2026)]


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def season_to_id(season_str):
    return int(season_str.split("-")[0])


def flatten_columns(df):
    df.columns = ["_".join([str(x) for x in col if x]) if isinstance(col, tuple) else col
                   for col in df.columns]
    return df


def main():
    conn = get_connection()
    total_updated = 0

    update_sql = """
        UPDATE eredivisie_soccerdata_player_season_stats
        SET goals = %s, penalty_attempts = %s
        WHERE player_name = %s AND team = %s AND season_id = %s
    """

    with conn.cursor() as cur:
        for season in SEASONS:
            season_id = season_to_id(season)
            print(f"Fetching {season}...")
            try:
                fbref = sd.FBref(LEAGUE, season)
                standard = flatten_columns(fbref.read_player_season_stats(stat_type="standard"))
            except Exception as e:
                print(f"  FAILED for {season}: {type(e).__name__}: {e}")
                continue

            season_updated = 0
            for idx, row in standard.iterrows():
                team = idx[2]
                player = idx[3]

                goals = row.get("Performance_Gls")
                pk_att = row.get("Performance_PKatt")
                goals = None if pd.isna(goals) else goals
                pk_att = None if pd.isna(pk_att) else pk_att

                cur.execute(update_sql, (goals, pk_att, player, team, season_id))
                season_updated += cur.rowcount

            conn.commit()
            total_updated += season_updated
            print(f"  Updated {season_updated} rows")

    conn.close()
    print(f"\nTotal rows updated: {total_updated}")
    print("Verify with:")
    print("  SELECT COUNT(*) FROM eredivisie_soccerdata_player_season_stats WHERE goals IS NOT NULL;")
    print("  SELECT COUNT(*) FROM eredivisie_soccerdata_player_season_stats WHERE penalty_attempts IS NOT NULL;")


if __name__ == "__main__":
    main()
