"""
Test script: confirms whether the soccerdata library's FBref module actually
supports the Eredivisie before building anything further on top of it.

soccerdata's FBref class runs a real (headless by default) browser under the
hood, which is why it stands a real chance against FBref's Cloudflare
protection where plain requests/cloudscraper failed. This script just checks
league support and pulls one small, cheap dataset (the schedule) to confirm.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"


def main():
    print(f"Attempting to create FBref scraper for {LEAGUE}, {SEASON}...")
    try:
        fbref = sd.FBref(LEAGUE, SEASON)
    except Exception as e:
        print(f"Failed to create scraper instance: {type(e).__name__}: {e}")
        return

    print("Scraper instance created. Attempting to read schedule...")
    try:
        schedule = fbref.read_schedule()
    except Exception as e:
        print(f"Failed to read schedule: {type(e).__name__}: {e}")
        return

    print(f"Success. Schedule shape: {schedule.shape}")
    print(schedule.head())


if __name__ == "__main__":
    main()
