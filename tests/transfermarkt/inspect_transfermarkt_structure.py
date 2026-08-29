"""
Inspects the real structure of a Transfermarkt squad page -- finds every
table on the page, prints its class/id and column headers, so we know
where the actual squad/market-value data lives before writing real
extraction logic. Same "confirm structure before building" discipline
used for FBref's data-stat discovery.
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


def main():
    response = requests.get(URL, headers=HEADERS, timeout=15)
    print(f"Status: {response.status_code}, {len(response.text)} characters\n")

    soup = BeautifulSoup(response.text, "html.parser")

    tables = soup.find_all("table")
    print(f"Total <table> elements found: {len(tables)}\n")

    for i, table in enumerate(tables):
        classes = table.get("class")
        table_id = table.get("id")
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        row_count = len(table.find_all("tr"))

        print(f"--- Table {i} ---")
        print(f"  class: {classes}")
        print(f"  id: {table_id}")
        print(f"  row count: {row_count}")
        print(f"  headers found: {headers[:15]}")  # cap in case a table has many columns
        print()

    # Also check specifically for common Transfermarkt container class names,
    # in case the real squad table is nested inside a named div rather than
    # being identifiable by its own class alone.
    print("--- Divs with 'items' or 'table' in class (common Transfermarkt naming) ---")
    candidates = soup.find_all("div", class_=lambda c: c and ("items" in c or "table" in c.lower()))
    for div in candidates[:10]:
        print(f"  class={div.get('class')}, id={div.get('id')}")


if __name__ == "__main__":
    main()
