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

Pattern observed (NOT yet confirmed across all 163 tables, only the
first 2): even-indexed tables (0, 2, 4...) are incoming transfers,
odd-indexed (1, 3, 5...) are outgoing -- i.e. each season contributes a
pair of tables. Worth spot-checking a few more pairs before trusting
this holds for the entire page, especially older seasons where a
transfer window might have zero movement in one direction.

parse_market_value / parse_fee / extract_player_id / extract_club_id
duplicated from extract_transfermarkt_squad.py rather than shared via
a common module -- flagged as a TODO refactor (pull into a
transfermarkt_utils.py) once both scripts are stable, not worth the
churn mid-exploration.
"""

import argparse
import re

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


def extract_all_transfers(url=URL):
    """Fetches and parses a club's full transfer-history page. Returns
    the list of transfer dicts -- callable directly by other pipeline
    code, not just as a script."""
    response = requests.get(url, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    all_transfers = []
    for i, table in enumerate(tables):
        # Pattern per module docstring: even index = incoming, odd =
        # outgoing. NOT fully confirmed across all 163 -- flagged, not
        # assumed safe.
        direction = "in" if i % 2 == 0 else "out"
        all_transfers.extend(extract_transfer_table(table, direction))

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=URL)
    parser.add_argument("--debug", action="store_true",
                         help="Print unrecognized-fee diagnostics.")
    args = parser.parse_args()

    all_transfers = extract_all_transfers(args.url)
    print_summary(all_transfers)

    if args.debug:
        print_unresolved_fees(all_transfers)

    return all_transfers


if __name__ == "__main__":
    main()
