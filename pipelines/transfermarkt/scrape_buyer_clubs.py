"""
Scrapes the full transfer history of each BUYER club -- the non-Eredivisie
clubs that have paid real fees for Eredivisie-sourced players -- so a
transfer's fee can be measured against the buying club's TOTAL spending
(e.g. De Ligt's fee vs. everything Bayern spent that window), not just
its spending on Eredivisie players. The club list comes from
list_buyer_clubs.py (ranking) filtered to >= EUR10M and verified
(see the 2026-10-03 entry in docs/patch_list.md): 69 clubs.

Reuses extract_transfermarkt_transfer_history.py's row parser, fee parser,
and headers unchanged, so rows come out in exactly the format already
loaded for the 29 Eredivisie clubs. What this adds on top of
scrape_all_eredivisie_clubs.py:

  - FAILURE GUARDS. extract_all_transfers() turns a blocked/challenge
    page into an empty list that looks like a success. Here a 200
    response that parses to ZERO transfers is a failure, never saved --
    the same "empty result mistaken for a clean one" shape as the empty
    keeper table found earlier in this project.
  - A 403/405 fails immediately with a pointer to the fallback (retrying
    a block is pointless); 429/5xx and network errors retry with backoff.
  - Resume-safe: a club whose JSON already exists is skipped unless
    --force, so a crash partway through doesn't redo finished clubs.
  - --only, to run one club first.

UNTESTED AGAINST THE LIVE SITE as of writing -- Transfermarkt blocked the
environment this was written in. The parsing, retry, and failure-guard
logic is unit-tested offline against synthetic pages; whether Transfermarkt
actually serves these pages to plain requests is the one thing only a real
run can show. RUN THIS FIRST, on one club:

    python pipelines/transfermarkt/scrape_buyer_clubs.py --only 985

(985 = Manchester United, the largest buyer.) Check the logged page title,
the row count, the in/out split, and the season range before running the
other 68. If it reports HTTP 403/405, plain requests is blocked for these
pages the way it is for player-profile pages (see scrape_player_bio.py);
the fallback is SeleniumBase UC mode, same as that script.

URL SLUGS: Transfermarkt URLs are /{slug}/alletransfers/verein/{id}. This
uses '-' as the slug unless the input CSV has an optional 'slug' column,
the same placeholder scrape_player_bio.py uses for player pages. That
Transfermarkt resolves a placeholder slug for CLUB pages is assumed from
the player-page behaviour, not confirmed -- if the first club comes back
as a failure or the wrong club (check the logged page title), add a
'slug' column to the CSV and rerun.

DIRECTION comes from each table's own 'Arrivals'/'Departures' heading,
not its position. The position rule this script originally inherited from
the extractor was wrong: one season with a single table shifted every table
below it, inverting direction for the whole rest of the page (7 of 69 buyer
pages, including Chelsea, Inter, Atalanta, Benfica, Arsenal and Atletico).
A club whose tables can't be given a trustworthy direction fails instead of
being saved. For a buyer club direction='in' IS the spend, so after loading,
run schema/transfermarkt/buyer_club_transfers_checks.sql: check 2 uses the
Eredivisie side's own 'out' rows as independent ground truth, and should
show 0 found_only_as_out_direction_flipped.
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from extract_transfermarkt_transfer_history import (
    HEADERS,
    RELEVANT_FROM_SEASON,
    DirectionError,
    parse_transfer_page_html,
    require_resolved_directions,
    save_to_json,
)

URL_TEMPLATE = "https://www.transfermarkt.com/{slug}/alletransfers/verein/{club_id}"
DEFAULT_INPUT = Path("data_audit/results/buyer_clubs_to_scrape.csv")
OUT_DIR = Path("data/transfermarkt/buyers")

DELAY_BETWEEN_CLUBS_SECONDS = 3   # same politeness delay as scrape_all_eredivisie_clubs.py
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [5, 15, 45]     # waits after attempt 1, 2 (3 is the last)


class ScrapeError(Exception):
    """A club that must be reported as failed, never saved as empty."""


def build_url(club_id, slug=None):
    return URL_TEMPLATE.format(slug=slug or "-", club_id=club_id)


def read_club_list(path):
    """Reads the scrape-target CSV. Needs counterparty_club_id and
    counterparty_club_name; 'slug' is optional."""
    clubs = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw_id = (row.get("counterparty_club_id") or "").strip()
            if not raw_id:
                continue
            clubs.append({
                "club_id": int(raw_id),
                "name": (row.get("counterparty_club_name") or "").strip(),
                "slug": (row.get("slug") or "").strip() or None,
            })
    return clubs


def fetch_html(url):
    """GET with failure handling. 403/405 = blocked: fail at once (retrying
    a block is pointless). 429/5xx/network errors: retry with backoff."""
    last_problem = "no attempt made"
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            last_problem = f"{type(e).__name__}: {e}"
        else:
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 405):
                raise ScrapeError(
                    f"HTTP {resp.status_code} (blocked) for {url} -- plain requests is "
                    f"being rejected for this page; see the fallback note in this "
                    f"script's docstring (SeleniumBase UC mode, as in scrape_player_bio.py)"
                )
            last_problem = f"HTTP {resp.status_code}"
        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(BACKOFF_SECONDS[attempt])
    raise ScrapeError(f"gave up after {MAX_ATTEMPTS} attempts: {last_problem}")


def page_title(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.title.get_text(strip=True) if soup.title else "(no <title>)"


def parse_transfer_page(html):
    """Pure function: page HTML -> (transfers, info). Direction for every
    table comes from its own 'Arrivals'/'Departures' heading, never from its
    position (see extract_transfermarkt_transfer_history.py for why). info
    lists unresolved tables and where the old position rule would have been
    wrong."""
    return parse_transfer_page_html(html)


def summarize(transfers):
    seasons = [t["season_id"] for t in transfers if t["season_id"] is not None]
    return {
        "rows": len(transfers),
        "in": sum(1 for t in transfers if t["direction"] == "in"),
        "out": sum(1 for t in transfers if t["direction"] == "out"),
        "first_season": min(seasons) if seasons else None,
        "last_season": max(seasons) if seasons else None,
        "unrecognized_fees": sum(1 for t in transfers if t["fee"]["type"].startswith("unrecognized")),
        "no_season": sum(1 for t in transfers if t["season_id"] is None),
    }


def scrape_club(club_id, slug=None):
    """Fetches and parses one club. Returns (url, title, transfers, info).
    Raises ScrapeError rather than ever returning an empty or
    direction-uncertain result."""
    url = build_url(club_id, slug)
    html = fetch_html(url)
    title = page_title(html)
    transfers, info = parse_transfer_page(html)
    try:
        require_resolved_directions(info)
    except DirectionError as e:
        raise ScrapeError(f"{e} (page title: {title!r}) -- NOT saved")
    if not transfers:
        raise ScrapeError(
            f"HTTP 200 but 0 transfers parsed (page title: {title!r}) -- a bot-"
            f"challenge page, a wrong/placeholder-slug redirect, or a layout change; "
            f"NOT saved as an empty success"
        )
    return url, title, transfers, info


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help=f"scrape-target CSV (default {DEFAULT_INPUT})")
    parser.add_argument("--only", type=int, nargs="+", metavar="CLUB_ID",
                        help="scrape only these club ids (run '--only 985' first)")
    parser.add_argument("--force", action="store_true",
                        help="re-scrape clubs whose JSON already exists")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"Input file not found: {args.input}\n"
                 f"Generate it with: python pipelines/transfermarkt/select_buyer_clubs.py "
                 f"(reads data_audit/results/buyer_clubs_ranked.csv, written by "
                 f"list_buyer_clubs.py), or pass --input <path>.")
    clubs = read_club_list(args.input)
    if args.only:
        wanted = set(args.only)
        clubs = [c for c in clubs if c["club_id"] in wanted]
        missing = wanted - {c["club_id"] for c in clubs}
        if missing:
            print(f"WARNING: not in {args.input}: {sorted(missing)}")
    print(f"{len(clubs)} club(s) to consider from {args.input}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done, skipped, failures = [], [], []

    for i, club in enumerate(clubs, start=1):
        club_id, name = club["club_id"], club["name"]
        out_path = OUT_DIR / f"{club_id}_transfers.json"
        print(f"\n[{i}/{len(clubs)}] {name} (id={club_id})")

        if out_path.exists() and not args.force:
            print(f"  already scraped ({out_path.name}) -- skipping (--force to redo)")
            skipped.append(club_id)
            continue

        try:
            url, title, transfers, info = scrape_club(club_id, club["slug"])
        except ScrapeError as e:
            print(f"  FAILED: {e}")
            failures.append((club_id, name, str(e)))
            continue

        s = summarize(transfers)
        print(f"  page title: {title}")
        print(f"  {s['rows']} rows ({s['in']} in / {s['out']} out), "
              f"seasons {s['first_season']}-{s['last_season']}, "
              f"{s['unrecognized_fees']} unrecognized fee format(s), "
              f"{s['no_season']} with no season")
        if info["parity_wrong_tables"]:
            print(f"  direction fixed: the old position rule would have mislabeled "
                  f"{info['parity_wrong_tables']} table(s) ({info['parity_wrong_rows_relevant']} rows "
                  f"from {RELEVANT_FROM_SEASON} on), first at table {info['first_parity_wrong_index']}")
        if info["unresolved"]:
            print(f"  skipped {len(info['unresolved'])} table(s) with no usable direction "
                  f"(none hold rows from {RELEVANT_FROM_SEASON} on)")
        save_to_json(transfers, out_path)
        done.append(club_id)

        if i < len(clubs):
            time.sleep(DELAY_BETWEEN_CLUBS_SECONDS)

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    print(f"Scraped: {len(done)}   Skipped (already done): {len(skipped)}   Failed: {len(failures)}")
    for club_id, name, why in failures:
        print(f"  FAILED {name} ({club_id}): {why}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
