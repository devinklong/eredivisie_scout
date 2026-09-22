"""
The single definitive coverage number for every column in
master_player_season_stats -- one row per column, whole-dataset
% populated. This is the flat reference; season_column_coverage/
team_column_coverage/player_column_coverage (build_coverage_matrices.py)
slice this same underlying fact by dimension. Check this table first
for "how good is column X overall," then drill into the matrices for
"which specific season/team/player is dragging it down."

Same gk_* exclusion as the matrices: those columns' denominator is
only goalkeeper rows (fbref_position LIKE '%GK%'), not the whole
table -- a non-keeper's structurally-NULL gk_* value isn't a gap.
"""

import csv
from pathlib import Path

import psycopg2

VIEW_TABLE = "master_player_season_stats"
RESULTS_DIR = Path(__file__).parent / "results"


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def get_domain_columns(cur):
    cur.execute(f"""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = '{VIEW_TABLE}'
        ORDER BY ordinal_position
    """)
    all_cols = [r[0] for r in cur.fetchall()]

    domains = {}
    for col in all_cols:
        if col.startswith("fbref_"):
            domains[col] = "fbref"
        elif col.startswith("ws_"):
            domains[col] = "ws"
        elif col.startswith("tm_"):
            domains[col] = "tm"
        elif col.startswith("gk_"):
            domains[col] = "gk"
    return domains


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        domains = get_domain_columns(cur)

        cur.execute("""
            DROP TABLE IF EXISTS column_coverage_summary;
            CREATE TABLE column_coverage_summary (
                column_name TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                total_rows INTEGER NOT NULL,
                non_null_rows INTEGER NOT NULL,
                pct_populated NUMERIC(5,1),
                pct_null NUMERIC(5,1)
            )
        """)

        for column_name, domain in domains.items():
            where_clause = "WHERE fbref_position LIKE '%%GK%%'" if domain == "gk" else ""
            cur.execute(f"""
                INSERT INTO column_coverage_summary
                    (column_name, domain, total_rows, non_null_rows, pct_populated, pct_null)
                SELECT
                    %s, %s,
                    COUNT(*),
                    COUNT("{column_name}"),
                    ROUND(100.0 * COUNT("{column_name}") / NULLIF(COUNT(*), 0), 1),
                    ROUND(100.0 * (COUNT(*) - COUNT("{column_name}")) / NULLIF(COUNT(*), 0), 1)
                FROM {VIEW_TABLE}
                {where_clause}
            """, (column_name, domain))

        conn.commit()

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = RESULTS_DIR / "column_coverage_summary.csv"
        cur.execute("""
            SELECT column_name, domain, total_rows, non_null_rows, pct_populated, pct_null
            FROM column_coverage_summary
            ORDER BY pct_populated ASC
        """)
        rows = cur.fetchall()
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["column_name", "domain", "total_rows", "non_null_rows", "pct_populated", "pct_null"])
            writer.writerows(rows)
        print(f"Exported {len(rows)} rows to {out_path}")

    print(f"\ncolumn_coverage_summary built -- {len(domains)} columns.")
    print("\nExample queries:")
    print("  -- Every column under 50% populated, worst first:")
    print("  SELECT column_name, domain, pct_populated FROM column_coverage_summary")
    print("  WHERE pct_populated < 50 ORDER BY pct_populated;")
    print()
    print("  -- Coverage by domain, averaged:")
    print("  SELECT domain, ROUND(AVG(pct_populated), 1) AS avg_pct FROM column_coverage_summary")
    print("  GROUP BY domain ORDER BY avg_pct;")

    conn.close()


if __name__ == "__main__":
    main()
