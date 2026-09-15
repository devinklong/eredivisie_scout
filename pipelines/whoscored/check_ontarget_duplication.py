"""
Isolates the on-target overcounting bug by inspecting RAW SavedShot/
Goal event rows directly for one real player across real matches --
not aggregated counts, the actual rows -- to check for duplication.

Built (2026-09-14) after season-level validation confirmed total shots
is correct (near-exact match against FBref) but shots_on_target is
systematically inflated by roughly 15-21 shots per player, WAY too
large and consistent to be random -- a real double-counting bug
specific to on-target counting.
"""

import soccerdata as sd

from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2019-20"
TEST_PLAYER = "Bryan Linssen"
TEST_TEAM = "Vitesse"


def get_events_with_fallback(ws, league, season, match_id):
    try:
        return ws.read_events(match_id=match_id, force_cache=True)
    except TypeError as e:
        if "cannot safely cast non-equivalent object to int64" not in str(e):
            raise
        return get_events_raw_fallback(league, season, match_id)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    schedule = ws.read_schedule(force_cache=True)
    vitesse_matches = schedule[
        (schedule["home_team"] == TEST_TEAM) | (schedule["away_team"] == TEST_TEAM)
    ]["game_id"].tolist()

    print(f"Checking {len(vitesse_matches)} Vitesse matches for raw "
          f"SavedShot/Goal rows belonging to {TEST_PLAYER}...\n")

    for match_id in vitesse_matches[:5]:  # first 5 matches only, for a manageable look
        events = get_events_with_fallback(ws, LEAGUE, SEASON, match_id)
        if events is None or len(events) == 0 or "player" not in events.columns:
            continue

        player_shots = events[
            (events["player"] == TEST_PLAYER) & (events["type"].isin(["SavedShot", "Goal"]))
        ]
        if len(player_shots) > 0:
            print(f"--- Match {match_id} ---")
            cols_to_show = [c for c in ["id", "event_id", "minute", "second", "type",
                                          "outcome_type", "related_event_id", "team"]
                             if c in player_shots.columns]
            print(player_shots[cols_to_show].to_string())
            print()


if __name__ == "__main__":
    main()
