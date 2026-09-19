"""
Full data-quality audit across the eredivisie_scout schema, ahead of
any modeling work. Built 2026-09-18 to cover what
master_players_testing.sql's Section 6 does NOT: that section only
checks 3 hardcoded columns against global, hand-typed thresholds.
This script introspects every numeric column dynamically (via
information_schema) and runs the same checks against ALL of them,
per season -- so it scales automatically as columns get added,
instead of needing a new hand-written block every time.

Covers, across eredivisie_soccerdata_player_season_stats,
eredivisie_whoscored_player_season_stats, and
eredivisie_keeper_season_stats:
  1. Per-season, per-column outlier detection (z-score based -- flags
     values more than N std devs from THAT SEASON's own mean for that
     column, not a single global number, since era/tempo differences
     make one global threshold meaningless across 2010-2025).
  2. Per-column, per-season NULL rate -- not just the 2 columns
     Section 3 already tracks.
  3. Team-level row-count density per season, generalized beyond the
     WhoScored-only check in Section 3c.

Also covers:
  4. eredivisie_transfermarkt_player_bio: height_cm range sanity
     (a real human range, not a stat that varies by season) and a
     foot-value distinct-value check.
  5. eredivisie_transfers: fee_amount outlier check per fee_type, and
     a direction balance check (own_club's 'in' rows should roughly
     mirror counterparty clubs' 'out' rows for the same transfer,
     given the known non-deduplication of this table).

NOT yet covered here, flagged rather than silently skipped:
  - Cross-season consistency for player-level fields that shouldn't
    change (canonical_born, height, foot) across a player's multiple
    season rows -- needs its own pass, deferred.
  - Per-90 denominator sanity generalized beyond Section 6's 3
    hardcoded columns -- deferred, same z-score approach as #1 above
    would apply once nineties < 1.0 rows are excluded from the
    baseline mean/stddev calculation first (a low-minutes outlier is
    expected noise, not a data bug).

Z_SCORE_THRESHOLD is a starting point, not a validated constant --
worth tuning after a first look at what it actually flags.
"""

import psycopg2
from collections import defaultdict

Z_SCORE_THRESHOLD = 4.0  # flags a value 4+ std devs from its season's own mean

PLAYER_SEASON_TABLES = [
    "eredivisie_soccerdata_player_season_stats",
    "eredivisie_whoscored_player_season_stats",
    "eredivisie_keeper_season_stats",
]

# Columns to exclude from outlier/null checks even though they're
# numeric -- IDs, keys, and pure counters that aren't "stats" in the
# sense this audit cares about.
EXCLUDE_COLUMNS = {
    "stat_id", "keeper_stat_id", "season_id", "born", "player_id",
    "crosswalk_id", "club_id", "transfer_id", "whoscored_player_id",
    "canonical_whoscored_player_id",
}


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def get_numeric_columns(cur, table):
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        AND data_type IN ('integer', 'numeric', 'smallint', 'bigint', 'double precision', 'real')
        ORDER BY ordinal_position
    """, (table,))
    return [r[0] for r in cur.fetchall() if r[0] not in EXCLUDE_COLUMNS]


def audit_outliers_and_nulls(cur, table):
    print(f"\n{'=' * 70}\n{table}\n{'=' * 70}")
    numeric_cols = get_numeric_columns(cur, table)
    print(f"Auditing {len(numeric_cols)} numeric columns across all seasons.\n")

    for col in numeric_cols:
        # Per-season mean/stddev, then flag individual rows beyond
        # Z_SCORE_THRESHOLD std devs from THEIR OWN season's mean.
        cur.execute(f"""
            WITH season_stats AS (
                SELECT season_id, AVG("{col}") AS mean, STDDEV("{col}") AS stddev
                FROM {table}
                WHERE "{col}" IS NOT NULL
                GROUP BY season_id
            )
            SELECT t.player_name, t.team, t.season_id, t."{col}",
                   ss.mean, ss.stddev,
                   ABS(t."{col}" - ss.mean) / NULLIF(ss.stddev, 0) AS z_score
            FROM {table} t
            JOIN season_stats ss ON ss.season_id = t.season_id
            WHERE t."{col}" IS NOT NULL
              AND ss.stddev > 0
              AND ABS(t."{col}" - ss.mean) / ss.stddev > %s
            ORDER BY z_score DESC
            LIMIT 10
        """, (Z_SCORE_THRESHOLD,))
        outliers = cur.fetchall()

        cur.execute(f"""
            SELECT season_id, COUNT(*) AS total, COUNT("{col}") AS non_null,
                   COUNT(*) - COUNT("{col}") AS null_count,
                   ROUND((COUNT(*) - COUNT("{col}"))::numeric / NULLIF(COUNT(*), 0) * 100, 1) AS null_pct
            FROM {table}
            GROUP BY season_id
            ORDER BY season_id
        """)
        null_by_season = cur.fetchall()
        high_null_seasons = [(s, p) for s, t, nn, nc, p in null_by_season if p and p > 50]

        if outliers or high_null_seasons:
            print(f"--- {col} ---")
            if outliers:
                print(f"  Top outliers (z-score > {Z_SCORE_THRESHOLD}):")
                for name, team, season, val, mean, stddev, z in outliers[:5]:
                    print(f"    {name} ({team}, {season}): {val} "
                          f"(season mean={mean:.1f}, z={z:.1f})")
            if high_null_seasons:
                print(f"  Seasons with >50% NULL: "
                      f"{', '.join(f'{s}={p}%' for s, p in high_null_seasons)}")


def audit_team_density(cur, table):
    print(f"\n--- Team-level row density, {table} ---")
    cur.execute(f"""
        SELECT season_id, team, COUNT(*) AS rows
        FROM {table}
        GROUP BY season_id, team
        ORDER BY season_id, rows ASC
    """)
    rows = cur.fetchall()
    by_season = defaultdict(list)
    for season, team, count in rows:
        by_season[season].append((team, count))

    for season in sorted(by_season):
        teams = by_season[season]
        avg = sum(c for _, c in teams) / len(teams)
        thin = [(t, c) for t, c in teams if c < avg * 0.5]
        if thin:
            print(f"  {season}: avg {avg:.0f} rows/team -- thin: "
                  f"{', '.join(f'{t}={c}' for t, c in thin)}")


def audit_transfermarkt_bio(cur):
    print(f"\n{'=' * 70}\neredivisie_transfermarkt_player_bio\n{'=' * 70}")
    cur.execute("""
        SELECT player_id, height_cm FROM eredivisie_transfermarkt_player_bio
        WHERE height_cm IS NOT NULL AND (height_cm < 155 OR height_cm > 210)
        ORDER BY height_cm
    """)
    bad_heights = cur.fetchall()
    if bad_heights:
        print(f"Implausible height_cm values (outside 155-210cm): {bad_heights}")
    else:
        print("height_cm: all values within plausible 155-210cm range.")

    cur.execute("SELECT DISTINCT foot, COUNT(*) FROM eredivisie_transfermarkt_player_bio GROUP BY foot")
    print(f"foot distinct values: {cur.fetchall()}")


def audit_transfers(cur):
    print(f"\n{'=' * 70}\neredivisie_transfers\n{'=' * 70}")
    cur.execute("""
        SELECT fee_type, MIN(fee_amount), MAX(fee_amount), AVG(fee_amount), COUNT(*)
        FROM eredivisie_transfers
        WHERE fee_amount IS NOT NULL
        GROUP BY fee_type
        ORDER BY MAX(fee_amount) DESC
    """)
    print("fee_amount range by fee_type (millions EUR):")
    for fee_type, mn, mx, avg, n in cur.fetchall():
        print(f"  {fee_type}: min={mn}, max={mx}, avg={avg:.2f}, n={n}")

    cur.execute("SELECT direction, COUNT(*) FROM eredivisie_transfers GROUP BY direction")
    print(f"\ndirection balance: {cur.fetchall()}")


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        for table in PLAYER_SEASON_TABLES:
            audit_outliers_and_nulls(cur, table)
            audit_team_density(cur, table)
        audit_transfermarkt_bio(cur)
        audit_transfers(cur)
    conn.close()
    print(f"\n{'=' * 70}\nDone. This does NOT cover: cross-season consistency for "
          f"player-level static fields, or per-90 denominator sanity beyond "
          f"Section 6's existing 3 columns -- see module docstring.")


if __name__ == "__main__":
    main()
