"""
Decisive check for the on-target overcounting mystery: counts every
raw SavedShot/Goal row for one player across their ENTIRE season,
with NO groupby, NO aggregation pipeline -- just a plain running total.
If this matches the ~59 figure from validate_shots_season.py, the
overcount is real, raw WhoScored data (a genuine definitional
difference from FBref, not a code bug). If it's closer to the real
FBref figure (~39), the bug is somewhere in the aggregation step,
just not visible from reading the code.
"""

import soccerdata as sd

from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2019-20"
TEST_PLAYER = "Bryan Linssen"
TEST_TEAM = "Vitesse"


def get_events_with_fallback(ws, league, season, match_id):
    try:
        return ws.read_events(match_id=match_id, force_cache=True), False
    except TypeError as e:
        if "cannot safely cast non-equivalent object to int64" not in str(e):
            raise
        return get_events_raw_fallback(league, season, match_id), True


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    schedule = ws.read_schedule(force_cache=True)
    vitesse_matches = schedule[
        (schedule["home_team"] == TEST_TEAM) | (schedule["away_team"] == TEST_TEAM)
    ]["game_id"].tolist()

    total_saved_shot = 0
    total_goal = 0
    per_match_log = []

    for match_id in vitesse_matches:
        events, used_fallback = get_events_with_fallback(ws, LEAGUE, SEASON, match_id)
        if events is None or len(events) == 0 or "player" not in events.columns:
            continue

        player_events = events[events["player"] == TEST_PLAYER]
        saved = (player_events["type"] == "SavedShot").sum()
        goal = (player_events["type"] == "Goal").sum()

        total_saved_shot += saved
        total_goal += goal
        per_match_log.append((match_id, used_fallback, saved, goal))

    print(f"{TEST_PLAYER} -- plain raw count across {len(vitesse_matches)} matches:")
    print(f"  Total SavedShot: {total_saved_shot}")
    print(f"  Total Goal: {total_goal}")
    print(f"  Combined (on-target definition): {total_saved_shot + total_goal}")
    print()
    print("Per-match breakdown (match_id, used_fallback, SavedShot, Goal):")
    for row in per_match_log:
        print(f"  {row}")


if __name__ == "__main__":
    main()
