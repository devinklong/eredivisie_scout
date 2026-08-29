"""
Inspects real row content of the club transfer-history page's tables
(163 season-grouped 'Players/Club/Transfer sum' tables, confirmed via
test_transfermarkt_history_page.py) -- checks whether the nested cell
structure matches what was already decoded on the squad page
(inspect_transfermarkt_rows.py: 'foto'/'td'/'wappen' cell classes,
player IDs embedded in href), or whether this page type has a genuinely
different structure that needs its own parsing logic.
"""

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


def inspect_transfer_history_table(table, label, max_rows=4):
    print(f"\n{'=' * 60}")
    print(f"{label}")
    print("=" * 60)

    transfer_rows = table.find_all("tr")
    for i, row in enumerate(transfer_rows[:max_rows]):
        cells = row.find_all(["th", "td"])
        print(f"\n-- Transfer row {i} ({len(cells)} cells) --")
        for cell in cells:
            classes = cell.get("class")
            text = cell.get_text(strip=True)
            link = cell.find("a")
            href = link.get("href") if link else None
            print(f"  class={classes} text={text!r} href={href}")


def main():
    response = requests.get(URL, headers=HEADERS, timeout=15)
    soup = BeautifulSoup(response.text, "html.parser")
    tables = soup.find_all("table")

    # Inspect just the first two season tables -- enough to confirm
    # (or rule out) the pattern without dumping all 163.
    inspect_transfer_history_table(tables[0], "Transfer history -- Table 0 (first season group)")
    inspect_transfer_history_table(tables[1], "Transfer history -- Table 1 (second season group)")


if __name__ == "__main__":
    main()
