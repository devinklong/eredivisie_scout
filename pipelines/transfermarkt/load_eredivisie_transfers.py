"""
Loads all 29 clubs' scraped transfer-history JSON files (data/transfermarkt/
{club}_transfers.json) into the eredivisie_transfers Postgres table --
filtered to only rows where the OWN club (whichever club's page the row was
scraped from) was actually confirmed Eredivisie that season, per
eredivisie_club_status.

Scope note: filtering is based on the scraped club's own Eredivisie status
for that season, not the counterparty club's. A transfer's counterparty
may or may not have been Eredivisie themselves (e.g. a transfer to/from a
foreign club, or a Dutch club never in the top flight) -- that's fine and
expected; this script only decides whether the ROW belongs to an
Eredivisie-era season for the club it was scraped from.

Rows with no season_id (e.g. 'Retired' transfers, or a missing club link
with no season info) are skipped and counted separately, since there's no
year to check them against at all.

2026-27 is deliberately NOT in eredivisie_club_status yet (per
v1_roadmap.md -- deferred until the winter transfer window closes), so
any 2026-season transfers will be automatically excluded here. That's
expected, not a bug -- re-run this script after the reference table is
updated for 2026-27 to pick those up.

DB connection details are placeholders -- adjust host/dbname/user to match
your local Postgres setup (matches the 'postgres' db name convention used
in two_words).
"""

import json
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

DATA_DIR = Path("data/transfermarkt")

# name -> Transfermarkt club_id, matching pipelines/transfermarkt/
# scrape_all_eredivisie_clubs.py's CLUBS dict (filename prefix -> id).
CLUB_IDS = {
    "ado_den_haag": 1268, "ajax": 610, "almere_city": 723, "az": 1090,
    "cambuur": 133, "de_graafschap": 642, "dordrecht": 1455, "emmen": 1283,
    "excelsior": 798, "feyenoord": 234, "fortuna_sittard": 385,
    "go_ahead_eagles": 1435, "groningen": 202, "heerenveen": 306,
    "heracles_almelo": 1304, "nac_breda": 132, "nec_nijmegen": 467,
    "pec_zwolle": 1269, "psv": 383, "rkc_waalwijk": 235, "roda_jc": 192,
    "sparta": 468, "telstar": 1434, "twente": 317, "utrecht": 200,
    "vitesse": 499, "volendam": 724, "vvv_venlo": 1426, "willem_ii": 403,
}


def get_connection():
    # Adjust these to match your actual local Postgres setup.
    return psycopg2.connect(dbname="postgres", host="localhost")


def load_eredivisie_status(conn):
    """Loads the whole reference table into memory as a set of
    (club_id, season_id) pairs where was_eredivisie = TRUE. Cheaper than
    querying per-row across ~36k transfers."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT club_id, season_id FROM eredivisie_club_status WHERE was_eredivisie = TRUE"
        )
        return set(cur.fetchall())


def load_club_file(name):
    path = DATA_DIR / f"{name}_transfers.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_insert_rows(name, transfers, eredivisie_seasons):
    club_id = CLUB_IDS[name]
    rows = []
    skipped_no_season = 0
    skipped_not_eredivisie = 0

    for t in transfers:
        season_id = t["season_id"]

        if season_id is None:
            skipped_no_season += 1
            continue

        if (club_id, season_id) not in eredivisie_seasons:
            skipped_not_eredivisie += 1
            continue

        rows.append((
            t["player_id"],
            t["name"],
            club_id,
            t["direction"],
            t["counterparty_club_id"],
            t["counterparty_club_name"],
            season_id,
            t["fee"]["amount"],
            t["fee"]["type"],
            t["is_internal_promotion"],
        ))

    return rows, skipped_no_season, skipped_not_eredivisie


def main():
    conn = get_connection()
    eredivisie_seasons = load_eredivisie_status(conn)
    print(f"Loaded {len(eredivisie_seasons)} (club_id, season_id) Eredivisie-confirmed pairs.")

    total_read = 0
    total_inserted = 0
    total_skipped_no_season = 0
    total_skipped_not_eredivisie = 0

    insert_sql = """
        INSERT INTO eredivisie_transfers
            (player_id, player_name, own_club_id, direction,
             counterparty_club_id, counterparty_club_name, season_id,
             fee_amount, fee_type, is_internal_promotion)
        VALUES %s
    """

    with conn.cursor() as cur:
        for name in CLUB_IDS:
            print(f"\nLoading {name}...")
            try:
                transfers = load_club_file(name)
            except FileNotFoundError:
                print(f"  FILE NOT FOUND -- skipping {name}, check data/transfermarkt/")
                continue

            total_read += len(transfers)
            rows, skipped_no_season, skipped_not_eredivisie = build_insert_rows(
                name, transfers, eredivisie_seasons
            )
            total_skipped_no_season += skipped_no_season
            total_skipped_not_eredivisie += skipped_not_eredivisie

            if rows:
                execute_values(cur, insert_sql, rows)
                conn.commit()
            total_inserted += len(rows)

            print(f"  Read {len(transfers)}, inserted {len(rows)}, "
                  f"skipped (no season) {skipped_no_season}, "
                  f"skipped (not Eredivisie that season) {skipped_not_eredivisie}")

    conn.close()

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    print(f"Total transfer rows read across all 29 files: {total_read}")
    print(f"Total inserted into eredivisie_transfers: {total_inserted}")
    print(f"Total skipped (no season_id): {total_skipped_no_season}")
    print(f"Total skipped (club not Eredivisie that season): {total_skipped_not_eredivisie}")


if __name__ == "__main__":
    main()
