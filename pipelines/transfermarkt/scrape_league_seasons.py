"""
Scrapes which clubs were in each Big-5 league in each season, 2010-2025, so
the model can tell whether a transfer's BUYER was in a Big-5 league that season.
80 pages: 5 leagues x 16 seasons. One JSON file per league-season in
data/transfermarkt/leagues/ (resume-safe), loaded by load_league_season_clubs.py.

BY SEASON, NOT BY CLUB: a club's overview page shows its CURRENT league, which
is wrong for historical transfers (Sunderland, Watford, Leeds, Burnley, Swansea
and Southampton have each moved between divisions since 2010).

Built from real pages inspected on 2026-10-05 with inspect_league_season.py:
  - /{slug}/startseite/wettbewerb/{code}?saison_id={year} works and the season
    parameter is honored (titles read 'Serie A 19/20' and so on).
  - The participants table is the class='items' table under a heading like
    'Clubs - Serie A 19/20'. That heading names the season.
  - Several other tables (standings, fixtures) hold the same clubs, and a few
    small tables hold OTHER clubs (e.g. Ligue 1 2023's 'Subsequent competitions'
    had three non-members), so "every club link on the page" is wrong.

A league-season is accepted only if ALL of these hold, otherwise it fails loudly
and nothing is saved for it:
  1. the page title names the requested season (a season parameter that was
     silently ignored would return the current table for every season),
  2. the season selector, if present, shows the requested season,
  3. a participants table exists whose heading names the same season,
  4. it holds the expected number of clubs (20, or 18 for the Bundesliga and for
     Ligue 1 from 2023/24),
  5. at least one OTHER table holds exactly the same set of clubs, so the member
     list is corroborated, not just a table that looked right.

Usage (run one first):
    python pipelines/transfermarkt/scrape_league_seasons.py --league IT1 --from-season 2019 --to-season 2019
    python pipelines/transfermarkt/scrape_league_seasons.py            # everything not yet scraped
    python pipelines/transfermarkt/scrape_league_seasons.py --force    # redo existing files
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup

from inspect_league_season import (
    BIG5,
    build_url,
    describe_tables,
    expected_club_count,
    season_evidence,
)
from scrape_buyer_clubs import ScrapeError, fetch_html

OUT_DIR = Path("data/transfermarkt/leagues")
FIRST_SEASON, LAST_SEASON = 2010, 2025
DELAY_BETWEEN_PAGES_SECONDS = 3
_CLUBS_HEADING = re.compile(r"^Clubs\b.*?(\d{2})/(\d{2})\s*$")


class LeagueSeasonError(ScrapeError):
    """A league-season page that cannot be trusted. Never saved."""


def season_label(season):
    """2019 -> '19/20', 1999 -> '99/00'."""
    return f"{season % 100:02d}/{(season + 1) % 100:02d}"


def parse_league_season(html, code, season):
    """Pure function: page HTML -> [{'club_id', 'club_name'}], or raises
    LeagueSeasonError naming exactly which guard failed."""
    soup = BeautifulSoup(html, "html.parser")
    label = season_label(season)
    ev = season_evidence(soup)

    if not ev["title"] or label not in ev["title"]:
        raise LeagueSeasonError(f"page title {ev['title']!r} does not name season {label} "
                                f"(season parameter ignored, or the wrong page)")
    for name, value, text in ev["selected"]:
        if name == "saison_id" and value != str(season):
            raise LeagueSeasonError(f"season selector shows {value!r} ({text}) but {season} was requested")

    tables = describe_tables(soup)
    candidates = []
    for t in tables:
        m = _CLUBS_HEADING.match(t["heading"] or "")
        if m and "items" in t["class"].split():
            candidates.append((t, m))
    if not candidates:
        raise LeagueSeasonError("no class='items' table under a 'Clubs - ... YY/YY' heading")

    table, m = candidates[0]
    if (int(m.group(1)), int(m.group(2))) != (season % 100, (season + 1) % 100):
        raise LeagueSeasonError(f"participants table heading {table['heading']!r} names a different "
                                f"season than {label}")

    clubs = table["clubs"]
    want = expected_club_count(code, season)
    if len(clubs) != want:
        raise LeagueSeasonError(f"{len(clubs)} clubs found, expected {want} for {code} {season}")

    ids = {cid for cid, _ in clubs}
    corroborating = [t["index"] for t in tables
                     if t is not table and {cid for cid, _ in t["clubs"]} == ids]
    if not corroborating:
        raise LeagueSeasonError("no second table on the page holds exactly the same clubs, "
                                "so the member list is uncorroborated")
    return [{"club_id": cid, "club_name": name} for cid, name in clubs]


def scrape_one(code, season):
    url = build_url(code, season)
    return url, parse_league_season(fetch_html(url), code, season)


def out_path(code, season):
    return OUT_DIR / f"{code}_{season}.json"


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--league", nargs="+", choices=sorted(BIG5), default=sorted(BIG5))
    p.add_argument("--from-season", type=int, default=FIRST_SEASON)
    p.add_argument("--to-season", type=int, default=LAST_SEASON)
    p.add_argument("--force", action="store_true", help="re-scrape files that already exist")
    args = p.parse_args()

    jobs = [(code, season) for code in args.league for season in range(args.from_season, args.to_season + 1)]
    print(f"{len(jobs)} league-season page(s) to consider")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    done, skipped, failures = [], [], []
    for i, (code, season) in enumerate(jobs, start=1):
        path = out_path(code, season)
        print(f"[{i}/{len(jobs)}] {code} {season_label(season)}", end=" ... ")
        if path.exists() and not args.force:
            print("already scraped, skipping")
            skipped.append((code, season))
            continue
        try:
            url, clubs = scrape_one(code, season)
        except ScrapeError as e:
            print(f"FAILED: {e}")
            failures.append((code, season, str(e)))
            continue
        records = [{"league_code": code, "season_id": season, **c} for c in clubs]
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK, {len(clubs)} clubs")
        done.append((code, season))
        if i < len(jobs):
            time.sleep(DELAY_BETWEEN_PAGES_SECONDS)

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    print(f"Scraped: {len(done)}   Skipped (already done): {len(skipped)}   Failed: {len(failures)}")
    for code, season, why in failures:
        print(f"  FAILED {code} {season}: {why}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
