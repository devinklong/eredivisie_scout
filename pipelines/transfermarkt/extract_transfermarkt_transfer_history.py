"""
Extracts a club's full multi-season transfer history from Transfermarkt
(the 163-table 'alletransfers' page, confirmed via
inspect_transfermarkt_transfer_history_rows.py -- NOT the same page or
cell structure as the squad-page transfer widget in
extract_transfermarkt_squad.py).

Transfer-history row structure (4 cells, confirmed from real rows):
  0: 'hauptlink' -- player name + profile link (/player-slug/profil/spieler/{id})
  1: 'no-border-rechts zentriert' -- club crest image only, no text; href
     has the counterparty club's slug + verein id + season
  2: 'no-border-links' -- counterparty club NAME as text, same href as cell 1
  3: 'rechts' -- fee text, same €X.XXm / descriptive-string format as the
     squad page's transfer widget

DIRECTION comes from each table's own heading, NOT from its position
(changed 2026-10-05). Every table sits under a heading like "Arrivals
26/27" or "Departures 27/28". This module previously assumed even-indexed
tables were incoming and odd-indexed outgoing, an assumption its own
docstring called unconfirmed. It was wrong: a season that has only ONE
table (an announced future departure with no arrivals yet, or a window
with no arrivals) shifts every table below it by one, so the whole rest of
the page is labeled backwards. Found when buyer_club_transfers_checks.sql
check 2 showed 22 of 238 paid Eredivisie sales labeled backwards, all at 7
clubs (Atalanta, Benfica, Chelsea, Atletico, Inter, Arsenal, Anzhi), none
labeled correctly at those clubs, then confirmed on the real pages with
inspect_transfer_tables.py. The table header row ('Players', 'Club',
'Transfer sum') is identical on every table and cannot be used.

A table whose direction cannot be established from the page (no Arrivals/
Departures heading, a heading already used by another table, or a heading
whose season disagrees with its own rows) is left out and reported. If it
holds transfers from RELEVANT_FROM_SEASON on, extract_all_transfers raises
DirectionError instead of guessing. It never falls back to position.

parse_market_value / parse_fee / extract_player_id / extract_club_id
duplicated from extract_transfermarkt_squad.py rather than shared via
a common module -- flagged as a TODO refactor (pull into a
transfermarkt_utils.py) once both scripts are stable, not worth the
churn mid-exploration.
"""

import argparse
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://www.transfermarkt.com/psv-eindhoven/alletransfers/verein/383"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

PLAYER_ID_PATTERN = re.compile(r"/spieler/(\d+)")
CLUB_ID_PATTERN = re.compile(r"/verein/(\d+)")
SEASON_ID_PATTERN = re.compile(r"/saison_id/(\d+)")


def extract_player_id(href):
    if not href:
        return None
    match = PLAYER_ID_PATTERN.search(href)
    return int(match.group(1)) if match else None


def extract_club_id(href):
    if not href:
        return None
    match = CLUB_ID_PATTERN.search(href)
    return int(match.group(1)) if match else None


def extract_season_id(href):
    if not href:
        return None
    match = SEASON_ID_PATTERN.search(href)
    return int(match.group(1)) if match else None


def parse_market_value(text):
    if not text:
        return None
    text = text.replace("€", "").strip()
    if text.endswith("m"):
        try:
            return float(text[:-1])
        except ValueError:
            return None
    if text.endswith("k"):
        try:
            return float(text[:-1]) / 1000
        except ValueError:
            return None
    return None


def parse_fee(text):
    if not text:
        # Confirmed real, rare case (6/1380 rows in a full PSV extraction,
        # 2026-08-29): the fee <td> is genuinely empty, not '?' or '-'.
        # All observed instances so far are pre-1991. Distinct label so
        # this doesn't silently collapse into a bare None type.
        return {"amount": None, "type": "empty_cell"}
    stripped = text.strip()

    if stripped == "-":
        return {"amount": None, "type": "unknown"}
    if stripped == "?":
        # Confirmed via a full 1380-row extraction (PSV, 2026-08-29):
        # Transfermarkt's own explicit "we don't have this fee on
        # record" marker, overwhelmingly on transfers from the 1950s-
        # 1990s. Not a parsing failure -- a deliberate, honest gap in
        # their own historical data. Distinct from '-', which appears
        # to be used differently (worth confirming that distinction
        # further if it ever matters for the model).
        return {"amount": None, "type": "unknown_historical"}
    if stripped.lower() == "end of loan":
        # A loaned player returning to their parent club -- no new fee,
        # and distinct from unpaid_loan (that's a loan *starting*, this
        # is one *ending*). Real, common case, not an error.
        return {"amount": None, "type": "loan_ended"}
    if stripped.lower() == "free transfer":
        return {"amount": 0.0, "type": "free_transfer"}
    if stripped.lower() == "loan transfer":
        return {"amount": None, "type": "unpaid_loan"}
    if stripped.lower().startswith("loan fee"):
        amount = parse_market_value(stripped.replace("Loan fee", "").strip())
        if amount is not None:
            return {"amount": amount, "type": "paid_loan"}
        return {"amount": None, "type": "paid_loan_undisclosed"}

    amount = parse_market_value(stripped)
    if amount is not None:
        return {"amount": amount, "type": "permanent_transfer"}
    return {"amount": None, "type": f"unrecognized: {stripped!r}"}


def is_internal_promotion(club_name):
    """Flags counterparty clubs that are actually the same organization's
    own youth/reserve team (e.g. 'PSV U21'), not a real external
    transfer. Confirmed real case: 3 rows in PSV's own transfer history
    list 'PSV U21' as the counterparty. Checked as a simple suffix match
    -- may need extending if other clubs use a different youth-team
    naming convention (not yet checked against other clubs)."""
    if not club_name:
        return False
    return bool(re.search(r"\b(U1[6-9]|U2[0-3])\b", club_name))


def extract_transfer_table(table, direction):
    transfers = []
    rows = table.find_all("tr")[1:]  # skip header row

    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 4:
            continue

        name_link = cells[0].find("a")
        name = name_link.get_text(strip=True) if name_link else None
        player_id = extract_player_id(name_link.get("href") if name_link else None)

        club_link = cells[2].find("a") or cells[1].find("a")
        club_href = club_link.get("href") if club_link else None
        club_name = cells[2].get_text(strip=True)
        club_id = extract_club_id(club_href)
        season_id = extract_season_id(club_href)

        fee_text = cells[3].get_text(strip=True)

        transfers.append({
            "player_id": player_id,
            "name": name,
            "direction": direction,
            "counterparty_club_id": club_id,
            "counterparty_club_name": club_name,
            "season_id": season_id,
            "fee": parse_fee(fee_text),
            "is_internal_promotion": is_internal_promotion(club_name),
        })

    return transfers


# Transfers before this season are dropped downstream (see
# pipelines/transfermarkt/load_buyer_club_transfers.py MIN_SEASON). A table
# whose direction can't be established only blocks a scrape if it holds rows
# from this season on. Old, undated clutter does not.
RELEVANT_FROM_SEASON = 2000

_HEADING_TAG = re.compile(r"^h[1-6]$")
_DIRECTION_HEADING = re.compile(r"^\s*(Arrivals|Departures)\b", re.IGNORECASE)
_HEADING_SEASON = re.compile(r"(\d{2})\s*/\s*(\d{2})")


class DirectionError(Exception):
    """A table holding relevant transfers has no trustworthy direction."""


def heading_direction(text):
    """'Arrivals 26/27' -> 'in', 'Departures 27/28' -> 'out', anything else
    (including None) -> None."""
    m = _DIRECTION_HEADING.match(text or "")
    if not m:
        return None
    return "in" if m.group(1).lower() == "arrivals" else "out"


def heading_start_yy(text):
    """'Arrivals 26/27' -> 26 (the season's start year, last two digits), or
    None. Century-agnostic on purpose: compared with season_id % 100."""
    m = _HEADING_SEASON.search(text or "")
    return int(m.group(1)) if m else None


def parse_transfer_page_html(html):
    """Pure function: page HTML -> (transfers, info).

    Direction for every table comes from its own Arrivals/Departures heading.
    Tables that can't be resolved are excluded from `transfers` and listed in
    info["unresolved"]. info also records where the OLD position rule would
    have been wrong, so each scrape can show what the fix changed."""
    soup = BeautifulSoup(html, "html.parser")
    transfers = []
    unresolved = []
    parity_wrong = []
    claimed = {}  # heading element -> index of the first table that used it

    tables = soup.find_all("table")
    for i, table in enumerate(tables):
        heading_tag = table.find_previous(_HEADING_TAG)
        heading = heading_tag.get_text(" ", strip=True) if heading_tag is not None else None
        direction = heading_direction(heading)
        parity = "in" if i % 2 == 0 else "out"

        problem = None
        if direction is None:
            problem = "no Arrivals/Departures heading above this table"
        elif id(heading_tag) in claimed:
            problem = f"heading {heading!r} already used by table {claimed[id(heading_tag)]}"
        else:
            claimed[id(heading_tag)] = i

        rows = extract_transfer_table(table, direction or parity)

        if problem is None:
            yy = heading_start_yy(heading)
            if yy is not None:
                bad = sorted({r["season_id"] for r in rows
                              if r["season_id"] is not None and r["season_id"] % 100 != yy})
                if bad:
                    problem = f"heading season {yy:02d} but rows are from season(s) {bad}"

        relevant = sum(1 for r in rows
                       if r["season_id"] is not None and r["season_id"] >= RELEVANT_FROM_SEASON)
        if problem:
            unresolved.append({"index": i, "heading": heading, "problem": problem,
                               "rows": len(rows), "rows_relevant": relevant})
            continue
        if direction != parity:
            parity_wrong.append({"index": i, "heading": heading,
                                 "rows": len(rows), "rows_relevant": relevant})
        transfers.extend(rows)

    info = {
        "tables": len(tables),
        "unresolved": unresolved,
        "parity_wrong_tables": len(parity_wrong),
        "parity_wrong_rows_relevant": sum(t["rows_relevant"] for t in parity_wrong),
        "first_parity_wrong_index": parity_wrong[0]["index"] if parity_wrong else None,
    }
    return transfers, info


def require_resolved_directions(info):
    """Raises DirectionError if any unresolved table holds transfers from
    RELEVANT_FROM_SEASON on. Those rows would silently vanish or be
    mislabeled, so the scrape must fail instead."""
    blocking = [u for u in info["unresolved"] if u["rows_relevant"] > 0]
    if blocking:
        first = blocking[0]
        raise DirectionError(
            f"{len(blocking)} table(s) holding transfers from {RELEVANT_FROM_SEASON} on have no "
            f"trustworthy direction; first: table {first['index']} ({first['heading']!r}): "
            f"{first['problem']}"
        )


def extract_all_transfers(url=URL):
    """Fetches and parses a club's full transfer-history page. Returns
    the list of transfer dicts -- callable directly by other pipeline
    code, not just as a script."""
    response = requests.get(url, headers=HEADERS, timeout=15)
    all_transfers, info = parse_transfer_page_html(response.text)
    require_resolved_directions(info)
    return all_transfers


def print_summary(all_transfers):
    print(f"Total transfers extracted: {len(all_transfers)}")
    print(f"Incoming: {sum(1 for t in all_transfers if t['direction'] == 'in')}")
    print(f"Outgoing: {sum(1 for t in all_transfers if t['direction'] == 'out')}")
    print(f"Internal promotions (not real transfers, e.g. youth-team): "
          f"{sum(1 for t in all_transfers if t['is_internal_promotion'])}")


def print_unresolved_fees(all_transfers):
    """Diagnostic only -- lists every transfer whose fee didn't resolve
    to a known category, for manually checking against a new club's
    page when its fee formats haven't been seen before. Every category
    seen in PSV's real 1380-transfer history (2026-08-29) is already
    handled by parse_fee(); this exists for when a *different* club
    surfaces something new."""
    unresolved = [t for t in all_transfers
                  if t["fee"]["type"].startswith("unrecognized")]
    print(f"\n--- Fees with an unrecognized format ({len(unresolved)}) ---")
    for t in unresolved:
        print(f"  {t['name']} ({t['direction']}, season {t['season_id']}): {t['fee']}")


def save_to_json(all_transfers, path):
    """Dumps the raw extracted transfer list to a JSON file. This is a
    disposable staging checkpoint, NOT the pipeline's real destination
    (that's Postgres, per the project's Python -> Postgres -> ... stack).
    Useful when scraping many clubs in one run, so a failure partway
    through doesn't force re-scraping clubs already done -- each club's
    raw result can be dumped and re-loaded independently. Lives under
    data/, which is already .gitignored."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_transfers, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(all_transfers)} transfers to {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL)
    parser.add_argument("--debug", action="store_true",
                         help="Print unrecognized-fee diagnostics.")
    parser.add_argument("--output", default=None,
                         help="If set, dump raw results to this JSON path "
                              "(e.g. data/transfermarkt/psv_transfers.json).")
    args = parser.parse_args()

    all_transfers = extract_all_transfers(args.url)
    print_summary(all_transfers)

    if args.debug:
        print_unresolved_fees(all_transfers)

    if args.output:
        save_to_json(all_transfers, args.output)

    return all_transfers


if __name__ == "__main__":
    main()
