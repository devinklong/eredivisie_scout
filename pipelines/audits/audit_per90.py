"""
Generalized per-90 denominator sanity check -- extends
audit_data_quality.py to cover ALL *_per90 columns in
master_player_season_stats, not just the 3 hardcoded columns
master_players_testing.sql's Section 6 checks.

KEY DIFFERENCE from the raw-stat outlier check in audit_data_quality.py:
a per-90 rate computed off a tiny minutes sample (e.g. 1 goal in 8
minutes played) is expected to look extreme -- that's not a data bug,
it's what division by a small number does. Excluding fbref_nineties < 1.0
(under 90 minutes total) from the baseline mean/stddev calculation is
what makes this check meaningful instead of just re-flagging every
low-minutes player as an "outlier."

Dynamically finds every '%_per90' column via information_schema --
same reasoning as audit_data_quality.py's approach: 37+ columns is too
many to hand-type, and the check should keep working automatically as
more get added.
"""

import psycopg2

Z_SCORE_THRESHOLD = 4.0
MIN_NINETIES = 1.0  # under 90 minutes total -- excluded from the baseline


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def get_per90_columns(cur):
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'master_player_season_stats'
        AND column_name ILIKE '%%_per90'
        ORDER BY column_name
    """)
    return [r[0] for r in cur.fetchall()]


def audit_per90(cur, col):
    # Baseline mean/stddev computed ONLY among real-minutes players
    # (fbref_nineties >= MIN_NINETIES) -- a low-minutes player's rate
    # never pollutes what "normal" looks like for this stat/season.
    cur.execute(f"""
        WITH season_stats AS (
            SELECT season_id, AVG("{col}") AS mean, STDDEV("{col}") AS stddev
            FROM master_player_season_stats
            WHERE "{col}" IS NOT NULL AND fbref_nineties >= %s
            GROUP BY season_id
        )
        SELECT m.canonical_name, m.team, m.season_id, m."{col}", m.fbref_nineties,
               ss.mean, ss.stddev,
               ABS(m."{col}" - ss.mean) / NULLIF(ss.stddev, 0) AS z_score
        FROM master_player_season_stats m
        JOIN season_stats ss ON ss.season_id = m.season_id
        WHERE m."{col}" IS NOT NULL
          AND m.fbref_nineties >= %s
          AND ss.stddev > 0
          AND ABS(m."{col}" - ss.mean) / ss.stddev > %s
        ORDER BY z_score DESC
        LIMIT 5
    """, (MIN_NINETIES, MIN_NINETIES, Z_SCORE_THRESHOLD))
    real_outliers = cur.fetchall()

    # How many LOW-minutes rows would have been flagged if the floor
    # weren't applied -- reported separately so it's visible that
    # these are being correctly excluded as noise, not silently lost.
    cur.execute(f"""
        WITH season_stats AS (
            SELECT season_id, AVG("{col}") AS mean, STDDEV("{col}") AS stddev
            FROM master_player_season_stats
            WHERE "{col}" IS NOT NULL AND fbref_nineties >= %s
            GROUP BY season_id
        )
        SELECT COUNT(*)
        FROM master_player_season_stats m
        JOIN season_stats ss ON ss.season_id = m.season_id
        WHERE m."{col}" IS NOT NULL
          AND m.fbref_nineties < %s
          AND ss.stddev > 0
          AND ABS(m."{col}" - ss.mean) / ss.stddev > %s
    """, (MIN_NINETIES, MIN_NINETIES, Z_SCORE_THRESHOLD))
    low_minutes_would_be_flagged = cur.fetchone()[0]

    if real_outliers or low_minutes_would_be_flagged:
        print(f"\n--- {col} ---")
        if real_outliers:
            print(f"  Real outliers (nineties >= {MIN_NINETIES}, z > {Z_SCORE_THRESHOLD}):")
            for name, team, season, val, nineties, mean, stddev, z in real_outliers:
                print(f"    {name} ({team}, {season}): {val} "
                      f"(nineties={nineties:.1f}, season mean={mean:.2f}, z={z:.1f})")
        if low_minutes_would_be_flagged:
            print(f"  Low-minutes rows correctly excluded from baseline "
                  f"(would've been flagged without the floor): {low_minutes_would_be_flagged}")


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        cols = get_per90_columns(cur)
        print(f"Auditing {len(cols)} per-90 columns in master_player_season_stats "
              f"(minutes floor: fbref_nineties >= {MIN_NINETIES}).")
        for col in cols:
            audit_per90(cur, col)
    conn.close()
    print(f"\nDone. Columns with neither a real outlier nor an excluded "
          f"low-minutes flag printed nothing above -- those are clean.")


if __name__ == "__main__":
    main()
