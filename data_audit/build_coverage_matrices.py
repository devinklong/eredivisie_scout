"""
Builds three long-format coverage matrices -- one row per
(dimension value, column), not a single blended percentage. This is
the deliberate replacement for pipelines/audits/audit_coverage.py's
earlier domain-bucketed approach (see data_audit/README.md for why):
a matrix lets you query down to "which SPECIFIC column is weak for
this SPECIFIC player/team/season," which a blended % hides.

Creates three tables (DROP + CREATE, safe to re-run any time the
underlying data changes):
  - season_column_coverage  (group_key = season_id)
  - team_column_coverage    (group_key = team)
  - player_column_coverage  (group_key = player_id, includes
    canonical_name since player_id alone isn't human-searchable)

Each row: group_key, column_name, domain, total_rows, non_null_rows,
pct_populated.

Same gk_* exclusion rule as the earlier coverage script: those
columns only count toward a row's denominator when that row is an
actual goalkeeper (fbref_position LIKE '%GK%', the real signal
master_players_testing.sql's Section 9a confirmed) -- a non-keeper's
structurally-NULL gk_* values are excluded, not counted as missing.

Cross-reference data_audit/known_issues.md before treating anything
this surfaces as a new bug -- most low-coverage cells have an already-
documented, real explanation.
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
        # key/identifier columns (player_id, team, season_id,
        # canonical_name, etc.) are excluded -- not "data" in the
        # coverage sense, always present by definition.
    return domains


def create_coverage_table(cur, table_name, group_by_col, domains, include_name=False):
    name_col_def = ", canonical_name TEXT" if include_name else ""
    cur.execute(f"""
        DROP TABLE IF EXISTS {table_name};
        CREATE TABLE {table_name} (
            group_key TEXT NOT NULL,
            column_name TEXT NOT NULL,
            domain TEXT NOT NULL,
            total_rows INTEGER NOT NULL,
            non_null_rows INTEGER NOT NULL,
            pct_populated NUMERIC(5,1)
            {name_col_def}
        )
    """)

    name_select = ", MAX(canonical_name)" if include_name else ""

    for column_name, domain in domains.items():
        if domain == "gk":
            # Only goalkeeper rows count toward this column's
            # denominator -- see module docstring. %% escapes the
            # literal % for psycopg2, since this query also uses %s
            # parameter placeholders below.
            where_clause = "WHERE fbref_position LIKE '%%GK%%'"
        else:
            where_clause = ""

        cur.execute(f"""
            INSERT INTO {table_name} (group_key, column_name, domain, total_rows, non_null_rows, pct_populated{", canonical_name" if include_name else ""})
            SELECT
                {group_by_col}::text AS group_key,
                %s AS column_name,
                %s AS domain,
                COUNT(*) AS total_rows,
                COUNT("{column_name}") AS non_null_rows,
                ROUND(100.0 * COUNT("{column_name}") / NULLIF(COUNT(*), 0), 1) AS pct_populated
                {name_select}
            FROM {VIEW_TABLE}
            {where_clause}
            {"AND" if where_clause else "WHERE"} {group_by_col} IS NOT NULL
            GROUP BY {group_by_col}
        """, (column_name, domain))

    cur.execute(f"CREATE INDEX ON {table_name} (group_key)")
    cur.execute(f"CREATE INDEX ON {table_name} (column_name)")
    cur.execute(f"CREATE INDEX ON {table_name} (pct_populated)")


def export_table_to_csv(cur, table_name, include_name=False):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{table_name}.csv"
    cols = "group_key, canonical_name, column_name, domain, total_rows, non_null_rows, pct_populated" \
        if include_name else "group_key, column_name, domain, total_rows, non_null_rows, pct_populated"
    cur.execute(f"SELECT {cols} FROM {table_name} ORDER BY group_key, pct_populated ASC")
    rows = cur.fetchall()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols.replace(" ", "").split(","))
        writer.writerows(rows)
    print(f"  Exported {len(rows)} rows to {out_path}")


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        domains = get_domain_columns(cur)
        print(f"Found {len(domains)} data columns to audit "
              f"({sum(1 for d in domains.values() if d == 'fbref')} fbref, "
              f"{sum(1 for d in domains.values() if d == 'ws')} ws, "
              f"{sum(1 for d in domains.values() if d == 'tm')} tm, "
              f"{sum(1 for d in domains.values() if d == 'gk')} gk).")

        print("Building season_column_coverage...")
        create_coverage_table(cur, "season_column_coverage", "season_id", domains)
        conn.commit()
        export_table_to_csv(cur, "season_column_coverage")

        print("Building team_column_coverage...")
        create_coverage_table(cur, "team_column_coverage", "team", domains)
        conn.commit()
        export_table_to_csv(cur, "team_column_coverage")

        print("Building player_column_coverage (this one's the big one -- "
              f"~2,465 players x {len(domains)} columns)...")
        create_coverage_table(cur, "player_column_coverage", "player_id", domains, include_name=True)
        conn.commit()
        export_table_to_csv(cur, "player_column_coverage", include_name=True)

    print("\nDone. Example queries:")
    print("  -- Every column under 50% coverage for the 2011 season:")
    print("  SELECT column_name, pct_populated FROM season_column_coverage")
    print("  WHERE group_key = '2011' AND pct_populated < 50 ORDER BY pct_populated;")
    print()
    print("  -- Hakim Ziyech's full coverage profile, worst columns first:")
    print("  SELECT column_name, pct_populated FROM player_column_coverage")
    print("  WHERE canonical_name = 'Hakim Ziyech' ORDER BY pct_populated;")
    print()
    print("  -- Every team with under 50% ws_ coverage:")
    print("  SELECT group_key, column_name, pct_populated FROM team_column_coverage")
    print("  WHERE domain = 'ws' AND pct_populated < 50 ORDER BY pct_populated;")

    conn.close()


if __name__ == "__main__":
    main()
