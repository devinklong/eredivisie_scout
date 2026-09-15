"""
Validates a candidate shots-derivation approach BEFORE building a real
derive_shots_stats.py around it: total shots = MissedShots + SavedShot
+ Goal (WhoScored event types); shots on target = SavedShot + Goal.

Cross-checks against FBref's OWN shooting numbers for a KNOWN-GOOD
season (one NOT affected by the confirmed 2016-17/2017-18 shots=0 gap)
for the same real player -- if the WhoScored-derived count is close to
FBref's real, correct number, that validates the definition is right
before using it to fill the actual gap. Same test match convention as
other derive_*.py scripts.
"""

import soccerdata as sd
from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2019-20"  # a season confirmed NOT affected by the shots=0 gap
MATCH_ID = 1377320


def get_events_with_fallback(ws, league, season, match_id):
    """Same fallback pattern already established in
    scrape_all_whoscored_matches.py -- some matches hit a confirmed
    soccerdata casting bug on the standard path regardless of season,
    not just the originally-documented 2013-14 through 2018-19 range."""
    try:
        return ws.read_events(match_id=match_id, force_cache=True)
    except TypeError as e:
        if "cannot safely cast non-equivalent object to int64" not in str(e):
            raise
        print("  (hit the known casting bug -- using the raw fallback parser)")
        return get_events_raw_fallback(league, season, match_id)


def check_event_types(events):
    print("Event types in this match:", sorted(events["type"].unique()))
    for t in ["MissedShots", "SavedShot", "Goal", "ShotOnPost"]:
        count = (events["type"] == t).sum()
        print(f"  {t}: {count} events")


def derive_shots(events):
    # Confirmed via Opta's own event definitions (2026-09-14, not a
    # guess): ShotOnPost is a genuine shot attempt -- counts toward
    # total shots, but NOT shots on target (Opta's "on target"
    # definition specifically means an attempt that would have gone in
    # but for a save or a last-man block -- a post is neither).
    # Smother is a GOALKEEPER defensive action (claiming the ball at an
    # attacker's feet, functionally similar to a tackle) -- confirmed
    # NOT a shot event at all, correctly excluded here.
    shot_types = ["MissedShots", "SavedShot", "Goal", "ShotOnPost"]
    on_target_types = ["SavedShot", "Goal"]

    shots = events[events["type"].isin(shot_types)].copy()
    on_target = events[events["type"].isin(on_target_types)]

    shots_by_player = shots.groupby(["player", "team"]).size().rename("shots")
    on_target_by_player = on_target.groupby(["player", "team"]).size().rename("shots_on_target")

    combined = shots_by_player.to_frame().join(on_target_by_player, how="outer").fillna(0)
    return combined.sort_values("shots", ascending=False)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    schedule = ws.read_schedule(force_cache=True)
    print(f"Found {len(schedule)} matches for {SEASON}. Pick a real match_id and "
          f"set MATCH_ID at the top of this file, then re-run.")
    print(schedule[["game_id", "home_team", "away_team", "date"]].head(20))


if __name__ == "__main__":
    if MATCH_ID is None:
        main()
    else:
        ws = sd.WhoScored(LEAGUE, SEASON)
        events = get_events_with_fallback(ws, LEAGUE, SEASON, MATCH_ID)
        check_event_types(events)
        print("\n--- Derived shots (top 10) ---")
        print(derive_shots(events).head(10))
        print("\nCross-check these numbers against the SAME real players' FBref "
              "shooting stats for this match/season (a season NOT affected by "
              "the shots=0 gap) before trusting this definition.")
