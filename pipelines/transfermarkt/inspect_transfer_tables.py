"""
Diagnostic: shows how one club's /alletransfers/ page is laid out, table by
table, and checks the extractor's direction rule against the page itself.

HISTORY: the extractor used to label direction by table position (even index
= 'in', odd = 'out'). Running this on three real pages (2026-10-05) showed
why that was wrong. Every table sits under its own heading ("Arrivals 26/27",
"Departures 27/28"), and a season with only ONE table (Atalanta's lone
"Departures 27/28" at table 0, Anzhi's lone "Departures 22/23" at table 6)
shifts every table below it by one. The extractor now reads the heading. The
table header row is identical on every table ('Players', 'Club', 'Transfer
sum') and was useless as a signal.

This is read-only and still useful as a spot check on any page. It prints:

  1. The first few tables: position-assigned direction (what the old rule
     said), the heading, row count and season ids.
  2. Direction by heading vs. by position: how many tables have a usable
     Arrivals/Departures heading, how many the position rule would have
     gotten WRONG (and how many rows from RELEVANT_FROM_SEASON on that
     covers), where it first goes wrong, tables with no direction heading,
     and headings shared by more than one table (which the extractor treats
     as unresolved rather than guessing).
  3. Season blocks: consecutive tables sharing one season id, with a
     histogram of block sizes. A block that is not a pair is where position
     parity breaks, and the indexes are listed.
  4. Empty tables.

Usage:
    python pipelines/transfermarkt/inspect_transfer_tables.py --club 985
    python pipelines/transfermarkt/inspect_transfer_tables.py --club 800 --first 12
"""

import argparse
import re
from collections import Counter

from bs4 import BeautifulSoup

from extract_transfermarkt_transfer_history import (
    RELEVANT_FROM_SEASON,
    extract_transfer_table,
    heading_direction,
)
from scrape_buyer_clubs import ScrapeError, build_url, fetch_html


def season_key(seasons):
    """One season -> that season. No data rows -> None. Mixed -> the tuple."""
    if not seasons:
        return None
    return seasons[0] if len(seasons) == 1 else tuple(seasons)


def describe_tables(html):
    """Pure function: page HTML -> one dict per <table>, in page order.
    `parity` is what the OLD position rule said, `heading_direction` is what
    the page says (None if there is no Arrivals/Departures heading)."""
    soup = BeautifulSoup(html, "html.parser")
    described = []
    for i, table in enumerate(soup.find_all("table")):
        parity = "in" if i % 2 == 0 else "out"
        rows = table.find_all("tr")
        header = [c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])] if rows else []
        heading_tag = table.find_previous(re.compile(r"^h[1-6]$"))
        heading = heading_tag.get_text(" ", strip=True) if heading_tag else None
        data = extract_transfer_table(table, parity)
        seasons = sorted({t["season_id"] for t in data if t["season_id"] is not None})
        described.append({
            "index": i,
            "parity": parity,
            "header": tuple(h for h in header if h),
            "heading": heading,
            "heading_id": id(heading_tag) if heading_tag is not None else None,
            "heading_direction": heading_direction(heading),
            "rows": len(data),
            "rows_relevant": sum(1 for t in data
                                 if t["season_id"] is not None and t["season_id"] >= RELEVANT_FROM_SEASON),
            "seasons": seasons,
        })
    return described


def season_blocks(tables):
    """Groups consecutive tables that share the same season key.
    Returns [(season_key, [table indexes])]."""
    blocks = []
    for t in tables:
        key = season_key(t["seasons"])
        if blocks and blocks[-1][0] == key:
            blocks[-1][1].append(t["index"])
        else:
            blocks.append((key, [t["index"]]))
    return blocks


def report(tables, first=8):
    lines = []
    emit = lines.append

    emit(f"{len(tables)} tables on the page.\n")
    emit(f"--- first {min(first, len(tables))} tables (position rule vs. what the heading says)")
    for t in tables[:first]:
        seasons = t["seasons"] if len(t["seasons"]) <= 3 else f"{t['seasons'][0]}..{t['seasons'][-1]} ({len(t['seasons'])})"
        emit(f"  [{t['index']:>3}] position={t['parity']:<3} heading={t['heading']!r:<24} "
             f"rows={t['rows']:<4} seasons={seasons}")

    resolved = [t for t in tables if t["heading_direction"]]
    wrong = [t for t in resolved if t["heading_direction"] != t["parity"]]
    no_heading = [t for t in tables if not t["heading_direction"]]
    heading_use = Counter(t["heading_id"] for t in tables if t["heading_id"] is not None)
    shared = sum(1 for n in heading_use.values() if n > 1)
    emit("\n--- direction by heading vs. by position")
    emit(f"  {len(resolved)} of {len(tables)} tables have an Arrivals/Departures heading")
    emit(f"  the position rule would be WRONG on {len(wrong)} of them "
         f"({sum(t['rows_relevant'] for t in wrong)} rows from {RELEVANT_FROM_SEASON} on); "
         f"first wrong at table index {wrong[0]['index'] if wrong else '-'}")
    emit(f"  tables with no Arrivals/Departures heading: {len(no_heading)}"
         + (f"  indexes={[t['index'] for t in no_heading][:15]}" if no_heading else ""))
    emit(f"  headings shared by more than one table (treated as unresolved): {shared}")

    blocks = season_blocks([t for t in tables if t["rows"] > 0])
    sizes = Counter(len(idx) for _, idx in blocks)
    emit("\n--- season blocks (consecutive non-empty tables sharing one season id)")
    emit(f"  {len(blocks)} blocks. Block sizes: "
         + ", ".join(f"{size} table(s) x {n}" for size, n in sorted(sizes.items())))
    odd = [(k, idx) for k, idx in blocks if len(idx) != 2]
    if odd:
        emit(f"  {len(odd)} block(s) NOT of size 2, where position parity breaks (first 15):")
        for key, idx in odd[:15]:
            emit(f"    season={key}  table indexes={idx}")
    else:
        emit("  every block is a pair, so position parity holds across this page")

    empty = [t["index"] for t in tables if t["rows"] == 0]
    emit(f"\n--- empty tables: {len(empty)}" + (f"  indexes={empty[:20]}" if empty else ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--club", type=int, default=985, help="Transfermarkt club id (default 985, Man Utd)")
    parser.add_argument("--slug", default=None, help="optional URL slug; '-' is used if omitted")
    parser.add_argument("--first", type=int, default=8, help="how many leading tables to print in full")
    args = parser.parse_args()

    url = build_url(args.club, args.slug)
    print(f"Fetching {url}")
    try:
        html = fetch_html(url)
    except ScrapeError as e:
        raise SystemExit(f"FAILED: {e}")
    print(report(describe_tables(html), first=args.first))


if __name__ == "__main__":
    main()
