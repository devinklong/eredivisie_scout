"""
One-off fix for the two confirmed FBref data-quality glitches found
2026-08-30 (see v1_roadmap.md item 7): Ricardo Ippel (Willem II, 2014-15)
and Bilal Bayazit (Vitesse, 2017-18) each have ONE real season split
across two erroneous FBref rows. Externally verified real identity for
each (Wikipedia, worldfootball.net, FBref's own current player pages):
  - Ippel: born 31 Aug 1990, NED, MF
  - Bayazit: born 8 Apr 1999, NED, GK

Fix: re-fetch both rows for each player, sum the additive counting
stats across the two rows, keep identity fields (nation/pos/age/born)
from whichever row matches the verified real-world facts, and UPDATE
the single existing row in eredivisie_player_season_stats with the
corrected combined values. Does NOT insert new rows -- the final count
stays 9,229, which is the correct total (these are 2 corrected rows,
not 2 missing ones).
"""

import pandas as pd
import psycopg2
import soccerdata as sd

LEAGUE = "NED-Eredivisie"


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def flatten_columns(df):
    df.columns = ["_".join([str(x) for x in col if x]) if isinstance(col, tuple) else col
                   for col in df.columns]
    return df


def sum_additive(val1, val2):
    """Sums two values, treating NA as 0 -- for genuine counting stats
    (MP, Min, Starts, Subs, etc.) where combining two partial/duplicate
    entries should produce the real season total."""
    v1 = 0 if pd.isna(val1) else val1
    v2 = 0 if pd.isna(val2) else val2
    return v1 + v2


def fix_player(season, team, player, correct_nation, correct_pos, correct_born):
    fbref = sd.FBref(LEAGUE, season)
    playing_time = flatten_columns(fbref.read_player_season_stats(stat_type="playing_time"))

    rows = playing_time[
        (playing_time.index.get_level_values("team") == team)
        & (playing_time.index.get_level_values("player") == player)
    ]

    if len(rows) != 2:
        print(f"  Expected 2 rows for {player}, found {len(rows)} -- skipping, check manually.")
        return None

    row1, row2 = rows.iloc[0], rows.iloc[1]

    # Additive counting stats -- sum across both rows.
    additive_cols = [
        "Playing Time_MP", "Playing Time_Min", "Starts_Starts", "Starts_Compl",
        "Subs_Subs", "Subs_unSub",
    ]
    merged = {}
    for col in additive_cols:
        if col in row1.index:
            merged[col] = sum_additive(row1.get(col), row2.get(col))

    # Recompute rate/derived stats from the merged totals rather than
    # averaging or picking one -- more correct than either source value.
    mp = merged.get("Playing Time_MP", 0)
    minutes = merged.get("Playing Time_Min", 0)
    merged["Playing Time_Mn/MP"] = round(minutes / mp, 1) if mp else None
    merged["Playing Time_90s"] = round(minutes / 90, 1) if minutes else 0

    print(f"  Merged additive stats for {player}: {merged}")
    return {
        "nation": correct_nation,
        "position": correct_pos,
        "born": correct_born,
        "matches_played": merged.get("Playing Time_MP"),
        "minutes": merged.get("Playing Time_Min"),
        "minutes_per_match": merged.get("Playing Time_Mn/MP"),
        "nineties": merged.get("Playing Time_90s"),
        "starts": merged.get("Starts_Starts"),
        "complete_matches": merged.get("Starts_Compl"),
        "substitute_appearances": merged.get("Subs_Subs"),
        "unused_sub": merged.get("Subs_unSub"),
    }


def to_native(value):
    """Converts numpy scalar types (int64, float64) to native Python
    int/float -- psycopg2 can't adapt numpy types directly."""
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def apply_fix(conn, player_name, team, season_id, fixed_values):
    native_values = {k: to_native(v) for k, v in fixed_values.items()}
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE eredivisie_player_season_stats
            SET nation = %(nation)s, position = %(position)s, born = %(born)s,
                matches_played = %(matches_played)s, minutes = %(minutes)s,
                minutes_per_match = %(minutes_per_match)s, nineties = %(nineties)s,
                starts = %(starts)s, complete_matches = %(complete_matches)s,
                substitute_appearances = %(substitute_appearances)s,
                unused_sub = %(unused_sub)s
            WHERE player_name = %(player_name)s AND team = %(team)s AND season_id = %(season_id)s
        """, {**native_values, "player_name": player_name, "team": team, "season_id": season_id})
        print(f"  Rows updated: {cur.rowcount}")
    conn.commit()


def main():
    conn = get_connection()

    print("Fixing Ricardo Ippel (Willem II, 2014-15)...")
    fixed = fix_player("2014-15", "Willem II", "Ricardo Ippel",
                        correct_nation="NED", correct_pos="MF", correct_born=1990)
    if fixed:
        apply_fix(conn, "Ricardo Ippel", "Willem II", 2014, fixed)

    print("\nFixing Bilal Bayazit (Vitesse, 2017-18)...")
    fixed = fix_player("2017-18", "Vitesse", "Bilal Bayazit",
                        correct_nation="NED", correct_pos="GK", correct_born=1999)
    if fixed:
        apply_fix(conn, "Bilal Bayazit", "Vitesse", 2017, fixed)

    conn.close()
    print("\nDone. Table row count should remain 9229 -- these were corrections, not additions.")


if __name__ == "__main__":
    main()
