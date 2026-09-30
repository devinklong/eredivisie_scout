"""
The readable rollup for the comprehensive read-through: real coverage
% for every (team, season) pair, plus team-level and season-level
averages -- the "Groningen: 60% overall, 2010: 30%..." format. None of
the existing coverage tables produce this: season_column_coverage is
season-only, team_column_coverage blends every season for a team into
one number. This computes the missing (team, season) cross-tab
directly from master_player_season_stats, using the same dynamic
column-introspection and gk_-only-for-keepers scoping as the other
coverage scripts (see build_coverage_matrices.py).

Output: one table (team_season_coverage) plus a readable text summary
printed to stdout AND written to
data_audit/results/team_season_summary.txt -- the actual thing to
read through, not another table to query cell-by-cell.

Team-level and season-level rollups are ROW-WEIGHTED, not a plain
average of per-cell percentages -- a team's overall % is
(total non-null cells across all their seasons) / (total cells across
all their seasons), so a season with more players correctly counts
more toward that team's real number than a season with a thin squad.
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
    domains = {"fbref": [], "ws": [], "tm": [], "gk": []}
    for col in all_cols:
        if col.startswith("fbref_"):
            domains["fbref"].append(col)
        elif col.startswith("ws_"):
            domains["ws"].append(col)
        elif col.startswith("tm_"):
            domains["tm"].append(col)
        elif col.startswith("gk_"):
            domains["gk"].append(col)
    return domains


def build_team_season_table(cur, domains):
    def count_expr(cols):
        return " + ".join(f'(CASE WHEN "{c}" IS NOT NULL THEN 1 ELSE 0 END)' for c in cols)

    fbref_cols, ws_cols, tm_cols, gk_cols = (
        domains["fbref"], domains["ws"], domains["tm"], domains["gk"]
    )
    all_non_gk_cols = fbref_cols + ws_cols + tm_cols

    cur.execute(f"""
        DROP TABLE IF EXISTS team_season_coverage;
        CREATE TABLE team_season_coverage (
            team TEXT NOT NULL,
            canonical_team TEXT,
            season_id INTEGER NOT NULL,
            num_players INTEGER NOT NULL,
            total_cells BIGINT NOT NULL,
            non_null_cells BIGINT NOT NULL,
            pct_populated NUMERIC(5,1)
        )
    """)

    cur.execute(f"""
        INSERT INTO team_season_coverage (team, season_id, num_players, total_cells, non_null_cells, pct_populated)
        SELECT
            team, season_id,
            COUNT(*) AS num_players,
            SUM({len(all_non_gk_cols)}
                + CASE WHEN fbref_position LIKE '%GK%' THEN {len(gk_cols)} ELSE 0 END
            ) AS total_cells,
            SUM(({count_expr(all_non_gk_cols)})
                + CASE WHEN fbref_position LIKE '%GK%' THEN ({count_expr(gk_cols)}) ELSE 0 END
            ) AS non_null_cells,
            ROUND(100.0 * SUM(({count_expr(all_non_gk_cols)})
                + CASE WHEN fbref_position LIKE '%GK%' THEN ({count_expr(gk_cols)}) ELSE 0 END
            ) / NULLIF(SUM({len(all_non_gk_cols)}
                + CASE WHEN fbref_position LIKE '%GK%' THEN {len(gk_cols)} ELSE 0 END
            ), 0), 1) AS pct_populated
        FROM {VIEW_TABLE}
        GROUP BY team, season_id
    """)

    # canonical_team, resolved through team_name_alias -- same approach
    # as team_column_coverage's own canonical_team column.
    cur.execute("""
        UPDATE team_season_coverage tsc
        SET canonical_team = canon.source_name
        FROM team_name_alias fbref_alias
        JOIN team_name_alias canon ON canon.club_id = fbref_alias.club_id AND canon.source = 'transfermarkt'
        WHERE fbref_alias.source = 'fbref' AND fbref_alias.source_name = tsc.team
    """)

    cur.execute("CREATE INDEX ON team_season_coverage (team)")
    cur.execute("CREATE INDEX ON team_season_coverage (season_id)")


def print_and_write_summary(cur):
    lines = []

    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 70)
    emit("TEAM ROLLUP (row-weighted across all that team's seasons)")
    emit("=" * 70)
    cur.execute("""
        SELECT COALESCE(canonical_team, team) AS name,
               ROUND(100.0 * SUM(non_null_cells) / NULLIF(SUM(total_cells), 0), 1) AS overall_pct,
               MIN(season_id) AS first_season, MAX(season_id) AS last_season
        FROM team_season_coverage
        GROUP BY COALESCE(canonical_team, team)
        ORDER BY overall_pct DESC
    """)
    team_rows = cur.fetchall()
    for name, overall_pct, first, last in team_rows:
        emit(f"\n{name}: {overall_pct}% overall ({first}-{last})")
        cur.execute("""
            SELECT season_id, pct_populated, num_players
            FROM team_season_coverage
            WHERE COALESCE(canonical_team, team) = %s
            ORDER BY season_id
        """, (name,))
        for season_id, pct, n in cur.fetchall():
            emit(f"  {season_id}: {pct}%  ({n} players)")

    emit("\n" + "=" * 70)
    emit("SEASON ROLLUP (row-weighted across all teams that season)")
    emit("=" * 70)
    cur.execute("""
        SELECT season_id,
               ROUND(100.0 * SUM(non_null_cells) / NULLIF(SUM(total_cells), 0), 1) AS overall_pct,
               SUM(num_players) AS total_players
        FROM team_season_coverage
        GROUP BY season_id
        ORDER BY season_id
    """)
    for season_id, pct, n in cur.fetchall():
        emit(f"{season_id}: {pct}%  ({n} total players)")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "team_season_summary.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n\nWritten to {out_path}")


def export_csv(cur):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "team_season_coverage.csv"
    cur.execute("""
        SELECT team, canonical_team, season_id, num_players, total_cells, non_null_cells, pct_populated
        FROM team_season_coverage
        ORDER BY canonical_team, season_id
    """)
    rows = cur.fetchall()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["team", "canonical_team", "season_id", "num_players",
                          "total_cells", "non_null_cells", "pct_populated"])
        writer.writerows(rows)
    print(f"Exported {len(rows)} rows to {out_path}")


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        domains = get_domain_columns(cur)
        print("Building team_season_coverage...")
        build_team_season_table(cur, domains)
        conn.commit()
        export_csv(cur)
        print()
        print_and_write_summary(cur)
    conn.close()


if __name__ == "__main__":
    main()
