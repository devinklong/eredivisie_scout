"""
Checks whether Foul events self-report win/loss directly via
outcome_type, the same way Aerial was confirmed to (see
check_aerial_outcome.py, whoscored_qualifier_taxonomy.md's
Cross-event relationships table -- "likely carries outcome directly,
not yet independently verified").

Uses the same match/fallback pattern as the other one-off qualifier
checks in this project.
"""

import soccerdata as sd

from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07 -- same match used for the rest of the qualifier taxonomy


def get_events_with_fallback(ws, league, season, match_id):
    try:
        return ws.read_events(match_id=match_id, force_cache=True)
    except TypeError as e:
        if "cannot safely cast non-equivalent object to int64" not in str(e):
            raise
        return get_events_raw_fallback(league, season, match_id)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = get_events_with_fallback(ws, LEAGUE, SEASON, MATCH_ID)

    fouls = events[events["type"] == "Foul"]
    print(f"Found {len(fouls)} Foul events in this match.\n")

    print("--- outcome_type value counts ---")
    print(fouls["outcome_type"].value_counts(dropna=False))

    print("\n--- Sample rows ---")
    for idx, row in fouls.head(10).iterrows():
        print(f"Player: {row.get('player', '?')}, team: {row.get('team', '?')}, "
              f"minute: {row.get('minute', '?')}, outcome_type: {row.get('outcome_type', '?')}")

    print("\nIf outcome_type splits cleanly (e.g. ~50/50 Successful/Unsuccessful, "
          "matching the Aerial signature), Foul self-reports win/loss directly -- "
          "no cross-referencing needed, same as Aerial.")
    print("If it's mostly NULL or all one value, this needs the same "
          "cross-referencing treatment as Challenge/TakeOn instead.")


if __name__ == "__main__":
    main()
