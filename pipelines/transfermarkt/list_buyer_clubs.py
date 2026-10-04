"""
Lists every distinct counterparty club that has paid a real fee for an
Eredivisie-sourced player, ranked by total paid -- the scoping step
before scraping any buyer club's own transfer history (see
schema/analysis/transfer_spend_context.sql's player-level extension).

This is READ-ONLY against existing data -- no new scraping happens
here. Output is the list of real buyer clubs worth scraping next,
not the buyer-side spend data itself (that requires a new scraper
pointed at each club's own /alletransfers/ page, same pattern as
scrape_all_eredivisie_clubs.py).

counterparty_club_id can be NULL (player retired, or Transfermarkt had
no linked club reference) -- excluded here since there's no club to
scrape in that case.
"""

import csv
from pathlib import Path

import psycopg2

RESULTS_DIR = Path("data_audit/results")


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT counterparty_club_id, counterparty_club_name,
                   COUNT(*) AS num_transfers,
                   SUM(fee_amount) AS total_paid_to_eredivisie_clubs,
                   MIN(season_id) AS first_season, MAX(season_id) AS last_season
            FROM eredivisie_transfers
            WHERE direction = 'out'
              AND fee_type IN ('permanent_transfer', 'paid_loan')
              AND fee_amount IS NOT NULL
              AND counterparty_club_id IS NOT NULL
            GROUP BY counterparty_club_id, counterparty_club_name
            ORDER BY total_paid_to_eredivisie_clubs DESC
        """)
        rows = cur.fetchall()
    conn.close()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "buyer_clubs_ranked.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["counterparty_club_id", "counterparty_club_name",
                          "num_transfers", "total_paid_to_eredivisie_clubs",
                          "first_season", "last_season"])
        writer.writerows(rows)

    print(f"{len(rows)} distinct buyer clubs found.")
    print(f"Exported to {out_path}")
    print("\nTop 10:")
    for club_id, name, n, total, first, last in rows[:10]:
        print(f"  {name} (id={club_id}): {n} transfers, EUR{total}m total, {first}-{last}")


if __name__ == "__main__":
    main()
