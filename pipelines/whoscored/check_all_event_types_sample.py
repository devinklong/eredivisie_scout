"""
Checks ALL distinct event types across a real, broad sample of season
data -- not just one or two matches. Built (2026-09-14) after the
season-level shots validation showed implausibly high on-target
percentages (55-75%, vs. a realistic 35-45%) across nearly every
player, suggesting the "shots" denominator is missing a real off-
target shot type (a blocked shot in particular) that simply never
happened to occur in either of the two single matches checked so far.
Same lesson as several other investigations tonight -- a small sample
isn't proof of the full picture.
"""

import soccerdata as sd
from collections import Counter

from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2019-20"
SAMPLE_SIZE = 30  # matches to sample -- broad enough to surface a rare event type


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
    match_ids = schedule["game_id"].tolist()[:SAMPLE_SIZE]

    all_types = Counter()
    for i, match_id in enumerate(match_ids, start=1):
        try:
            events = get_events_with_fallback(ws, LEAGUE, SEASON, match_id)
            if events is not None and len(events) > 0 and "type" in events.columns:
                all_types.update(events["type"].value_counts().to_dict())
        except Exception as e:
            print(f"  match {match_id} FAILED: {type(e).__name__}: {e}")

    print(f"\nAll distinct event types across {len(match_ids)} matches, with counts:")
    for event_type, count in all_types.most_common():
        print(f"  {event_type}: {count}")

    print("\nLooking specifically for anything shot/block-related not already "
          "in derive_shots_stats.py's SHOT_TYPES (MissedShots, SavedShot, "
          "Goal, ShotOnPost).")


if __name__ == "__main__":
    main()
