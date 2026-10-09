"""
Writes, for each WhoScored season, the list of REGULAR-SEASON match ids to aggregate.

WHY: WhoScored's season schedule for the Eredivisie also lists non-regular-season matches
(European play-offs, promotion/relegation play-offs). The scraper saved every match it could
extract, so most seasons have 306 match files (18 clubs x 17 home matches) PLUS the play-off
matches: 312 files in 2013-14 to 2018-19 and 2021-22, 309 in 2020-21. The aggregation summed every file,
so a play-off club's WhoScored counts covered about 4 extra matches while FBref (league only)
and every `ws_*_per90` denominator did not: those players' counts and rates are inflated.

RULE (self-validating, no reliance on a stage label): sort the schedule by date, then take a
match as regular only while BOTH clubs still have fewer than 34 regular matches. A club's 35th
match is a play-off. Then check the result: every club must have exactly 34 regular matches,
(which also fixes the total at clubs x 34 / 2). Anything else raises instead of writing a manifest.
2019-20 was abandoned after 26 rounds, with no play-offs, so every scheduled match is kept
(and no club may exceed 34).

Needs soccerdata's cached schedule (the same call the scraper makes, force_cache=True).

Usage:
    python pipelines/whoscored/build_regular_season_manifest.py
    python pipelines/whoscored/build_regular_season_manifest.py --seasons 2013-14 2014-15
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

LEAGUE = "NED-Eredivisie"
DATA_ROOT = Path("data/whoscored")
MANIFEST_NAME = "regular_season_matches.json"
MATCHES_PER_CLUB = 34
SEASONS = ["2013-14", "2014-15", "2015-16", "2016-17", "2017-18", "2018-19", "2019-20", "2020-21",
           "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
# None = the season was cut short with no play-offs: keep every scheduled match.
SEASON_MATCHES_PER_CLUB = {"2019-20": None}


class ManifestError(Exception):
    pass


def regular_season_ids(schedule, matches_per_club=MATCHES_PER_CLUB):
    """Return (regular_ids, excluded_ids, per_club_counts) from a schedule DataFrame with the
    columns game_id, date, home_team, away_team. Raises ManifestError if the result is not a
    complete round-robin."""
    need = {"game_id", "date", "home_team", "away_team"}
    missing = need - set(schedule.columns)
    if missing:
        raise ManifestError(f"schedule lacks columns {sorted(missing)}")
    df = schedule[["game_id", "date", "home_team", "away_team"]].copy()
    if df["date"].isna().any() or df["home_team"].isna().any() or df["away_team"].isna().any():
        raise ManifestError("schedule has matches with a missing date or team; cannot order them")
    if df["game_id"].duplicated().any():
        raise ManifestError("schedule lists the same game_id twice")
    df = df.sort_values(["date", "game_id"], kind="stable")
    counts = defaultdict(int)
    regular, excluded = [], []
    for gid, h, a in zip(df["game_id"], df["home_team"], df["away_team"]):
        if matches_per_club is None or (counts[h] < matches_per_club and counts[a] < matches_per_club):
            regular.append(int(gid))
            counts[h] += 1
            counts[a] += 1
        else:
            excluded.append(int(gid))
    if matches_per_club is None:
        over = {t: n for t, n in counts.items() if n > MATCHES_PER_CLUB}
        if over:
            raise ManifestError(f"club(s) with more than {MATCHES_PER_CLUB} matches in a season kept whole: {over}")
    else:
        short = {t: n for t, n in counts.items() if n != matches_per_club}
        if short:
            raise ManifestError(f"club(s) without exactly {matches_per_club} regular matches: {short}")
    return regular, excluded, dict(counts)


def build_manifest(season, schedule):
    r = SEASON_MATCHES_PER_CLUB.get(season, MATCHES_PER_CLUB)
    regular, excluded, counts = regular_season_ids(schedule, r)
    return {"season": season, "matches_per_club": r, "clubs": len(counts),
            "regular_match_ids": regular, "excluded_match_ids": excluded}


def write_manifest(season, manifest, root=DATA_ROOT):
    path = Path(root) / season / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1))
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", nargs="+", default=SEASONS)
    args = ap.parse_args(argv)
    import soccerdata as sd
    for season in args.seasons:
        schedule = sd.WhoScored(LEAGUE, season).read_schedule(force_cache=True).reset_index()
        m = build_manifest(season, schedule)
        path = write_manifest(season, m)
        on_disk = {p.stem for p in (DATA_ROOT / season).glob("*.json") if p.name != MANIFEST_NAME}
        reg = {str(i) for i in m["regular_match_ids"]}
        exc = {str(i) for i in m["excluded_match_ids"]}
        print(f"{season}: {len(reg)} regular, {len(exc)} excluded (scheduled); on disk {len(on_disk)}: "
              f"{len(on_disk & reg)} regular, {len(on_disk & exc)} excluded, {len(on_disk - reg - exc)} not in the schedule, "
              f"{len(reg - on_disk)} regular matches have no file -> {path}")


if __name__ == "__main__":
    main()
