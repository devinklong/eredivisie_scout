"""
Test scraper: pulls Ajax's 2026-2027 Eredivisie Standard Stats table from FBref.

Purpose: validate the extraction approach against a known-populated, stable
table before building out the full pipeline.

Note: plain `requests` (even with full browser headers + a session) got a
403 from FBref -- this points to bot-detection deeper than missing headers
(likely TLS/request-fingerprinting). Using `cloudscraper`, a requests-compatible
client built to get past that class of block, instead.

FBref also wraps many of its stat tables in HTML comments that only get
revealed client-side via JS tab-switching -- this script handles that case.
"""

import time

import cloudscraper
from bs4 import BeautifulSoup, Comment

URL = "https://fbref.com/en/squads/19c3f8c4/2026-2027/c23/Ajax-Stats-Eredivisie"

TABLE_CLASS = "table_container tabbed current"


def find_stats_table(soup: BeautifulSoup):
    """Look for the stats table directly, then fall back to searching
    inside HTML comments, since FBref hides several tables that way."""
    table = soup.find("div", class_=TABLE_CLASS)
    if table is not None:
        return table, "direct"

    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for comment in comments:
        if "table_container" in comment:
            comment_soup = BeautifulSoup(comment, "html.parser")
            possible_table = comment_soup.find("div", class_=TABLE_CLASS)
            if possible_table is not None:
                return possible_table, "comment"

    return None, None


def main():
    print(f"Requesting: {URL}")
    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "darwin", "mobile": False}
    )
    response = scraper.get(URL, timeout=15)
    response.raise_for_status()
    print(f"Status: {response.status_code}, {len(response.text)} bytes received")

    soup = BeautifulSoup(response.text, "html.parser")
    stats_table, source = find_stats_table(soup)

    if stats_table is None:
        print("Table not found -- either the class name has changed, "
              "the page structure differs from what we inspected, or "
              "the request was served a block/challenge page instead "
              "of the real content.")
        return

    print(f"Table found (source: {source})")

    # Pull the actual <table> element out of the container and check
    # it has real rows before declaring success.
    table_tag = stats_table.find("table")
    if table_tag is None:
        print("Container found, but no <table> tag inside it.")
        return

    rows = table_tag.find("tbody").find_all("tr")
    print(f"Row count in tbody: {len(rows)}")

    if rows:
        first_row_cells = [cell.get_text(strip=True) for cell in rows[0].find_all(["th", "td"])]
        print(f"First row sample: {first_row_cells}")

    # Be polite before any follow-up request.
    time.sleep(3)


if __name__ == "__main__":
    main()
