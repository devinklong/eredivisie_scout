"""
Retests whether force_cache=True fixes the calendar-refetch inefficiency
confirmed in patch_list.md (2026-08-31). Root cause: read_events() calls
read_schedule() internally on every call, and read_schedule()'s caching
logic (no_cache = current_season and not force_cache) deliberately skips
the local cache for an in-progress season unless force_cache=True is
passed. Same test as test_whoscored_instance_reuse.py, but now with
force_cache=True on every call -- if the fix works, calls 2 and 3 should
be dramatically faster than the first (129-229s each in the prior test).
"""

import time

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
NUM_MATCHES_TO_TEST = 3


def main():
    print("Creating ONE WhoScored instance (reused for every call below)...")
    ws = sd.WhoScored(LEAGUE, SEASON)

    print("\nFetching schedule (force_cache=True) to get real match_ids...")
    t0 = time.time()
    schedule = ws.read_schedule(force_cache=True)
    print(f"  read_schedule(force_cache=True) took {time.time() - t0:.1f}s")

    match_ids = schedule["game_id"].head(NUM_MATCHES_TO_TEST).tolist()
    print(f"\nTesting read_events(force_cache=True) on {len(match_ids)} matches: {match_ids}")

    for i, match_id in enumerate(match_ids, start=1):
        print(f"\n--- Call {i}/{len(match_ids)}: match_id={match_id} ---")
        t0 = time.time()
        try:
            events = ws.read_events(match_id=match_id, force_cache=True)
            elapsed = time.time() - t0
            print(f"  SUCCESS -- {len(events)} events, took {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  FAILED after {elapsed:.1f}s -- {type(e).__name__}: {e}")

    print("\n" + "=" * 60)
    print("Interpretation:")
    print("Compare these times against the prior run (no force_cache):")
    print("  read_schedule: 137.0s  |  events: 129.0s, 147.9s, 228.6s")
    print("If these calls are dramatically faster, force_cache=True is the")
    print("real fix -- safe to build the season-scale batch script with it.")
    print("Remember the tradeoff: force_cache=True won't pick up newly-added")
    print("fixtures/results -- fine for historical batch work, not for live data.")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
