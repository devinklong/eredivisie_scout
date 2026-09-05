"""
Diagnostic: scans every JSON file across every season folder for any
record whose "player" value looks numeric (e.g. '298844.0', '0.0',
298844, 0) instead of a real name string -- these are the rows showing
up as garbage player_name values in eredivisie_whoscored_player_season_stats.

Prints every match/category where this happens, plus the full record,
so we can see exactly what's actually in the raw derived JSON rather
than guessing at season-folder/team-name conventions.
"""

import json
from pathlib import Path

DATA_ROOT = Path("data/whoscored")

# Only the 13 confirmed-working seasons (per v1_roadmap.md) -- matches
# aggregate_and_load_whoscored_season.py's SEASONS list exactly. Older
# folders like 2012-13 may still exist on disk from early testing/
# exploration and are NOT part of the real pipeline -- scanning them
# produces false leads (confirmed 2026-09-04: 2012-13/611804.json is a
# stale pre-fix-format leftover, unrelated to the real bug).
SEASONS = [
    "2013-14", "2014-15", "2015-16", "2016-17", "2017-18", "2018-19",
    "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
    "2025-26",
]


def looks_numeric(value):
    if value is None:
        return False
    s = str(value)
    try:
        float(s)
        return True
    except ValueError:
        return False


def main():
    found_any = False

    for season in SEASONS:
        season_dir = DATA_ROOT / season
        if not season_dir.exists():
            print(f"{season}: no folder found at {season_dir} -- skipping")
            continue

        for f in sorted(season_dir.glob("*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)

            for category, records in data.items():
                for record in records:
                    if not isinstance(record, dict):
                        found_any = True
                        print(f"{season_dir.name}/{f.name} [{category}]: "
                              f"NON-DICT RECORD ({type(record).__name__}): {record!r}")
                        continue

                    player = record.get("player")
                    if looks_numeric(player):
                        found_any = True
                        print(f"{season_dir.name}/{f.name} [{category}]: {record}")

    if not found_any:
        print("No numeric-looking player values found in any season/file.")


if __name__ == "__main__":
    main()
