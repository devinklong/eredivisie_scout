"""
Derives FBref-style defensive stats (tackles, interceptions, clearances,
challenges, errors -- by zone where relevant) from WhoScored raw event
data. Same match/pattern as derive_passing_stats.py and
derive_possession_stats.py (game_id=1982244, Cambuur-Excelsior).

Scope for today: tackles, interceptions, clearances, challenges, errors.
Deliberately NOT attempted here (flagged, not guessed at):

- blocks / blocked_shots / blocked_passes -- attribution is unclear.
  A BlockedPass event's 'player' field is very likely the attacking
  player whose pass got blocked, NOT the defender who blocked it --
  unconfirmed whether the blocking player is findable via
  related_player_id or a qualifier. Needs its own check before building,
  same as miscontrols/passes_received were flagged (not guessed at) in
  derive_possession_stats.py.
- tackles_interceptions (FBref's combined column) -- trivial to add
  once tackles and interceptions are both confirmed correct
  individually; deferred until then.

VALIDATION PATTERN (per patch_list.md's possession fix): a goalkeeper
sanity check caught a real zone-labeling bug in the possession script.
The equivalent check here: a center-back's tackles/interceptions should
cluster heavily in def_3rd. Worth eyeballing the real output against
whichever players you know play CB in this match before trusting the
zone logic.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07

# Same thirds convention as derive_possession_stats.py -- reused as-is,
# not redefined, so both scripts stay consistent with each other.
DEF_THIRD_MAX_X = 33.3
MID_THIRD_MAX_X = 66.6


def zone_for_event(x):
    if x <= DEF_THIRD_MAX_X:
        return "def_3rd"
    elif x <= MID_THIRD_MAX_X:
        return "mid_3rd"
    else:
        return "att_3rd"


def derive_tackle_stats(events):
    """Tackles attempted/won, by zone."""
    tackles = events[events["type"] == "Tackle"].copy()
    print(f"Total Tackle events found: {len(tackles)}")

    tackles["zone"] = tackles["x"].apply(zone_for_event)
    tackles["is_won"] = tackles["outcome_type"] == "Successful"

    grouped = tackles.groupby("player").agg(
        tackles=("type", "count"),
        tackles_won=("is_won", "sum"),
        tackles_def_3rd=("zone", lambda z: (z == "def_3rd").sum()),
        tackles_mid_3rd=("zone", lambda z: (z == "mid_3rd").sum()),
        tackles_att_3rd=("zone", lambda z: (z == "att_3rd").sum()),
    )
    return grouped.sort_values("tackles", ascending=False)


def derive_interception_stats(events):
    """Interceptions, by zone."""
    interceptions = events[events["type"] == "Interception"].copy()
    print(f"Total Interception events found: {len(interceptions)}")

    interceptions["zone"] = interceptions["x"].apply(zone_for_event)

    grouped = interceptions.groupby("player").agg(
        interceptions=("type", "count"),
        interceptions_def_3rd=("zone", lambda z: (z == "def_3rd").sum()),
        interceptions_mid_3rd=("zone", lambda z: (z == "mid_3rd").sum()),
        interceptions_att_3rd=("zone", lambda z: (z == "att_3rd").sum()),
    )
    return grouped.sort_values("interceptions", ascending=False)


def derive_clearance_stats(events):
    """Clearances -- simple count, no zone breakdown (FBref doesn't
    zone-split clearances either, per stat_source_tracker.md)."""
    clearances = events[events["type"] == "Clearance"]
    print(f"Total Clearance events found: {len(clearances)}")
    return clearances.groupby("player").size().rename("clearances").sort_values(ascending=False)


def derive_challenge_stats(events):
    """'Challenge' events -- confirmed via Opta's own event definitions
    this is NOT a win/loss stat. A Challenge is only ever logged for the
    defender who got dribbled past; there is no 'Challenge won' outcome
    in Opta's data model at all. The corresponding 'win' for the
    attacking side is a separate event type entirely -- TakeOn (see
    derive_possession_stats.py) -- attributed to the attacker, not the
    defender. The two are two different players' events describing the
    same real-world moment, not one event with an outcome flag.

    So this returns a single count: dribbled_past. If you want the
    matching 'win' side for a specific defender, cross-reference against
    TakeOn events (from derive_possession_stats.py) where the opposing
    attacker's take_ons_won count went up in the same passage of play --
    not built here, noted as the relationship to use if this is ever
    joined against possession data. See
    docs/whoscored_qualifier_taxonomy.md's cross-event relationships
    table for the same pattern applied to Aerial and Tackle/Dispossessed."""
    challenges = events[events["type"] == "Challenge"]
    print(f"Total Challenge events found: {len(challenges)}")
    print("NOTE: Challenge is a losing-side-only event (see docstring) -- "
          "no win/loss split is computed here.")

    return challenges.groupby("player").size().rename("dribbled_past").sort_values(ascending=False)


def derive_error_stats(events):
    """Errors -- simple count."""
    errors = events[events["type"] == "Error"]
    print(f"Total Error events found: {len(errors)}")
    return errors.groupby("player").size().rename("errors").sort_values(ascending=False)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID)

    print("\n--- Tackles by zone (top 10) ---")
    print(derive_tackle_stats(events).head(10))

    print("\n--- Interceptions by zone (top 10) ---")
    print(derive_interception_stats(events).head(10))

    print("\n--- Clearances (top 10) ---")
    print(derive_clearance_stats(events).head(10))

    print("\n--- Dribbled past (formerly 'challenges' -- see docstring) (top 10) ---")
    print(derive_challenge_stats(events).head(10))

    print("\n--- Errors (all) ---")
    print(derive_error_stats(events))


if __name__ == "__main__":
    main()
