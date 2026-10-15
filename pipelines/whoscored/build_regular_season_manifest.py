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

CROSS-CHECK: the schedule also carries a `stage` label (the league vs the play-off competition). The
date rule above is what decides; the label is an independent check, and a disagreement is printed.

DUPLICATE FIXTURES: in a double round-robin each (home, away) pair occurs once per stage. If the schedule
lists one twice (seen in 2018-19: 307 league rows instead of 306), the date rule drops the wrong matches
and some clubs end on 33. A duplicate pair is resolved by the match FILES: the row whose file exists is
kept; if that does not settle it (none or both have files) the season fails. The result is still verified
by the exact 34-per-club check.

Needs soccerdata's cached schedule (the same call the scraper makes, force_cache=True).

Usage:
    python pipelines/whoscored/build_regular_season_manifest.py
    python pipelines/whoscored/build_regular_season_manifest.py --seasons 2013-14 2014-15
"""

import argparse
import json
import sys
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


def _schedule_frame(schedule):
    need = {"game_id", "date", "home_team", "away_team"}
    missing = need - set(schedule.columns)
    if missing:
        raise ManifestError(f"schedule lacks columns {sorted(missing)}")
    df = schedule[["game_id", "date", "home_team", "away_team"]].copy()
    if df["date"].isna().any() or df["home_team"].isna().any() or df["away_team"].isna().any():
        raise ManifestError("schedule has matches with a missing date or team; cannot order them")
    if df["game_id"].duplicated().any():
        raise ManifestError("schedule lists the same game_id twice")
    return df.sort_values(["date", "game_id"], kind="stable")


def _assign(df, matches_per_club):
    counts = defaultdict(int)
    regular, excluded = [], []
    for gid, h, a in zip(df["game_id"], df["home_team"], df["away_team"]):
        if matches_per_club is None or (counts[h] < matches_per_club and counts[a] < matches_per_club):
            regular.append(int(gid))
            counts[h] += 1
            counts[a] += 1
        else:
            excluded.append(int(gid))
    return regular, excluded, dict(counts)


def regular_season_ids(schedule, matches_per_club=MATCHES_PER_CLUB):
    """Return (regular_ids, excluded_ids, per_club_counts) from a schedule DataFrame with the
    columns game_id, date, home_team, away_team. Raises ManifestError if the result is not a
    complete round-robin."""
    regular, excluded, counts = _assign(_schedule_frame(schedule), matches_per_club)
    if matches_per_club is None:
        over = {t: n for t, n in counts.items() if n > MATCHES_PER_CLUB}
        if over:
            raise ManifestError(f"club(s) with more than {MATCHES_PER_CLUB} matches in a season kept whole: {over}")
    else:
        short = {t: n for t, n in counts.items() if n != matches_per_club}
        if short:
            raise ManifestError(f"club(s) without exactly {matches_per_club} regular matches: {short}")
    return regular, excluded, counts


NO_STAGE = "(no stage label)"


def _stage_series(schedule):
    """The stage label per row with missing labels made explicit, or None if there is no usable column.
    A single-competition season (2019-20) has the column but every value empty: one label, no exclusions."""
    if "stage" not in schedule.columns or schedule.empty:
        return None
    return schedule["stage"].fillna(NO_STAGE)


def drop_duplicate_fixtures(schedule, on_disk):
    """Resolve repeated (stage, home, away) rows using which match files exist. Returns
    (schedule_without_the_dropped_rows, dropped_game_ids). Only applies when the schedule has a
    `stage` column; raises ManifestError if a duplicate cannot be settled by the files."""
    stage = _stage_series(schedule)
    if stage is None:
        return schedule, []
    schedule = schedule.assign(stage=stage)
    key = ["stage", "home_team", "away_team"]
    dup = schedule[schedule.duplicated(key, keep=False)]
    dropped = []
    for _, grp in dup.groupby(key, dropna=False):
        has_file = [str(g) in on_disk for g in grp["game_id"]]
        if sum(has_file) != 1:
            ids = [int(g) for g in grp["game_id"]]
            raise ManifestError(f"fixture listed {len(grp)} times and the match files do not settle which is real "
                                f"({sum(has_file)} of them have a file): {grp.iloc[0]['home_team']} - {grp.iloc[0]['away_team']}, "
                                f"game_ids {ids}")
        dropped += [int(g) for g, f in zip(grp["game_id"], has_file) if not f]
    return schedule[~schedule["game_id"].astype(int).isin(dropped)], sorted(dropped)


def stage_label_excluded(schedule):
    """game_ids whose `stage` label differs from the schedule's main stage (None without the column)."""
    stage = _stage_series(schedule)
    if stage is None:
        return None
    main = stage.value_counts().idxmax()
    return {int(g) for g, st in zip(schedule["game_id"], stage) if st != main}


def diagnose(schedule, matches_per_club=MATCHES_PER_CLUB, on_disk=None):
    """Text explaining WHY a season failed: the schedule's columns, each short club's regular and
    total scheduled matches, and every scheduled meeting between two short clubs (a double
    round-robin has exactly 2 per pair, so 1 means a fixture is missing from the schedule)."""
    out = [f"  schedule: {len(schedule)} rows, columns {list(schedule.columns)}"]
    if "stage" in schedule.columns:
        out.append(f"  stage values: {schedule['stage'].value_counts(dropna=False).to_dict()}")
    stage = _stage_series(schedule)
    if stage is not None:
        schedule = schedule.assign(stage=stage)
        main = stage.value_counts().idxmax()
        league = schedule[schedule["stage"] == main]
        per = defaultdict(int)
        for h, a in zip(league["home_team"], league["away_team"]):
            per[h] += 1
            per[a] += 1
        odd = {t: n for t, n in per.items() if n != (matches_per_club or MATCHES_PER_CLUB)}
        out.append(f"  clubs with other than {matches_per_club or MATCHES_PER_CLUB} matches inside the main stage '{main}': {odd or 'none'}")
        dups = schedule[schedule.duplicated(["stage", "home_team", "away_team"], keep=False)]
        for _, r in dups.sort_values(["home_team", "away_team", "date"]).iterrows():
            f = "" if on_disk is None else ("  [file]" if str(r["game_id"]) in on_disk else "  [NO FILE]")
            out.append(f"  repeated fixture: {pd.Timestamp(r['date']).date()}  {r['home_team']} - {r['away_team']}  game_id {r['game_id']}  stage {r['stage']}{f}")
    df = _schedule_frame(schedule)
    _, _, counts = _assign(df, matches_per_club)
    total = defaultdict(int)
    for h, a in zip(df["home_team"], df["away_team"]):
        total[h] += 1
        total[a] += 1
    target = matches_per_club or MATCHES_PER_CLUB
    short = sorted(t for t in total if counts.get(t, 0) != target)
    for t in short:
        out.append(f"  {t}: {counts.get(t, 0)} regular, {total[t]} scheduled in all")
    for i, a in enumerate(short):
        for b in short[i + 1:]:
            meet = df[((df["home_team"] == a) & (df["away_team"] == b)) | ((df["home_team"] == b) & (df["away_team"] == a))]
            out.append(f"  {a} vs {b}: {len(meet)} scheduled meeting(s) (a double round-robin has 2)")
            for _, r in meet.iterrows():
                out.append(f"      {pd.Timestamp(r['date']).date()}  {r['home_team']} - {r['away_team']}  game_id {r['game_id']}")
    return "\n".join(out)


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


def process_seasons(seasons, read_schedule, root=DATA_ROOT):
    """One season failing must not hide the others: returns (report_lines, failures)."""
    lines, failures = [], {}
    for season in seasons:
        season_dir = Path(root) / season
        on_disk = {p.stem for p in season_dir.glob("*.json") if p.name != MANIFEST_NAME} if season_dir.exists() else set()
        schedule = None
        try:
            schedule = read_schedule(season)
            clean, dropped = drop_duplicate_fixtures(schedule, on_disk)
            m = build_manifest(season, clean)
            label = stage_label_excluded(clean)
            m["dropped_duplicate_ids"] = dropped
            path = write_manifest(season, m, root)
        except Exception as e:           # one season's problem must not hide the others
            kind = "" if isinstance(e, ManifestError) else f"unexpected {type(e).__name__}: "
            failures[season] = f"{kind}{e}"
            lines.append(f"{season}: FAILED, no manifest written: {kind}{e}")
            if schedule is not None:
                try:
                    lines.append(diagnose(schedule, SEASON_MATCHES_PER_CLUB.get(season, MATCHES_PER_CLUB), on_disk))
                except Exception as d:
                    lines.append(f"  (diagnosis itself failed: {type(d).__name__}: {d})")
            continue
        reg = {str(i) for i in m["regular_match_ids"]}
        exc = {str(i) for i in m["excluded_match_ids"]}
        line = (f"{season}: {len(reg)} regular, {len(exc)} excluded (scheduled); on disk {len(on_disk)}: "
                f"{len(on_disk & reg)} regular, {len(on_disk & exc)} excluded, {len(on_disk - reg - exc)} not in the schedule, "
                f"{len(reg - on_disk)} regular matches have no file -> {path}")
        if dropped:
            line += f"\n    dropped {len(dropped)} duplicate schedule row(s) with no file: {dropped}"
        if label is not None:
            date_rule = {int(i) for i in m["excluded_match_ids"]}
            if label == date_rule:
                line += "\n    stage labels agree with the date rule"
            else:
                line += (f"\n    WARNING stage labels DISAGREE with the date rule: date rule only {sorted(date_rule - label)[:5]}, "
                         f"label only {sorted(label - date_rule)[:5]}")
        lines.append(line)
    return lines, failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", nargs="+", default=SEASONS)
    args = ap.parse_args(argv)
    import soccerdata as sd
    lines, failures = process_seasons(
        args.seasons, lambda season: sd.WhoScored(LEAGUE, season).read_schedule(force_cache=True).reset_index(),
        root=DATA_ROOT)
    print("\n" + "\n".join(lines))
    if failures:
        print(f"\n{len(failures)} season(s) FAILED: {sorted(failures)}. Their manifests were not written, so the "
              f"aggregator will refuse to load them.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
