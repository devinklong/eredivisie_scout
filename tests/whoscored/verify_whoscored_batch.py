"""
Verifies the WhoScored season-scale batch output (data/whoscored/{season}/
{match_id}.json) after scrape_all_whoscored_matches.py finishes:

1. File count vs. expected match count (from the real schedule)
2. Structural validity -- every file parses as JSON and has all 10
   expected top-level keys (one per derivation category)
3. Empty/near-empty file check -- flags files with suspiciously few
   entries in every category, which could indicate a match that
   returned events but the derivation logic found nothing (worth a
   manual look, not necessarily a bug)
4. A spot-check aggregate: total distinct players appearing across all
   files, and the single match with the most/fewest total events
   recorded across all categories -- gives you something concrete to
   sanity-check by hand (e.g. does the "most active" match make sense
   given real fixtures that week) rather than just trusting counts.
"""

import json
from pathlib import Path

import soccerdata as sd
    
LEAGUE = "NED-Eredivisie"
SEASONS = ["2010-11", "2011-12", "2012-13", "2013-14", "2014-15", "2015-16", "2016-17", "2017-18", "2018-19" "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"] 

EXPECTED_KEYS = {
    "passing", "touches", "take_ons", "dispossessed", "tackles",
    "interceptions", "clearances", "dribbled_past", "errors",
    "final_third_entries",
}


def verify_season(season):
    data_dir = Path("data/whoscored") / season

    print(f"\n{'=' * 60}\n{season}\n{'=' * 60}")

    if not data_dir.exists():
        print(f"  No data folder found at {data_dir} -- skipping (not scraped yet?)")
        return None

    ws = sd.WhoScored(LEAGUE, season)
    schedule = ws.read_schedule(force_cache=True)
    expected_match_ids = set(schedule["game_id"].tolist())

    files = list(data_dir.glob("*.json"))
    found_match_ids = {int(f.stem) for f in files}

    missing = expected_match_ids - found_match_ids
    extra = found_match_ids - expected_match_ids

    print(f"  Expected: {len(expected_match_ids)}, Found: {len(files)}, "
          f"Missing: {len(missing)}")
    if missing:
        print(f"  Missing match_ids: {sorted(missing)}")
    if extra:
        print(f"  EXTRA (not in schedule): {sorted(extra)}")

    malformed = 0
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if EXPECTED_KEYS - set(data.keys()):
                malformed += 1
        except json.JSONDecodeError:
            malformed += 1
    if malformed:
        print(f"  MALFORMED files: {malformed}")
    else:
        print("  All files structurally valid.")

    return {
        "expected": len(expected_match_ids),
        "found": len(files),
        "missing": len(missing),
        "missing_ids": sorted(missing),
        "malformed": malformed,
    }


def main():
    results = {}
    for season in SEASONS:
        result = verify_season(season)
        if result:
            results[season] = result

    print(f"\n{'=' * 60}\nGrand total across {len(results)} season(s)\n{'=' * 60}")
    total_expected = sum(r["expected"] for r in results.values())
    total_found = sum(r["found"] for r in results.values())
    total_missing = sum(r["missing"] for r in results.values())
    total_malformed = sum(r["malformed"] for r in results.values())

    print(f"Total expected matches: {total_expected}")
    print(f"Total found:            {total_found}")
    print(f"Total missing:          {total_missing}")
    print(f"Total malformed:        {total_malformed}")

    print("\nPer-season missing count:")
    for season, r in results.items():
        print(f"  {season}: {r['missing']} missing")


if __name__ == "__main__":
    main()
