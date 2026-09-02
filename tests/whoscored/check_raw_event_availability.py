"""
Diagnostic: checks whether WhoScored actually has real event data for
matches flagged as "unusable" by check_early_season_event_coverage.py,
using output_fmt="raw" -- which returns WhoScored's original JSON
directly, skipping soccerdata's own DataFrame-formatting step (the
'.astype("Int64")' casting that's throwing
"TypeError: cannot safely cast non-equivalent object to int64").

If raw data comes back non-empty, WhoScored genuinely has the events --
the earlier coverage check's 0/10 results were a soccerdata parsing bug
for older seasons, not a real data gap, and worth fixing rather than
scoping the project's historical range around it.

If raw data is also empty/None, that confirms a genuine WhoScored-side
gap for that match.

Checks a few specific match_ids spanning the flagged seasons.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"

# One flagged match_id per season, spanning the range that showed 0/10
# or 1/10 in the coverage check.
CHECKS = [
    ("2010-11", 409048),
    ("2015-16", 956891),
    ("2017-18", 1189035),
    ("2018-19", 1283333),
    ("2019-20", 1377319),
]


def main():
    for season, match_id in CHECKS:
        print(f"\n{'=' * 60}\n{season} -- match_id={match_id}\n{'=' * 60}")
        ws = sd.WhoScored(LEAGUE, season)

        try:
            raw = ws.read_events(match_id=match_id, force_cache=True, output_fmt="raw")
        except Exception as e:
            print(f"  RAW FETCH FAILED: {type(e).__name__}: {e}")
            continue

        if raw is None or match_id not in raw:
            print(f"  No raw data returned for this match_id.")
            continue

        events_list = raw[match_id]
        print(f"  Raw events returned: {len(events_list)}")

        if len(events_list) > 0:
            sample = events_list[0]
            print(f"  Sample event keys: {list(sample.keys())}")
            print(f"  Sample event_id value: {sample.get('id')!r} "
                  f"(type: {type(sample.get('id')).__name__})")
            print(f"  Sample relatedEventId value: {sample.get('relatedEventId')!r} "
                  f"(type: {type(sample.get('relatedEventId')).__name__})")


if __name__ == "__main__":
    main()
