"""
Quick coverage check: for each season 2010-11 through 2019-20, checks
whether WhoScored has usable event data (a 'type' column, non-empty) for
the first 10 matches in the schedule. Cheap early signal of which older
seasons are likely to have real data gaps (like the confirmed 2010-11
game_id=409048 case) before committing to a full ~300-match batch run
for a given season.

NOT a full audit -- just the first 10 matches per season, to get a quick
per-season "mostly fine" vs "mostly missing" read.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASONS = [f"{y}-{str(y + 1)[-2:]}" for y in range(2010, 2020)]  # 2010-11 through 2019-20
MATCHES_TO_CHECK = 10


def has_usable_events(events):
    return events is not None and len(events) > 0 and "type" in events.columns


def main():
    results = {}

    for season in SEASONS:
        print(f"\n{'=' * 60}\n{season}\n{'=' * 60}")
        ws = sd.WhoScored(LEAGUE, season)

        try:
            schedule = ws.read_schedule(force_cache=True)
        except Exception as e:
            print(f"  FAILED to fetch schedule: {type(e).__name__}: {e}")
            results[season] = "schedule_failed"
            continue

        match_ids = schedule["game_id"].head(MATCHES_TO_CHECK).tolist()
        usable = 0
        unusable_ids = []

        for match_id in match_ids:
            try:
                events = ws.read_events(match_id=match_id, force_cache=True)
                if has_usable_events(events):
                    usable += 1
                else:
                    unusable_ids.append(match_id)
            except Exception as e:
                print(f"  match_id={match_id}: ERROR -- {type(e).__name__}: {e}")
                unusable_ids.append(match_id)

        print(f"  {usable}/{len(match_ids)} of the first {MATCHES_TO_CHECK} matches "
              f"have usable event data.")
        if unusable_ids:
            print(f"  Matches with no usable data: {unusable_ids}")

        results[season] = f"{usable}/{len(match_ids)}"

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    for season, result in results.items():
        print(f"  {season}: {result}")


if __name__ == "__main__":
    main()
