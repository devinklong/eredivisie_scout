"""
scrape_all_whoscored_matches.py (cache-only rewrite)

Regenerates per-match derived JSON (data/whoscored/{season}/{match_id}.json)
purely from soccerdata's own on-disk WhoScored cache -- NO network calls,
NO sd.WhoScored() instantiation, NO Selenium/Chrome launch, in any season.

WHY THIS REWRITE: sd.WhoScored()'s constructor appears to launch a
SeleniumBase UC-mode Chrome window on instantiation regardless of whether
force_cache=True ends up serving every individual request from disk --
observed directly (Chrome windows popped up during a supposedly
cache-only rerun of the original script, across seasons that should have
been fully cached already). Since the actual goal here is a pure
reprocessing pass -- recomputing derived stats (now including
whoscored_player_id) from already-cached raw events, not fetching
anything new -- this version reads soccerdata's cache files directly
with plain file I/O and never touches the sd.WhoScored class at all.

CACHE LOCATION: soccerdata stores each match's full raw JSON response at
~/soccerdata/data/WhoScored/events/{league}_{season_code}/{match_id}.json
-- confirmed via this project's own tests/whoscored/check_cache_file_path.py
and the console log showing "Saving cached data to
/Users/devinlong/soccerdata/data/WhoScored". season_code is soccerdata's
compact numeric form (e.g. '2015-16' -> '1516'), per
parse_raw_whoscored_events.py's season_to_compact_code() -- reused here
directly rather than redefined.

ASSUMPTION FLAGGED, NOT independently confirmed here: the cached JSON's
top-level shape is assumed to be {"events": [...], "home": {...},
"away": {...}, "playerIdNameDictionary": {...}} -- consistent with
WhoScored's known public API response shape, and with what
parse_raw_whoscored_events.py already reads from this exact same file
(playerIdNameDictionary, home/away). The "events" key name itself is
inferred, not verified against this project's own real cached files.

RUN verify_cache_shape() BELOW AGAINST ONE REAL CACHED FILE BEFORE
TRUSTING THIS AT FULL SCALE. If the key is named differently than
"events", only the RAW_EVENTS_KEY constant needs to change -- everything
else in this script is unaffected.

If a match's cache file is missing entirely, it is skipped and logged --
this script will NEVER fall back to a live fetch, no exceptions. A
missing file means that match genuinely isn't cached (unexpected, given
the original extraction already succeeded for these seasons) -- not
something to silently paper over by allowing a live request through.
"""

import json
from pathlib import Path

from derive_passing_stats import derive_passing_stats
from derive_possession_stats import (
    derive_touch_stats,
    derive_take_on_stats,
    derive_dispossessed_stats,
)
from derive_defense_stats import (
    derive_tackle_stats,
    derive_interception_stats,
    derive_clearance_stats,
    derive_challenge_stats,
    derive_error_stats,
)
from derive_finalthird_stats import derive_finalthird_stats
from parse_raw_whoscored_events import parse_raw_events, season_to_compact_code

LEAGUE = "NED-Eredivisie"
SEASONS = [
    "2013-14", "2014-15", "2015-16", "2016-17", "2017-18", "2018-19",
    "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
    "2025-26",
]
OUTPUT_DIR = Path("data/whoscored")

# soccerdata's own on-disk cache root -- confirmed via console log output
# and check_cache_file_path.py, NOT a documented/stable public API. If a
# future soccerdata version changes its cache layout, this path breaks
# and needs updating by hand.
CACHE_ROOT = Path.home() / "soccerdata" / "data" / "WhoScored"

# See ASSUMPTION note in module docstring -- verify this against a real
# file via verify_cache_shape() before trusting the rest of this script.
RAW_EVENTS_KEY = "events"


def verify_cache_shape(league, season, match_id):
    """Run this FIRST, against one known-good match_id, before running
    main() at full scale. Prints the top-level keys of a real cached
    file so you can confirm RAW_EVENTS_KEY is actually correct."""
    season_code = season_to_compact_code(season)
    filepath = CACHE_ROOT / "events" / f"{league}_{season_code}" / f"{match_id}.json"
    if not filepath.exists():
        print(f"No cache file found at {filepath}")
        return
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"Top-level keys in {filepath.name}: {list(data.keys())}")
    if RAW_EVENTS_KEY in data:
        print(f"'{RAW_EVENTS_KEY}' found -- contains "
              f"{len(data[RAW_EVENTS_KEY])} events. Looks correct.")
    else:
        print(f"'{RAW_EVENTS_KEY}' NOT found in this file -- "
              f"update RAW_EVENTS_KEY to match one of the keys printed "
              f"above before running main().")


def load_cached_match(league, season, match_id):
    """Reads one match's cached JSON directly from disk -- no
    sd.WhoScored() instantiation, no network, no Selenium. Returns a
    parsed events DataFrame via parse_raw_whoscored_events.parse_raw_events
    (already built and validated for the fallback-parser seasons, reused
    here for every season), or None if the cache file doesn't exist."""
    season_code = season_to_compact_code(season)
    filepath = CACHE_ROOT / "events" / f"{league}_{season_code}" / f"{match_id}.json"
    if not filepath.exists():
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        full_json = json.load(f)

    raw_events = full_json.get(RAW_EVENTS_KEY)
    if raw_events is None:
        return None

    player_names = {int(k): v for k, v in full_json.get("playerIdNameDictionary", {}).items()}
    team_names = {
        int(full_json[side]["teamId"]): full_json[side]["name"]
        for side in ["home", "away"] if side in full_json
    }

    return parse_raw_events(raw_events, player_names, team_names)


def process_match(events, match_id):
    """Unchanged from the original script's logic -- runs every
    derivation function (now including player_id in each groupby) and
    returns a single combined dict, keyed by category."""
    if events is None or len(events) == 0 or "type" not in events.columns:
        raise ValueError(f"No usable event data for match_id={match_id}.")

    return {
        "passing": derive_passing_stats(events).to_dict(orient="records"),
        "touches": derive_touch_stats(events).to_dict(orient="records"),
        "take_ons": derive_take_on_stats(events).to_dict(orient="records"),
        "dispossessed": derive_dispossessed_stats(events).to_dict(orient="records"),
        "tackles": derive_tackle_stats(events).to_dict(orient="records"),
        "interceptions": derive_interception_stats(events).to_dict(orient="records"),
        "clearances": derive_clearance_stats(events).to_dict(orient="records"),
        "dribbled_past": derive_challenge_stats(events).to_dict(orient="records"),
        "errors": derive_error_stats(events).to_dict(orient="records"),
        "final_third_entries": derive_finalthird_stats(events).to_dict(orient="records"),
    }


def save_match_json(match_id, season, data):
    season_dir = OUTPUT_DIR / season
    season_dir.mkdir(parents=True, exist_ok=True)
    path = season_dir / f"{match_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path


def main():
    for season in SEASONS:
        print(f"\n{'=' * 60}\nSeason: {season}\n{'=' * 60}")
        season_code = season_to_compact_code(season)
        cache_dir = CACHE_ROOT / "events" / f"{LEAGUE}_{season_code}"

        if not cache_dir.exists():
            print(f"No cache directory found at {cache_dir} -- skipping "
                  f"this season entirely (unexpected for a previously "
                  f"extracted season -- worth investigating, not just "
                  f"moving on).")
            continue

        match_files = list(cache_dir.glob("*.json"))
        print(f"Found {len(match_files)} cached match files.")

        succeeded = 0
        failed = []

        for i, match_file in enumerate(match_files, start=1):
            match_id = match_file.stem
            print(f"[{i}/{len(match_files)}] match_id={match_id}...", end=" ")
            try:
                events = load_cached_match(LEAGUE, season, match_id)
                if events is None or len(events) == 0:
                    print("SKIPPED (no cached data)")
                    failed.append(match_id)
                    continue

                data = process_match(events, match_id)
                path = save_match_json(match_id, season, data)
                print(f"OK -> {path}")
                succeeded += 1
            except Exception as e:
                print(f"FAILED -- {type(e).__name__}: {e}")
                failed.append(match_id)

        print(f"\n{season} summary: {succeeded}/{len(match_files)} succeeded")
        if failed:
            print(f"Failed/skipped match_ids: {failed}")


if __name__ == "__main__":
    # verify_cache_shape() confirmed RAW_EVENTS_KEY = "events" is correct
    # (2026-09-04) -- proceeding straight to the full regeneration.
    main()
