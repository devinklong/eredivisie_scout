"""
Checks whether SavedShot events carry a qualifier distinguishing a
genuine goalkeeper save from a last-man/outfield block -- needed to
build an on-target definition that EXCLUDES blocked shots, per
project decision (2026-09-14): Opta's own published definition
includes last-man blocks as "on target", but this project wants a
narrower definition excluding them.

Looking specifically for a "Def block" qualifier (confirmed to exist
in Opta's broader qualifier set via web search earlier tonight:
id=94, "Defender blocks an opposition shot") -- checking whether it
actually appears on real SavedShot events in this project's own data,
not assumed.
"""

import soccerdata as sd

from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2019-20"
MATCH_ID = 1377320  # Vitesse-Ajax, already fetched/cached tonight


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

    saved_shots = events[events["type"] == "SavedShot"]
    print(f"Found {len(saved_shots)} SavedShot events in this match.\n")

    for idx, row in saved_shots.iterrows():
        print(f"Player: {row.get('player', '?')}, minute: {row.get('minute', '?')}")
        qualifiers = row.get("qualifiers")
        print(f"  Raw qualifiers: {qualifiers}")
        print()


if __name__ == "__main__":
    main()
