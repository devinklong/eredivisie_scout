"""
Custom scraper for FBref stat categories soccerdata doesn't support:
passing, possession, defense, goal_shot_creation. League-level pages,
player-level tables (not squad-aggregate tables).

Confirmed via diagnostic: the player-level table on each page has a
predictable id ("stats_passing", etc.) and is wrapped inside an HTML
comment. The squad-aggregate tables on the same page are NOT
comment-wrapped and have different ids (e.g. "stats_squads_passing_for")
-- we deliberately target the player-level table by id, not by the
fragile class-string matching our first attempt used.
"""

import time

from bs4 import BeautifulSoup, Comment
from seleniumbase import SB

STAT_PAGES = {
    "passing": ("https://fbref.com/en/comps/23/passing/Eredivisie-Stats", "stats_passing"),
    "possession": ("https://fbref.com/en/comps/23/possession/Eredivisie-Stats", "stats_possession"),
    "defense": ("https://fbref.com/en/comps/23/defense/Eredivisie-Stats", "stats_defense"),
    "goal_shot_creation": ("https://fbref.com/en/comps/23/gca/Eredivisie-Stats", "stats_gca"),
    # Prior-season comparison: if last season's (fully completed) Eredivisie
    # passing table is populated for a real starter, that confirms this
    # season's blanks are a data-publishing lag, not a scraper bug.
    "passing_prior_season_comparison": (
        "https://fbref.com/en/comps/23/2025-2026/passing/2025-2026-Eredivisie-Stats",
        "stats_passing",
    ),
}


def find_table_by_id(soup: BeautifulSoup, table_id: str):
    """Search for a <table> with the given id, first directly in the
    HTML, then inside HTML comments (FBref hides several tables that
    way)."""
    table = soup.find("table", id=table_id)
    if table is not None:
        return table, "direct"

    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for comment in comments:
        if table_id in comment:
            comment_soup = BeautifulSoup(comment, "html.parser")
            possible_table = comment_soup.find("table", id=table_id)
            if possible_table is not None:
                return possible_table, "comment"

    return None, None


def scrape_stat_page(sb, stat_name: str, url: str, table_id: str):
    print(f"\n{'=' * 60}")
    print(f"Scraping: {stat_name} ({url}), target table id='{table_id}'")
    print("=" * 60)

    sb.uc_open_with_reconnect(url, reconnect_time=8)
    html = sb.get_page_source()
    soup = BeautifulSoup(html, "html.parser")

    table_tag, source = find_table_by_id(soup, table_id)

    if table_tag is None:
        print(f"  Table id='{table_id}' not found -- id may differ on this "
              f"page, verify with the diagnostic script.")
        return None

    tbody = table_tag.find("tbody")
    if tbody is None:
        print("  Table found, but no <tbody>.")
        return None

    rows = tbody.find_all("tr")
    print(f"  Row count: {len(rows)} (source: {source})")

    if not rows:
        return None

    # Row 0 is often a fringe player with minimal minutes (tables tend to
    # sort alphabetically or by minutes ascending) -- pick the first row
    # with meaningful minutes_90s instead, so we're inspecting a real
    # regular starter's data, not a mostly-blank row.
    target_row = rows[0]
    for row in rows:
        cells = row.find_all(["th", "td"])
        row_data = {cell.get("data-stat"): cell.get_text(strip=True) for cell in cells}
        try:
            if float(row_data.get("minutes_90s", 0)) >= 3.0:
                target_row = row
                break
        except (TypeError, ValueError):
            continue

    labeled = {
        cell.get("data-stat", f"unknown_col_{i}"): cell.get_text(strip=True)
        for i, cell in enumerate(target_row.find_all(["th", "td"]))
    }
    print(f"  Column count: {len(labeled)}")
    print(f"  Row with real minutes (labeled):")
    for key, value in labeled.items():
        print(f"    {key}: {value!r}")

    return table_tag


def main():
    with SB(uc=True, test=True) as sb:
        for stat_name, (url, table_id) in STAT_PAGES.items():
            scrape_stat_page(sb, stat_name, url, table_id)
            time.sleep(3)  # be polite between requests


if __name__ == "__main__":
    main()
