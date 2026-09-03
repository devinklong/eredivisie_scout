"""
Derives FBref-style passing stats (passes_completed, passes, passes_pct)
from WhoScored raw event data.

Uses .isin() rather than a direct == 'Pass' match, since WhoScored's event
taxonomy splits some pass outcomes into their own separate type values
(e.g. 'BlockedPass', 'OffsidePass') rather than keeping everything under
a single 'Pass' type with an outcome flag. Confirmed via
events['type'].unique() on a real match (game_id=1982244):

['Start' 'Pass' 'Aerial' 'BallRecovery' 'Dispossessed' 'Tackle'
 'BallTouch' 'Clearance' 'CornerAwarded' 'MissedShots' 'Challenge'
 'TakeOn' 'Claim' 'BlockedPass' 'Interception' 'SavedShot' 'Save'
 'OffsideGiven' 'Foul' 'OffsidePass' 'OffsideProvoked' 'Error' 'Goal'
 'KeeperPickup' 'KeeperSweeper' 'End' 'SubstitutionOff' 'SubstitutionOn'
 'FormationChange' 'GoodSkill' 'FormationSet']

Only 'Pass', 'BlockedPass', and 'OffsidePass' are pass-attempt-relevant --
the rest are unrelated event types and are correctly excluded either way.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07

# All event types that represent a genuine pass attempt, successful or not.
PASS_ATTEMPT_TYPES = ["Pass", "BlockedPass", "OffsidePass"]


def derive_passing_stats(events):
    """Returns a per-player DataFrame with passes, passes_completed, and
    passes_pct, derived from raw WhoScored events."""
    pass_events = events[events["type"].isin(PASS_ATTEMPT_TYPES)].copy()

    print(f"Total pass-attempt events found: {len(pass_events)}")
    print(f"Breakdown by type:\n{pass_events['type'].value_counts()}\n")

    # A pass only counts as completed if it's specifically type == 'Pass'
    # AND outcome_type == 'Successful' -- a BlockedPass or OffsidePass is
    # never a completion, regardless of what outcome_type says.
    pass_events["is_completed"] = (
        (pass_events["type"] == "Pass")
        & (pass_events["outcome_type"] == "Successful")
    )

    grouped = pass_events.groupby(["player", "team"]).agg(
        passes=("type", "count"),
        passes_completed=("is_completed", "sum"),
    ).reset_index()
    grouped["passes_pct"] = (
        (grouped["passes_completed"] / grouped["passes"]) * 100
    ).round(1)

    return grouped.sort_values("passes", ascending=False)


def inspect_pass_qualifiers(events):
    """Diagnostic: checks what subtype info (crosses, throw-ins, corners,
    free kicks, etc.) lives inside the qualifiers field of real 'Pass'
    events, to confirm .isin() on type alone isn't silently missing a
    pass subtype that WhoScored tracks as its own separate type value."""
    pass_rows = events[events["type"] == "Pass"]
    print(f"Inspecting qualifiers on {len(pass_rows)} 'Pass' events...")

    all_qualifier_names = set()
    for qualifiers in pass_rows["qualifiers"].dropna():
        for q in qualifiers:
            display_name = q.get("type", {}).get("displayName")
            if display_name:
                all_qualifier_names.add(display_name)

    print(f"Distinct qualifier displayNames found on Pass events:")
    for name in sorted(all_qualifier_names):
        print(f"  {name}")
    print()


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID)

    print(f"All event types on this page: {sorted(events['type'].unique())}\n")

    inspect_pass_qualifiers(events)

    passing_stats = derive_passing_stats(events)
    print("Derived passing stats (top 10 by attempts):")
    print(passing_stats.head(10))


if __name__ == "__main__":
    main()
