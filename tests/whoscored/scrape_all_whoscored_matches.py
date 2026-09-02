"""
Season-scale WhoScored batch extraction: loops every match in the
Eredivisie schedule, pulls events for each (force_cache=True per the
confirmed fix in patch_list.md -- ~1000x speedup, 129-229s/match down
to 0.1-0.2s/match), and runs all four derivation functions (passing,
possession, defense, final-third) built and validated earlier this
project.

Dumps each match's raw derived stats to its own JSON file immediately
(data/whoscored/{season}/{match_id}.json) -- same safety-checkpoint
pattern used for the 29-club Transfermarkt batch: a failure partway
through doesn't require re-processing matches already done.

ASSUMPTION FLAGGED: imports the four derive_*_stats functions directly
from their existing tests/whoscored/ files, assuming their current
signatures still match what was last confirmed working (each takes
`events` as its only argument and returns a DataFrame or dict). Not
re-verified against the live file contents at the time this script was
written -- if an import or call fails, check the actual current
function signature in the corresponding derive_*.py file before
assuming this batch script's logic is wrong.

Season-participation filtering (which club/season pairs are genuinely
Eredivisie) is NOT applied here -- WhoScored's own schedule is already
scoped to real Eredivisie matches for the season/league passed to
WhoScored(), unlike Transfermarkt's club-history pages which needed the
separate eredivisie_club_status filter.

CONFIRMED (2026-08-31): 2025-26's schedule includes 3 promotion/
relegation playoff matches (game_ids 1980233/1980234/1980235) alongside
the 306 real regular-season matches. These 3 failed/were skipped during
extraction -- confirmed this is expected, not a bug: playoff matches are
a structurally different competition (involving non-Eredivisie Eerste
Divisie clubs) and are out of scope for this project's thesis anyway,
which is built around regular-season performance. 306/309 (100% of the
real regular-season matches) is the correct, complete result for this
season. MATCH_IDS_OVERRIDE is not needed for these 3 -- do not keep
retrying them.

NOTE on force_cache and season choice: the confirmed 1000x speedup was
measured against 2026-27, an in-progress season -- soccerdata's own
caching logic (no_cache = current_season and not force_cache) only
skips its cache for a season it considers "current" (incomplete). For
2025-26 (a fully completed season), current_season is already False, so
no_cache is False regardless of force_cache -- meaning the cache should
already be used by default here, independent of the force_cache flag.
force_cache=True is still passed below since it's harmless either way,
but the dramatic before/after speed difference measured earlier may not
apply the same way to a completed season -- the first pass through each
match should still be reasonably fast, just via ordinary caching rather
than the specific fix confirmed for a current season.
"""

import json
import time
from pathlib import Path

import soccerdata as sd

# Import the derivation functions built and validated earlier this
# project. See module docstring's ASSUMPTION note.
import sys
sys.path.insert(0, str(Path(__file__).parent))

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

LEAGUE = "NED-Eredivisie"
SEASONS = ["2018-19"]  # a fully completed season; extend to a full
                        # historical list once this run is confirmed clean
DATA_DIR = Path("data/whoscored")

# If non-empty, only these match_ids are processed (for retrying
# specific failures) instead of the full season schedule. Confirmed
# 2026-08-31: 1980233/1980234/1980235 are promotion/relegation playoff
# matches, not regular-season games -- out of scope, do not retry.
MATCH_IDS_OVERRIDE = []


def process_match(events, match_id):
    """Runs every derivation function against one match's events and
    returns a single combined dict of DataFrames, keyed by category --
    kept as separate frames (not merged into one wide table) since each
    has its own player population/grain, matching how they were built
    and validated individually.

    Guards against matches where WhoScored genuinely has no event data
    at all (confirmed real case: game_id=409048, 2010-11 -- WhoScored's
    own log says "No events found for game 409048"). In that case
    events comes back with no 'type' column, and every derive_* function
    would raise a KeyError. Treated as a clean skip, not a crash --
    matches the same "older seasons have real data gaps" pattern already
    seen in Transfermarkt's '?' fees for old transfers."""
    if events is None or len(events) == 0 or "type" not in events.columns:
        raise ValueError(
            f"No usable event data for match_id={match_id} -- "
            "WhoScored has no events for this match (common for older "
            "seasons, e.g. 2010-11). Not a processing bug."
        )

    return {
        "passing": derive_passing_stats(events).to_dict(orient="index"),
        "touches": derive_touch_stats(events).to_dict(orient="index"),
        "take_ons": derive_take_on_stats(events).to_dict(orient="index"),
        "dispossessed": derive_dispossessed_stats(events).to_dict(),
        "tackles": derive_tackle_stats(events).to_dict(orient="index"),
        "interceptions": derive_interception_stats(events).to_dict(orient="index"),
        "clearances": derive_clearance_stats(events).to_dict(),
        "dribbled_past": derive_challenge_stats(events).to_dict(),
        "errors": derive_error_stats(events).to_dict(),
        "final_third_entries": derive_finalthird_stats(events).to_dict(orient="index"),
    }


def save_match_json(match_id, season, data):
    season_dir = DATA_DIR / season
    season_dir.mkdir(parents=True, exist_ok=True)
    path = season_dir / f"{match_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path


def main():
    for season in SEASONS:
        print(f"\n{'=' * 60}\nSeason: {season}\n{'=' * 60}")
        ws = sd.WhoScored(LEAGUE, season)

        print("Fetching schedule (force_cache=True)...")
        schedule = ws.read_schedule(force_cache=True)

        if MATCH_IDS_OVERRIDE:
            match_ids = MATCH_IDS_OVERRIDE
            print(f"Using MATCH_IDS_OVERRIDE -- retrying {len(match_ids)} "
                  f"specific match(es) instead of the full schedule.")
        else:
            match_ids = schedule["game_id"].tolist()
            print(f"Found {len(match_ids)} matches.")

        succeeded = 0
        failed = []

        for i, match_id in enumerate(match_ids, start=1):
            print(f"[{i}/{len(match_ids)}] match_id={match_id}...", end=" ")
            try:
                events = ws.read_events(match_id=match_id, force_cache=True)
                if events is None or len(events) == 0:
                    print("SKIPPED (no events returned)")
                    failed.append(match_id)
                    continue

                data = process_match(events, match_id)
                path = save_match_json(match_id, season, data)
                print(f"OK -> {path}")
                succeeded += 1
            except Exception as e:
                print(f"FAILED -- {type(e).__name__}: {e}")
                failed.append(match_id)

            # Politeness delay -- cheap now that force_cache avoids the
            # heavy calendar refetch, but still worth not hammering.
            time.sleep(1)

        print(f"\n{season} summary: {succeeded}/{len(match_ids)} succeeded")
        if failed:
            print(f"Failed/skipped match_ids: {failed}")


if __name__ == "__main__":
    main()
