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
FALLBACK PARSER INTEGRATED (2026-09-01): for seasons where soccerdata's
standard read_events() crashes with the confirmed casting bug
(TypeError: cannot safely cast non-equivalent object to int64 -- affects
2015-16 through 2018-19's related_event_id field), this script now
automatically falls back to parse_raw_whoscored_events.py's raw-JSON
converter instead of marking the match failed. Any OTHER exception is
still treated as a real failure, not silently caught. Each match's
console output notes "(via raw fallback parser)" when the fallback was
used, and the season summary reports a total fallback count -- not yet
validated at full-season scale, only against single matches so far.
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
from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASONS = [
    "2013-14", "2014-15", "2015-16", "2016-17", "2017-18", "2018-19",
    "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
    "2025-26",
]  # every confirmed-working season -- regenerating ALL of them since
   # the team-capture fix changed the JSON output format entirely.
   # Should be fast: every match's raw event data is already cached on
   # disk from the original runs, so this reprocesses locally rather
   # than re-scraping the web.
DATA_DIR = Path("data/whoscored")

# If non-empty, only these match_ids are processed (for retrying
# specific failures) instead of the full season schedule. Confirmed
# 2026-08-31: 1980233/1980234/1980235 are promotion/relegation playoff
# matches, not regular-season games -- out of scope, do not retry.
MATCH_IDS_OVERRIDE = []


def get_events_with_fallback(ws, league, season, match_id):
    """Tries soccerdata's standard read_events() first. If it hits the
    known casting bug (TypeError: cannot safely cast non-equivalent
    object to int64 -- confirmed 2026-09-01 to affect 2015-16 through
    2018-19's related_event_id field), falls back to
    parse_raw_whoscored_events.get_events_for_match(), which bypasses
    soccerdata's formatting entirely via output_fmt="raw".

    Returns (events, used_fallback: bool). Any OTHER exception from the
    standard path is re-raised as-is -- this fallback is deliberately
    narrow, only for the one specific confirmed bug, not a catch-all."""
    try:
        events = ws.read_events(match_id=match_id, force_cache=True)
        return events, False
    except TypeError as e:
        if "cannot safely cast non-equivalent object to int64" not in str(e):
            raise  # a different TypeError -- don't silently swallow it
        events = get_events_raw_fallback(league, season, match_id)
        return events, True


def process_match(events, match_id):
    """Runs every derivation function against one match's events and
    returns a single combined dict, keyed by category -- kept as
    separate lists (not merged into one wide table) since each has its
    own player population/grain, matching how they were built and
    validated individually.

    FIXED (2026-09-02): all derive_*.py functions now group by
    ["player", "team"], not just "player" -- previously team was
    silently dropped entirely, making it impossible to look up e.g.
    "Ajax's 2025-26 squad" from the output. Output format changed
    accordingly from orient="index" (a dict keyed by player name, which
    can't hold a team field and breaks on duplicate names) to
    orient="records" (a list of dicts, each with explicit "player" and
    "team" keys) -- required since a JSON object key must be a single
    string, not a (player, team) tuple.

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
        used_fallback_count = 0
        failed = []

        for i, match_id in enumerate(match_ids, start=1):
            print(f"[{i}/{len(match_ids)}] match_id={match_id}...", end=" ")
            try:
                events, used_fallback = get_events_with_fallback(ws, LEAGUE, season, match_id)
                if events is None or len(events) == 0:
                    print("SKIPPED (no events returned)")
                    failed.append(match_id)
                    continue

                data = process_match(events, match_id)
                path = save_match_json(match_id, season, data)
                fallback_note = " (via raw fallback parser)" if used_fallback else ""
                print(f"OK{fallback_note} -> {path}")
                succeeded += 1
                if used_fallback:
                    used_fallback_count += 1
            except Exception as e:
                print(f"FAILED -- {type(e).__name__}: {e}")
                failed.append(match_id)

            # Politeness delay -- cheap now that force_cache avoids the
            # heavy calendar refetch, but still worth not hammering.
            time.sleep(1)

        print(f"\n{season} summary: {succeeded}/{len(match_ids)} succeeded"
              f" ({used_fallback_count} via raw fallback parser)")
        if failed:
            print(f"Failed/skipped match_ids: {failed}")


if __name__ == "__main__":
    main()
