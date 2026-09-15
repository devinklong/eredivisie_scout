"""
Diagnostic: checks soccerdata's RAW output for Standard_Sh (shots) on a
known-affected player, BEFORE any of this project's own processing
(flatten_columns, the g() null-handling helper, etc.) touches it. This
tells us definitively whether the 0-instead-of-NULL bug originates
upstream in soccerdata/pandas' own HTML parsing, or somewhere in this
project's loading code -- don't guess, check.

Uses Hakim Ziyech, Ajax, 2017 (2017-18 season) as the known-affected
test case -- confirmed via master_player_season_stats (2026-09-14):
fbref_shots=0, fbref_shots_on_target=46, a real, prolific attacking
player who cannot genuinely have taken zero shots.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2017-18"


def main():
    fbref = sd.FBref(LEAGUE, SEASON)
    shooting = fbref.read_player_season_stats(stat_type="shooting")

    print("Raw shooting DataFrame dtypes:")
    print(shooting.dtypes)
    print()

    # Find Ziyech's row directly -- multi-index is (league, season, team, player)
    ziyech_rows = shooting[shooting.index.get_level_values("player") == "Hakim Ziyech"]
    print(f"Found {len(ziyech_rows)} row(s) for Hakim Ziyech:")
    print(ziyech_rows)
    print()

    if len(ziyech_rows) > 0:
        row = ziyech_rows.iloc[0]
        # Standard_Sh may appear as a tuple-column ('Standard', 'Sh') before
        # flattening -- try both forms to find it regardless of shape.
        for col in shooting.columns:
            col_str = "_".join([str(x) for x in col if x]) if isinstance(col, tuple) else col
            if col_str == "Standard_Sh" or (isinstance(col, tuple) and col[-1] == "Sh"):
                raw_value = row[col]
                print(f"Raw Standard_Sh value: {raw_value!r} (type: {type(raw_value).__name__})")
                print(f"pd.isna() result: {__import__('pandas').isna(raw_value)}")


if __name__ == "__main__":
    main()
