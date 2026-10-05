"""
Loads each buyer club's scraped transfer history (data/transfermarkt/buyers/
{club_id}_transfers.json, written by scrape_buyer_clubs.py) into the
buyer_club_transfers table (schema/transfermarkt/buyer_club_transfers.sql
-- run that first).

Unlike load_eredivisie_transfers.py, there is NO eredivisie_club_status
filter: none of these clubs is ever an Eredivisie club, and the point is
to capture what each one spent overall, not just on Eredivisie players.

Idempotent per club: a club's existing rows are deleted and reinserted in
ONE transaction, so re-running never duplicates rows and a failure
mid-club rolls back to the club's previous state instead of leaving it
half-loaded. Other clubs are untouched.

MIN_SEASON drops pre-2000 history. A buyer page goes back to the 1950s;
the earliest Eredivisie-sourced transfer in this project is 2010, so even
a 10-year trailing window needs nothing before 2000, and old rows are the
noisiest (the '?' unknown-fee rows). Set to None to load everything.

Rows with no season_id are skipped and counted (nothing to window them
against), same as load_eredivisie_transfers.py.

After loading, run schema/transfermarkt/buyer_club_transfers_checks.sql --
check 2 validates the in/out direction labels against the Eredivisie
side's own records.
"""

import csv
import json
import re
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

BUYERS_DIR = Path("data/transfermarkt/buyers")
CLUB_LIST = Path("data_audit/results/buyer_clubs_to_scrape.csv")
MIN_SEASON = 2000

INSERT_SQL = """
    INSERT INTO buyer_club_transfers
        (player_id, player_name, own_club_id, own_club_name, direction,
         counterparty_club_id, counterparty_club_name, season_id,
         fee_amount, fee_type, is_internal_promotion)
    VALUES %s
"""


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def read_club_names(path):
    """club_id -> name from the scrape-target CSV, for the readable
    own_club_name column. Missing file/rows just mean a NULL name."""
    names = {}
    if not Path(path).exists():
        return names
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw_id = (row.get("counterparty_club_id") or "").strip()
            if raw_id:
                names[int(raw_id)] = (row.get("counterparty_club_name") or "").strip() or None
    return names


def build_rows(club_id, club_name, transfers, min_season=MIN_SEASON):
    """Pure function (no DB): scraped transfer dicts -> insert tuples, plus
    counts of what was skipped and why. Tuple order matches INSERT_SQL."""
    rows = []
    no_season = 0
    too_old = 0
    for t in transfers:
        season_id = t["season_id"]
        if season_id is None:
            no_season += 1
            continue
        if min_season is not None and season_id < min_season:
            too_old += 1
            continue
        rows.append((
            t["player_id"],
            t["name"],
            club_id,
            club_name,
            t["direction"],
            t["counterparty_club_id"],
            t["counterparty_club_name"],
            season_id,
            t["fee"]["amount"],
            t["fee"]["type"],
            t["is_internal_promotion"],
        ))
    return rows, no_season, too_old


def club_id_from_filename(path):
    m = re.fullmatch(r"(\d+)_transfers\.json", path.name)
    return int(m.group(1)) if m else None


def main():
    files = sorted(p for p in BUYERS_DIR.glob("*_transfers.json") if club_id_from_filename(p))
    if not files:
        print(f"No *_transfers.json files in {BUYERS_DIR} -- run scrape_buyer_clubs.py first.")
        return

    names = read_club_names(CLUB_LIST)
    conn = get_connection()
    total_read = total_inserted = 0

    try:
        with conn.cursor() as cur:
            for path in files:
                club_id = club_id_from_filename(path)
                club_name = names.get(club_id)
                with open(path, encoding="utf-8") as f:
                    transfers = json.load(f)

                rows, no_season, too_old = build_rows(club_id, club_name, transfers)
                try:
                    cur.execute("DELETE FROM buyer_club_transfers WHERE own_club_id = %s", (club_id,))
                    replaced = cur.rowcount
                    if rows:
                        execute_values(cur, INSERT_SQL, rows)
                    conn.commit()
                except Exception:
                    conn.rollback()   # club stays exactly as it was before this attempt
                    raise

                total_read += len(transfers)
                total_inserted += len(rows)
                print(f"{club_name or club_id} (id={club_id}): read {len(transfers)}, "
                      f"inserted {len(rows)} (replaced {replaced} existing), "
                      f"skipped: {no_season} no season, {too_old} before {MIN_SEASON}")
    except psycopg2.errors.UndefinedTable:
        print("\nbuyer_club_transfers doesn't exist -- run "
              "schema/transfermarkt/buyer_club_transfers.sql first.")
        raise
    finally:
        conn.close()

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    print(f"Files loaded: {len(files)}   Rows read: {total_read}   Rows inserted: {total_inserted}")
    print("\nNext: run schema/transfermarkt/buyer_club_transfers_checks.sql")


if __name__ == "__main__":
    main()
