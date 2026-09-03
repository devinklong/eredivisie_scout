"""
Derives a final-third/penalty-area entry stat from WhoScored raw event
data -- the SCA/GCA proxy for v1 (per README's v1.0 map and
docs/whoscored_qualifier_taxonomy.md's scoping notes: true SCA/GCA
chain-attribution is out of scope for v1; this is a deliberate, coarser
substitute).

Scope for today: PASSES only. Carries are NOT included -- per
docs/stat_source_tracker.md, carries require soccerdata's SPADL output
format (output_fmt="spadl"), which hasn't been built yet (see
v1_roadmap.md). This script only counts completed passes whose end
location lands in the opponent's final third or penalty area --
narrower than FBref's original carries+passes combined definition, but
consistent with the "don't guess, flag what's missing" approach used in
the other derive_*.py scripts.

Zone boundaries reused as-is from derive_possession_stats.py /
derive_defense_stats.py for consistency across scripts.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07

MID_THIRD_MAX_X = 66.6  # anything beyond this, on the end coordinate, is the final third
PEN_AREA_DEPTH_X = 17.0
PEN_AREA_MIN_Y = 21.1
PEN_AREA_MAX_Y = 78.9

# Same pass-attempt scope as derive_passing_stats.py, but only completed
# 'Pass' events count as a genuine "entry" -- a blocked or offside pass
# never actually reached the final third/box, regardless of where it
# was aimed.


def is_final_third_entry(end_x):
    return end_x is not None and end_x > MID_THIRD_MAX_X


def is_penalty_area_entry(end_x, end_y):
    if end_x is None or end_y is None:
        return False
    return end_x >= (100 - PEN_AREA_DEPTH_X) and PEN_AREA_MIN_Y <= end_y <= PEN_AREA_MAX_Y


def derive_finalthird_stats(events):
    completed_passes = events[
        (events["type"] == "Pass") & (events["outcome_type"] == "Successful")
    ].copy()
    print(f"Total completed Pass events found: {len(completed_passes)}")

    completed_passes["is_final_third_entry"] = completed_passes["end_x"].apply(is_final_third_entry)
    completed_passes["is_pen_area_entry"] = completed_passes.apply(
        lambda row: is_penalty_area_entry(row["end_x"], row["end_y"]), axis=1
    )

    grouped = completed_passes.groupby(["player", "team"]).agg(
        final_third_entries=("is_final_third_entry", "sum"),
        pen_area_entries=("is_pen_area_entry", "sum"),
    ).reset_index()
    return grouped.sort_values("final_third_entries", ascending=False)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID)

    print("\n--- Final-third / penalty-area entries via completed passes (top 10) ---")
    print(derive_finalthird_stats(events).head(10))
    print("\nNOTE: passes only -- carries not included, see docstring.")


if __name__ == "__main__":
    main()
