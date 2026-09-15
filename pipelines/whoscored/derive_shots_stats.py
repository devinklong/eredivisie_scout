"""
Derives shot stats (shots, shots_on_target, shots_on_target_pct) from
WhoScored raw event data.

Shot definition:
  - shots = MissedShots + SavedShot + Goal + ShotOnPost (confirmed via
    check_shots_derivation.py against real FBref season totals --
    near-exact match, 5/8 exact, 3/8 off by 1, attributable to a small
    number of failed/fallback matches, not a definitional error).
  - shots_on_target = Goal + (SavedShot events that reached the goal
    frame -- i.e. carry real GoalMouthY/GoalMouthZ qualifier
    coordinates). CONFIRMED via check_savedshot_qualifiers.py
    (2026-09-14) against real match data: SavedShot events split
    cleanly into two groups -- those with an explicit 'Blocked'
    qualifier and NO GoalMouth coordinates (consistent across two
    independent signals in 16 of 17 real sampled events), vs. those
    with real GoalMouth coordinates and no 'Blocked' tag.

    This is a DELIBERATE, project-specific choice to use the narrower
    "reached the keeper or scored" convention, NOT Opta's own broader
    published definition (which explicitly includes last-man blocks
    as "on target") -- decided (2026-09-14) because the narrower
    convention matches what FBref and most public sources use,
    keeping this project's shots_on_target comparable to the ecosystem
    a club would actually reference when forming its own valuation of
    a player, and because it's the more precise signal for what the
    model is trying to measure. See docs/v1_roadmap.md for the full
    reasoning.

Includes player_id in the groupby, matching the convention already
applied to every other derive_*.py file in this project.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07

SHOT_TYPES = ["MissedShots", "SavedShot", "Goal", "ShotOnPost"]


def _reached_goal_frame(qualifiers):
    """True if this event's qualifiers include real GoalMouthY/
    GoalMouthZ coordinates -- meaning the shot's trajectory was
    tracked all the way to the goal frame, i.e. it wasn't blocked
    before then. Confirmed via check_savedshot_qualifiers.py: this
    agrees with the explicit 'Blocked' qualifier tag in 16 of 17 real
    sampled events, and resolves the one ambiguous case conservatively
    (no coordinates = not counted as on target)."""
    if not isinstance(qualifiers, list):
        return False
    for q in qualifiers:
        display_name = q.get("type", {}).get("displayName")
        if display_name in ("GoalMouthY", "GoalMouthZ"):
            return True
    return False


def derive_shot_stats(events, verbose=True):
    """Shots attempted/on-target, from the four real WhoScored shot
    event types directly, with on-target using the narrower
    reached-the-goal-frame-or-scored definition (see module docstring)."""
    shots = events[events["type"].isin(SHOT_TYPES)].copy()
    if verbose:
        print(f"Total shot events found: {len(shots)}")

    shots["is_on_target"] = (
        (shots["type"] == "Goal")
        | ((shots["type"] == "SavedShot") & shots["qualifiers"].apply(_reached_goal_frame))
    )

    grouped = shots.groupby(["player", "team", "player_id"]).agg(
        shots=("type", "count"),
        shots_on_target=("is_on_target", "sum"),
    ).reset_index()
    grouped["shots_on_target_pct"] = (
        (grouped["shots_on_target"] / grouped["shots"]) * 100
    ).round(1)
    return grouped.sort_values("shots", ascending=False)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID, force_cache=True)

    print("\n--- Shots (top 10) ---")
    shot_stats = derive_shot_stats(events)
    print(shot_stats.head(10))


if __name__ == "__main__":
    main()
