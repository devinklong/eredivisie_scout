"""
Extracts Ajax's real squad (Table 1, class="items") and recent transfers
(Tables 29/30, class="startseite") from Transfermarkt, based on the real
row structure confirmed via tests/transfermarkt/inspect_transfermarkt_rows.py.

Squad row structure (8 cells, confirmed from a real row):
  0: shirt number (class zentriert + position-color bg class)
  1: 'posrela' -- photo cell, combined name+position text (redundant with cell 3+4)
  2: empty
  3: 'hauptlink' -- the real player name + profile link (/player-slug/profil/spieler/{id})
  4: position, as plain text
  5: 'zentriert' -- date of birth + age, e.g. "30/04/1992 (34)"
  6: empty (nationality flag image, no text)
  7: 'rechts hauptlink' -- market value text + link to value-history page

Some rows only have 2 cells (a secondary/duplicate row Transfermarkt
inserts under some players) -- these are skipped, not parsed, since they
don't carry the full row shape.

Transfer-table row structure (4 cells, confirmed from real rows):
  0: 'foto' -- player photo, link has the same /spieler/{id} pattern
  1: 'td' -- combined "NamePosition" text, no separator
  2: 'wappen' -- destination/origin club crest, link has club slug + verein id
  3: 'rechts' -- fee text: either "€X.XXm" or a string like "loan transfer"

NOTE: cell 1 in the transfer tables has NO separator between name and
position (e.g. "Marcos LeonardoCentre-Forward") -- can't cleanly split
this into name/position without a known list of valid position strings
to match against. Left as one raw field (name_position) for now rather
than guessing a wrong split.
"""

import re

import requests
from bs4 import BeautifulSoup

URL = "https://www.transfermarkt.com/ajax-amsterdam/startseite/verein/610"

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


def parse_market_value(text):
    """'€3.00m' -> 3.00 (millions). '€500k' -> 0.5. Returns None if it
    doesn't parse (e.g. '-')."""
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
    """Transfer fee is usually the same €X.XXm format as market value,
    but can also be a descriptive string ('loan transfer', 'free
    transfer', '-'). Returns a numeric value in millions when possible,
    otherwise returns the raw text so nothing gets silently dropped."""
    numeric = parse_market_value(text)
    if numeric is not None:
        return numeric
    return text.strip() if text else None


def extract_squad(table):
    players = []
    rows = table.find_all("tr")[1:]  # skip header row

    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 8:
            # Secondary/duplicate rows (2 cells) -- not the real data row, skip.
            continue

        name_link = cells[3].find("a")
        name = name_link.get_text(strip=True) if name_link else None
        player_id = extract_player_id(name_link.get("href") if name_link else None)

        position = cells[4].get_text(strip=True)
        dob_age_text = cells[5].get_text(strip=True)
        market_value_text = cells[7].get_text(strip=True)

        players.append({
            "player_id": player_id,
            "name": name,
            "position": position,
            "dob_age_raw": dob_age_text,  # e.g. "30/04/1992 (34)" -- split later
            "market_value_eur_millions": parse_market_value(market_value_text),
        })

    return players


def extract_transfers(table, direction):
    """direction: 'in' or 'out' -- caller knows which table is which,
    since the HTML itself doesn't label this distinctly enough to infer
    automatically (both tables share the same class/header text)."""
    transfers = []
    rows = table.find_all("tr")[1:]  # skip header row

    for row in rows:
        cells = row.find_all(["th", "td"])
        if len(cells) < 4:
            continue

        name_position_cell = cells[1]
        name_link = name_position_cell.find("a")
        name_position_text = name_position_cell.get_text(strip=True)
        player_id = extract_player_id(name_link.get("href") if name_link else None)

        club_link = cells[2].find("a")
        club_id = extract_club_id(club_link.get("href") if club_link else None)

        fee_text = cells[3].get_text(strip=True)

        transfers.append({
            "player_id": player_id,
            "name_position_raw": name_position_text,  # not split -- see docstring
            "counterparty_club_id": club_id,
            "direction": direction,
            "fee": parse_fee(fee_text),
        })

    return transfers


def main():
    response = requests.get(URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    squad = extract_squad(tables[1])
    print(f"Extracted {len(squad)} squad players")
    for p in squad[:5]:
        print(f"  {p}")

    # NOTE: which of tables[29]/tables[30] is "arrivals" vs "departures"
    # was not confirmed by position alone in the inspection output --
    # both had the same header text. Verify manually against the live
    # page before trusting the 'in'/'out' labels below.
    transfers_out = extract_transfers(tables[29], direction="out")
    transfers_in = extract_transfers(tables[30], direction="in")

    print(f"\nExtracted {len(transfers_out)} outgoing transfers")
    for t in transfers_out:
        print(f"  {t}")

    print(f"\nExtracted {len(transfers_in)} incoming transfers")
    for t in transfers_in:
        print(f"  {t}")


if __name__ == "__main__":
    main()
