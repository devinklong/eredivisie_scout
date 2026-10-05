"""
Decides which buyer clubs are worth scraping, and writes the input file
scrape_buyer_clubs.py reads (data_audit/results/buyer_clubs_to_scrape.csv).

Replaces a hand-built version of that file whose Eredivisie-exclusion list
was hardcoded from memory (the weakness flagged in the 2026-10-03 entry of
docs/patch_list.md) and which lived only as a download, so a fresh checkout
couldn't reproduce it. This reads the ranking list_buyer_clubs.py already
wrote to the repo, and takes the Eredivisie club IDs LIVE from
eredivisie_club_status.

Filters, in this order (a club is counted under the first that applies):
  1. Eredivisie clubs -- a transfer between two tracked clubs shows up from
     both sides, and every one of those clubs' full history is already in
     eredivisie_transfers from its own page, so re-scraping it is redundant.
  2. Under MIN_TOTAL_PAID_M of total fees paid for Eredivisie players --
     a long tail of one-off buyers that wouldn't give enough signal against
     their own spending even with complete data. Boundary is inclusive.
  3. Youth/reserve sides (Ajax U21, Barcelona B, Din. Zagreb II, Jong *) --
     an internal promotion, not a real buyer. Checked AFTER the money cutoff
     so the report below lists only reserve sides that actually would have
     been scraped, i.e. the ones whose removal changes the result.

Refuses to run if eredivisie_club_status returns no clubs: an empty table
would exclude nothing and quietly send every Eredivisie club through as an
"external buyer" -- the same empty-table-passes-silently shape as the empty
keeper table found earlier in this project.

Run order: list_buyer_clubs.py -> this -> scrape_buyer_clubs.py
"""

import csv
import re
import sys
from pathlib import Path

import psycopg2

RANKED_CSV = Path("data_audit/results/buyer_clubs_ranked.csv")
OUT_CSV = Path("data_audit/results/buyer_clubs_to_scrape.csv")
MIN_TOTAL_PAID_M = 10.0

# U16-U23 sides, 'B' / 'II' reserve teams, Dutch 'Jong ...' sides.
RESERVE_SIDE_PATTERN = re.compile(r"\b(U1[6-9]|U2[0-3])\b|\s(B|II)$|^Jong\s")


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def select_clubs(ranked_rows, eredivisie_ids, min_total=MIN_TOTAL_PAID_M):
    """Pure function. Returns (selected_rows, dropped) where dropped is a list
    of (row, reason_key). Selected rows keep the ranking order."""
    selected, dropped = [], []
    for r in ranked_rows:
        club_id = int(r["counterparty_club_id"])
        total = float(r["total_paid_to_eredivisie_clubs"])
        if club_id in eredivisie_ids:
            dropped.append((r, "eredivisie"))
        elif total < min_total:
            dropped.append((r, "under_cutoff"))
        elif RESERVE_SIDE_PATTERN.search(r["counterparty_club_name"]):
            dropped.append((r, "reserve_side"))
        else:
            selected.append(r)
    return selected, dropped


def read_ranked(path):
    if not Path(path).exists():
        sys.exit(f"{path} not found -- run pipelines/transfermarkt/list_buyer_clubs.py first.")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def read_eredivisie_ids():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT club_id FROM eredivisie_club_status")
            ids = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()
    if not ids:
        sys.exit("eredivisie_club_status returned no clubs -- refusing to run: the Eredivisie "
                 "exclusion would silently exclude nothing. Populate that table first.")
    return ids


def main():
    fieldnames, ranked = read_ranked(RANKED_CSV)
    eredivisie_ids = read_eredivisie_ids()
    selected, dropped = select_clubs(ranked, eredivisie_ids)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(selected)

    by_reason = {}
    for row, reason in dropped:
        by_reason.setdefault(reason, []).append(row)
    print(f"Ranked clubs read:                    {len(ranked)}")
    print(f"Eredivisie clubs in the live table:   {len(eredivisie_ids)}")
    print(f"  dropped, Eredivisie (already have): {len(by_reason.get('eredivisie', []))}")
    print(f"  dropped, under EUR{MIN_TOTAL_PAID_M:g}M total:        {len(by_reason.get('under_cutoff', []))}")
    reserves = by_reason.get("reserve_side", [])
    print(f"  dropped, reserve/youth side:        {len(reserves)}"
          + (f"  -> {', '.join(r['counterparty_club_name'] for r in reserves)}" if reserves else ""))
    print(f"Selected for scraping:                {len(selected)}  -> {OUT_CSV}")
    if selected:
        print(f"  top: {selected[0]['counterparty_club_name']} "
              f"(EUR{selected[0]['total_paid_to_eredivisie_clubs']}M), "
              f"bottom: {selected[-1]['counterparty_club_name']} "
              f"(EUR{selected[-1]['total_paid_to_eredivisie_clubs']}M)")


if __name__ == "__main__":
    main()
