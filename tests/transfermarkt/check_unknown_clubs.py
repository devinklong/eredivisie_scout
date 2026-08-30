"""
Scans a saved transfermarkt transfer-history JSON export for every row
where counterparty_club_name is literally "Unknown" (a real, distinct
case from a null club_id/"Retired" -- see extract_transfermarkt_
transfer_history.py's docstring notes), and reports the most recent one
by season_id, plus the full sorted list for reference.
"""

import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_path")
    args = parser.parse_args()

    with open(args.json_path, "r", encoding="utf-8") as f:
        transfers = json.load(f)

    unknown_rows = [t for t in transfers if t["counterparty_club_name"] == "Unknown"]
    print(f"Total 'Unknown' counterparty rows: {len(unknown_rows)}")

    # Rows with a real season_id, sorted most recent first
    with_season = [t for t in unknown_rows if t["season_id"] is not None]
    with_season.sort(key=lambda t: t["season_id"], reverse=True)

    if with_season:
        most_recent = with_season[0]
        print(f"\nMost recent 'Unknown' counterparty:")
        print(f"  Player: {most_recent['name']}")
        print(f"  Direction: {most_recent['direction']}")
        print(f"  Season: {most_recent['season_id']}")
    else:
        print("\nNo 'Unknown' rows with a season_id found.")

    print(f"\nFull list, most recent first ({len(with_season)} rows):")
    for t in with_season:
        print(f"  {t['name']} ({t['direction']}, season {t['season_id']})")


if __name__ == "__main__":
    main()
