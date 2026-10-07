"""
Diagnostic: shows how one Transfermarkt league-season page is laid out and
whether it can be trusted to answer "which clubs were in this league in this
season?". Built to decide how to scrape Big-5 league membership by season.

WHY BY SEASON: a club's overview page shows its CURRENT league, which is
wrong for historical transfers (Sunderland, Watford, Leeds, Burnley, Swansea
and Southampton have each moved between divisions since 2010). The unit that
works is club x season, so the question is asked of league-season pages.

What it checks, because each is a way this could silently go wrong:
  1. SEASON EVIDENCE. If the ?saison_id= parameter were ignored, every season
     would return the current table and the data would look fine while being
     wrong. So it prints the page title, first heading, and any season
     dropdown's selected option. Check these name the season you asked for.
  2. THE PARTICIPANTS TABLE. It picks the table holding the most distinct club
     links, prints every club, and compares the count with the expected size of
     that league that season (20, or 18 for the Bundesliga and for Ligue 1 from
     2023/24). It also lists club links found OUTSIDE that table (sidebars,
     recent-transfer widgets), which a naive "every club link on the page"
     approach would wrongly count as members.
  3. KNOWN CLUBS. Club ids are Transfermarkt's own, the same ids used in
     buyer_club_transfers. Of the 69 buyer clubs, the ones that must be in this
     league this season are known (Juventus, Inter, Milan... in Serie A 2019),
     so the overlap is an independent test that the right table was picked and
     the right season returned.

Read-only. Nothing is written.

Usage:
    python pipelines/transfermarkt/inspect_league_season.py --league IT1 --season 2019
    python pipelines/transfermarkt/inspect_league_season.py --league GB1 --season 2012
    python pipelines/transfermarkt/inspect_league_season.py --league FR1 --season 2023
    python pipelines/transfermarkt/inspect_league_season.py --url "https://..."   # any page, to try another URL shape

The default URL shape (/{slug}/startseite/wettbewerb/{code}?saison_id={year}) is
the one believed to work. It has NOT been confirmed. If the page title or season
evidence names the wrong season, or no clubs are found, try --url.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from scrape_buyer_clubs import ScrapeError, fetch_html

BIG5 = {
    "GB1": {"slug": "premier-league", "name": "Premier League"},
    "ES1": {"slug": "laliga", "name": "La Liga"},
    "IT1": {"slug": "serie-a", "name": "Serie A"},
    "L1": {"slug": "bundesliga", "name": "Bundesliga"},
    "FR1": {"slug": "ligue-1", "name": "Ligue 1"},
}
DEFAULT_KNOWN = Path("data_audit/results/buyer_clubs_to_scrape.csv")
_CLUB_LINK = re.compile(r"/verein/(\d+)")
_HEADING_TAG = re.compile(r"^h[1-6]$")


def expected_club_count(code, season):
    """How many clubs the league had that season (season = starting year)."""
    if code == "L1":
        return 18
    if code == "FR1":
        return 18 if season >= 2023 else 20
    return 20


def build_url(code, season, slug=None):
    return (f"https://www.transfermarkt.com/{slug or BIG5[code]['slug']}"
            f"/startseite/wettbewerb/{code}?saison_id={season}")


def club_links(node):
    """[(club_id, name)] for every club link under `node`, de-duplicated by id
    in first-seen order. A row usually holds two anchors for one club (a crest
    with no text, then the name), so the first NON-EMPTY text wins."""
    found = {}
    for a in node.find_all("a", href=True):
        m = _CLUB_LINK.search(a["href"])
        if not m:
            continue
        club_id = int(m.group(1))
        text = a.get_text(" ", strip=True)
        if club_id not in found or (not found[club_id] and text):
            found[club_id] = text
    return list(found.items())


def describe_tables(soup):
    described = []
    for i, table in enumerate(soup.find_all("table")):
        heading = table.find_previous(_HEADING_TAG)
        described.append({
            "index": i,
            "class": " ".join(table.get("class", [])),
            "heading": heading.get_text(" ", strip=True) if heading else None,
            "rows": len(table.find_all("tr")),
            "clubs": club_links(table),
        })
    return described


def best_table(described, minimum=5):
    """The table holding the most distinct clubs, or None if none holds at
    least `minimum` (then it is not a participants table at all)."""
    holders = [t for t in described if len(t["clubs"]) >= minimum]
    return max(holders, key=lambda t: len(t["clubs"])) if holders else None


def season_evidence(soup):
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    h1 = soup.find("h1")
    selected = []
    for select in soup.find_all("select"):
        for opt in select.find_all("option"):
            if opt.has_attr("selected"):
                selected.append((select.get("name") or select.get("id") or "?",
                                 opt.get("value"), opt.get_text(" ", strip=True)))
    return {"title": title, "h1": h1.get_text(" ", strip=True) if h1 else None, "selected": selected}


def read_known(path):
    """club_id -> name for the 69 buyer clubs. Empty if the file is missing."""
    known = {}
    if path and Path(path).exists():
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw = (row.get("counterparty_club_id") or "").strip()
                if raw:
                    known[int(raw)] = (row.get("counterparty_club_name") or "").strip()
    return known


def report(html, code, season, known, url=""):
    soup = BeautifulSoup(html, "html.parser")
    ev = season_evidence(soup)
    tables = describe_tables(soup)
    all_ids = {cid for cid, _ in club_links(soup)}
    lines = []
    emit = lines.append

    emit(f"URL: {url}")
    emit(f"page title:    {ev['title']!r}")
    emit(f"first heading: {ev['h1']!r}")
    emit(f"season selector (selected option): {ev['selected'] or 'none found'}")
    emit(f"  -> these should name the {season}/{str(season + 1)[-2:]} season. If they name a different one, "
         f"the season parameter was ignored.")
    emit(f"\n{len(tables)} tables; {len(all_ids)} distinct club ids linked anywhere on the page.")

    holders = [t for t in tables if t["clubs"]]
    emit("\n--- tables that contain club links")
    for t in holders[:12]:
        emit(f"  [{t['index']:>2}] class={t['class']!r:<28} heading={t['heading']!r:<30} "
             f"rows={t['rows']:<3} distinct_clubs={len(t['clubs'])}")

    best = best_table(tables)
    if best is None:
        emit("\nNO participants table found (no table holds 5+ clubs). Wrong page, a bot-challenge page, "
             "or a different layout. Try --url.")
        return "\n".join(lines)

    want = expected_club_count(code, season)
    got = len(best["clubs"])
    verdict = "OK" if got == want else f"MISMATCH (expected {want})"
    emit(f"\n--- candidate participants table: index {best['index']}, {got} clubs, "
         f"expected {want} for {code} {season}: {verdict}")
    for cid, name in best["clubs"]:
        tag = f"   <- buyer club: {known[cid]}" if cid in known else ""
        emit(f"  {cid:>7}  {name}{tag}")

    in_best = {cid for cid, _ in best["clubs"]}
    elsewhere = [(cid, n) for cid, n in club_links(soup) if cid not in in_best]
    emit(f"\n--- club links elsewhere on the page, NOT in that table: {len(elsewhere)} "
         f"(counting every link on the page would wrongly add these)")
    for cid, name in elsewhere[:10]:
        emit(f"  {cid:>7}  {name}")

    if known:
        overlap = [known[cid] for cid, _ in best["clubs"] if cid in known]
        emit(f"\n--- known buyer clubs in this table: {len(overlap)} of {len(known)}")
        emit("  " + (", ".join(overlap) if overlap else "none"))
    else:
        emit("\n--- known buyer clubs: no CSV found, overlap check skipped")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--league", choices=sorted(BIG5), default="IT1")
    p.add_argument("--season", type=int, default=2019, help="starting year, 2019 = 2019/20")
    p.add_argument("--slug", default=None, help="override the URL slug")
    p.add_argument("--url", default=None, help="fetch this exact URL instead of building one")
    p.add_argument("--known", type=Path, default=DEFAULT_KNOWN)
    args = p.parse_args()

    url = args.url or build_url(args.league, args.season, args.slug)
    print(f"Fetching {url}\n")
    try:
        html = fetch_html(url)
    except ScrapeError as e:
        sys.exit(f"FAILED: {e}")
    print(report(html, args.league, args.season, read_known(args.known), url))


if __name__ == "__main__":
    main()
