"""
Inspects real row content (not just headers) of the three Transfermarkt
tables identified as relevant: the squad table (market value per player)
and the two transfer-fee tables (arrivals/departures with real fees).
Checks each <td>'s class/attributes too, since Transfermarkt may not use
a clean data-stat convention the way FBref did -- need to see what's
actually there before writing real parsing logic.
"""

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


def inspect_table_rows(table, label, max_rows=5):
    print(f"\n{'=' * 60}")
    print(f"{label}")
    print("=" * 60)

    rows = table.find_all("tr")
    for i, row in enumerate(rows[:max_rows]):
        cells = row.find_all(["th", "td"])
        print(f"\n-- Row {i} ({len(cells)} cells) --")
        for cell in cells:
            classes = cell.get("class")
            text = cell.get_text(strip=True)
            # Also check for an <a> tag inside, since player names are
            # often links -- worth knowing if the player ID is embedded
            # in the href, useful for entity resolution later.
            link = cell.find("a")
            href = link.get("href") if link else None
            print(f"  class={classes} text={text!r} href={href}")


def main():
    response = requests.get(URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    inspect_table_rows(tables[1], "Table 1 -- squad (items)", max_rows=3)
    inspect_table_rows(tables[29], "Table 29 -- transfers (startseite) #1", max_rows=3)
    inspect_table_rows(tables[30], "Table 30 -- transfers (startseite) #2", max_rows=3)
    inspect_table_rows(tables[34], "Table 34 -- arrivals/departures", max_rows=3)


if __name__ == "__main__":
    main()
