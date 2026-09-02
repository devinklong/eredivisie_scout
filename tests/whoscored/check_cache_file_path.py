"""
Diagnostic: finds out where soccerdata actually cached this match's
event JSON on disk, since parse_raw_whoscored_events.py's guessed path
(events/{league}_{season}/{match_id}.json) isn't finding player/team
names -- either the path is wrong, or the file exists but doesn't
contain playerIdNameDictionary/home/away the way expected.
"""

from pathlib import Path

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2015-16"
MATCH_ID = 956891


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    print(f"ws.data_dir = {ws.data_dir}")

    events_dir = ws.data_dir / "events"
    print(f"\nLooking in: {events_dir}")
    if events_dir.exists():
        print("Subfolders found:")
        for sub in events_dir.iterdir():
            print(f"  {sub}")
    else:
        print("events_dir does not exist at all.")

    # Search the whole data_dir for anything with this match_id in the
    # filename, wherever it actually landed.
    print(f"\nSearching entire data_dir for '{MATCH_ID}' in any filename...")
    matches = list(ws.data_dir.rglob(f"*{MATCH_ID}*"))
    for m in matches:
        print(f"  FOUND: {m}")

    if not matches:
        print("  No files found matching that match_id anywhere under data_dir.")


if __name__ == "__main__":
    main()
