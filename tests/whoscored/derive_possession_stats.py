"""
Derives FBref-style possession stats (touches by zone, take-ons,
dispossessed) from WhoScored raw event data. Same match/pattern as
derive_passing_stats.py (game_id=1982244, Cambuur-Excelsior).

Scope for today: touches by zone, take-ons, dispossessed -- the parts
that map cleanly onto first-class event columns or a simple type filter.
Deliberately NOT attempted here (flagged, not guessed at):

- carries / carries_distance / carries_progressive_distance /
  carries_into_final_third / carries_into_penalty_area -- per
  docs/stat_source_tracker.md, this needs soccerdata's SPADL output
  format (output_fmt="spadl"), not the default event format used here.
  Separate script, separate day.
- miscontrols -- no confirmed WhoScored type/qualifier identified yet
  for this. Do not guess; needs its own lookup before building.
- passes_received -- possibly derivable from a pass event's
  related_player_id, but not confirmed. Flagged, not built.

Zone boundaries used below (thirds + penalty area) are the commonly-cited
Opta 0-100 normalized-pitch convention, NOT independently confirmed
against WhoScored's own docs -- treat as a reasonable default, worth
sanity-checking against a few known real touches (e.g. a goalkeeper's
touches should fall almost entirely in the defensive third/penalty area)
before trusting this for real feature-building.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07

# Opta-style normalized pitch: x/y both run 0-100.
# Thirds are split evenly along x (attacking direction).
DEF_THIRD_MAX_X = 33.3
MID_THIRD_MAX_X = 66.6

# Penalty area approx bounds -- commonly cited Opta convention, unverified
# against WhoScored's own docs. Pitch is symmetric: the defensive box sits
# near x=0 (own goal), the attacking box near x=100 (opponent's goal).
PEN_AREA_DEPTH_X = 17.0  # how far the box extends inward from each goal line
PEN_AREA_MIN_Y = 21.1
PEN_AREA_MAX_Y = 78.9


def zone_for_touch(x):
    if x <= DEF_THIRD_MAX_X:
        return "def_3rd"
    elif x <= MID_THIRD_MAX_X:
        return "mid_3rd"
    else:
        return "att_3rd"


def is_in_def_penalty_area(x, y):
    return x <= PEN_AREA_DEPTH_X and PEN_AREA_MIN_Y <= y <= PEN_AREA_MAX_Y


def is_in_att_penalty_area(x, y):
    return x >= (100 - PEN_AREA_DEPTH_X) and PEN_AREA_MIN_Y <= y <= PEN_AREA_MAX_Y


def derive_touch_stats(events):
    """Touches, by zone.

    SANITY CHECK (2026-08-28, game_id=1982244): this originally only
    computed one penalty-area zone (x <= 17) and mislabeled it
    touches_att_pen_area. Running it against real data caught the bug --
    the goalkeeper (Stijn van Gassel) had by far the most touches in that
    zone (33), which only makes sense for a DEFENSIVE box, not an
    attacking one. Fixed by splitting into both def and att penalty
    areas, computed from opposite ends of the pitch (x<=17 vs x>=83).
    Worth re-running this same keeper-touch check after any future
    change to the zone boundaries, as a cheap correctness test."""
    touches = events[events["is_touch"] == True].copy()
    print(f"Total touch events found: {len(touches)}")

    touches["zone"] = touches["x"].apply(zone_for_touch)
    touches["in_def_pen_area"] = touches.apply(
        lambda row: is_in_def_penalty_area(row["x"], row["y"]), axis=1
    )
    touches["in_att_pen_area"] = touches.apply(
        lambda row: is_in_att_penalty_area(row["x"], row["y"]), axis=1
    )

    grouped = touches.groupby("player").agg(
        touches=("x", "count"),
        touches_def_3rd=("zone", lambda z: (z == "def_3rd").sum()),
        touches_mid_3rd=("zone", lambda z: (z == "mid_3rd").sum()),
        touches_att_3rd=("zone", lambda z: (z == "att_3rd").sum()),
        touches_def_pen_area=("in_def_pen_area", "sum"),
        touches_att_pen_area=("in_att_pen_area", "sum"),
    )
    return grouped.sort_values("touches", ascending=False)


def derive_take_on_stats(events):
    """Take-ons attempted/won, from the TakeOn event type directly."""
    take_ons = events[events["type"] == "TakeOn"].copy()
    print(f"Total TakeOn events found: {len(take_ons)}")

    take_ons["is_won"] = take_ons["outcome_type"] == "Successful"

    grouped = take_ons.groupby("player").agg(
        take_ons=("type", "count"),
        take_ons_won=("is_won", "sum"),
    )
    grouped["take_ons_won_pct"] = (
        (grouped["take_ons_won"] / grouped["take_ons"]) * 100
    ).round(1)
    return grouped.sort_values("take_ons", ascending=False)


def derive_dispossessed_stats(events):
    """Times a player lost the ball to an opponent's challenge."""
    dispossessed = events[events["type"] == "Dispossessed"]
    print(f"Total Dispossessed events found: {len(dispossessed)}")
    return dispossessed.groupby("player").size().rename("dispossessed").sort_values(ascending=False)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID)

    print("\n--- Touches by zone (top 10) ---")
    touch_stats = derive_touch_stats(events)
    print(touch_stats.head(10))

    print("\n--- Take-ons (top 10) ---")
    take_on_stats = derive_take_on_stats(events)
    print(take_on_stats.head(10))

    print("\n--- Dispossessed (top 10) ---")
    dispossessed_stats = derive_dispossessed_stats(events)
    print(dispossessed_stats.head(10))


if __name__ == "__main__":
    main()
