"""
Test script: confirms whether NED-Eredivisie is now recognized by
soccerdata's WhoScored module (after adding the WhoScored mapping to
league_dict.json), then attempts a small, cheap pull (schedule) to
confirm real data comes back -- before attempting anything heavier
like read_events(), which is the one that actually matters for
shot-level xG-model data.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"


def main():
    print("Checking WhoScored's available leagues...")
    available = sd.WhoScored.available_leagues()
    print(f"Total available leagues: {len(available)}")
    if LEAGUE in available:
        print(f"'{LEAGUE}' IS in the available leagues list.")
    else:
        print(f"'{LEAGUE}' is NOT in the available leagues list.")
        print(f"Full list: {available}")
        return

    print(f"\nAttempting to create WhoScored scraper for {LEAGUE}, {SEASON}...")
    try:
        ws = sd.WhoScored(LEAGUE, SEASON)
    except Exception as e:
        print(f"Failed to create scraper instance: {type(e).__name__}: {e}")
        return

    print("Scraper instance created. Attempting to read schedule...")
    try:
        schedule = ws.read_schedule()
    except Exception as e:
        print(f"Failed to read schedule: {type(e).__name__}: {e}")
        return

    print(f"Success. Schedule shape: {schedule.shape}")
    print(schedule.head())


if __name__ == "__main__":
    main()
