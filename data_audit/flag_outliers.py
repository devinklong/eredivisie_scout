"""
Flags statistically extreme values for manual review, as a PERSISTENT
table -- not console output that vanishes after one run. Same
reviewable-queue pattern this project already used for entity
resolution (fbref_whoscored_review_queue.csv etc.): every flagged row
gets empty reviewed/explanation columns for a human to fill in, and
re-running this script preserves any decision already made (merge-safe,
same as the entity-resolution review queues) rather than wiping it out.

METHODOLOGY: z-score against that column's OWN SEASON mean (never a
single global threshold across 2010-2025 -- era/tempo differences make
a global number meaningless, same reasoning as
pipelines/audits/audit_data_quality.py). Z_SCORE_THRESHOLD is
deliberately high (5.0, stricter than the 4.0 used elsewhere in this
project) since the ask here is "flag MASSIVE outliers for review," not
"flag anything mildly unusual" -- a lower threshold would flag most of
this league's real elite performers every single time, which isn't
useful as a review queue.

FIXED (2026-09-21), based on real evidence from the first run: a
MIN_NINETIES floor is now applied to EVERY numeric column, not just
_pct/_per90 ones, and raised from 1.0 to 5.0. The first run's top-20
most-flagged player-seasons all turned out to sit at fbref_nineties
between 0.0 and 0.5 (under 45 real minutes, several in single digits)
-- one of them (Maximiliano Romero, PSV 2020) had EXACTLY 0.0 nineties
and still got flagged on raw counting stats, since the old version
only applied the floor to rate-shaped columns. A player with
essentially no recorded minutes can still have a nonzero raw count
(one goal, one shot) that reads as statistically extreme purely
because almost nobody else in that season has so little playing time
-- that's not "a massive outlier worth reviewing," it's an artifact of
an unfiltered tiny sample, for counting stats exactly as much as for
rates. 5.0 nineties (~450 minutes, a real sample) is the new floor,
applied everywhere.

FIXED (2026-09-23), two more real gaps found during outlier review:
  1. fbref_minutes_per_sub/fbref_minutes_per_start have a different
     real denominator (substitute_appearances / starts, not total
     minutes) -- the universal nineties floor never protected these.
     Now use their own floor via SPECIAL_DENOMINATOR_FLOORS.
  2. fbref_on_off's near-zero season variance made its z-score
     hypersensitive, flagging real stars and unknowns alike at
     similarly extreme scores. Excluded from z-score detection
     entirely (EXCLUDE_NEAR_ZERO_VARIANCE) until a real fix (a
     percentile-based or CoV-aware method) gets built -- this is a
     documented placeholder, not a general solution.

Before treating anything this flags as a bug: check
data_audit/known_issues.md first. Most extreme values are one of two
things -- a genuine elite performance (leave alone, mark reviewed with
a note), or something already explained there (same). Only a
genuinely new, unexplained pattern needs real investigation.
"""

import csv
from pathlib import Path

import psycopg2

VIEW_TABLE = "master_player_season_stats"
RESULTS_DIR = Path(__file__).parent / "results"
Z_SCORE_THRESHOLD = 5.0
MIN_NINETIES = 5.0  # ~450 minutes -- a real sample, applied to every column

# Some columns' real denominator ISN'T total minutes played --
# fbref_minutes_per_sub is an average over substitute_appearances, not
# nineties, so a player can clear the nineties floor easily while
# still having only 1-2 sub appearances behind this specific rate.
# Confirmed real 2026-09-23: 3 players all landed here with extreme
# z-scores purely from a tiny appearance count. fbref_minutes_per_start
# has the identical structural risk (denominator is starts, not
# nineties) even though it hadn't been flagged yet -- fixed proactively
# rather than waiting for it to show up on its own.
SPECIAL_DENOMINATOR_FLOORS = {
    "fbref_minutes_per_sub": ("fbref_substitute_appearances", 3),
    "fbref_minutes_per_start": ("fbref_starts", 3),
}

# fbref_on_off has a near-zero season stddev, which makes the z-score
# formula hypersensitive -- confirmed 2026-09-23: 8 flagged rows mixed
# genuine stars with unknown players at similarly wild z-scores (11-14),
# proving the METRIC's scale is the problem, not 8 real anomalies.
# Excluded from z-score detection entirely until a proper fix (a
# percentile-based or coefficient-of-variation-aware method) is built --
# this is a known placeholder, not a general solution to near-zero-
# variance columns. If another column shows this same symptom (a
# flagged list mixing obvious stars with total unknowns at similarly
# extreme z-scores), it likely needs the same treatment -- add it here
# rather than guessing a universal threshold that hasn't been tested
# against this project's actual column-scale diversity.
EXCLUDE_NEAR_ZERO_VARIANCE = {"fbref_on_off"}


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def get_numeric_columns(cur):
    """Only numeric columns can have an outlier in the statistical
    sense -- text/boolean columns are excluded automatically. Also
    excludes obvious key/ID columns even if numeric."""
    cur.execute(f"""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = '{VIEW_TABLE}'
        AND data_type IN ('integer', 'numeric', 'smallint', 'bigint', 'double precision', 'real')
        ORDER BY ordinal_position
    """)
    # fbref_born excluded: a birth year isn't a performance stat --
    # z-scoring it just flags very young/old players, not an anomaly.
    exclude = {"player_id", "season_id", "fbref_born"}
    cols = [r[0] for r in cur.fetchall() if r[0] not in exclude]

    domains = {}
    for col in cols:
        if col.startswith("fbref_"):
            domains[col] = "fbref"
        elif col.startswith("ws_"):
            domains[col] = "ws"
        elif col.startswith("tm_"):
            domains[col] = "tm"
        elif col.startswith("gk_"):
            domains[col] = "gk"
    return domains


def ensure_review_table(cur):
    """CREATE TABLE IF NOT EXISTS, not DROP+CREATE -- this table holds
    human review decisions that must survive a re-run, same as the
    entity-resolution review queues."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS flagged_outliers (
            flag_id SERIAL PRIMARY KEY,
            column_name TEXT NOT NULL,
            domain TEXT NOT NULL,
            player_id INTEGER,
            canonical_name TEXT,
            team TEXT,
            season_id INTEGER,
            value NUMERIC,
            season_mean NUMERIC,
            season_stddev NUMERIC,
            z_score NUMERIC,
            flagged_at TIMESTAMP NOT NULL DEFAULT now(),
            reviewed BOOLEAN NOT NULL DEFAULT FALSE,
            explanation TEXT,
            UNIQUE (column_name, player_id, team, season_id)
        )
    """)


def flag_column(cur, column_name, domain):
    # Skip entirely -- see EXCLUDE_NEAR_ZERO_VARIANCE's definition for
    # why a z-score isn't a meaningful check for these columns.
    if column_name in EXCLUDE_NEAR_ZERO_VARIANCE:
        return 0

    # Some columns' real denominator isn't total minutes -- use that
    # column's own floor instead of the default nineties one.
    # See SPECIAL_DENOMINATOR_FLOORS's definition for why.
    if column_name in SPECIAL_DENOMINATOR_FLOORS:
        floor_col, floor_val = SPECIAL_DENOMINATOR_FLOORS[column_name]
        minutes_floor_clause = f'AND "{floor_col}" >= {floor_val}'
    else:
        # Floor applied to EVERY other column, not just rate-shaped
        # ones -- see module docstring for why (Maximiliano Romero's
        # 0.0-nineties row still tripping raw counting stats is what
        # proved this was needed everywhere, not just for _pct/_per90).
        minutes_floor_clause = f"AND fbref_nineties >= {MIN_NINETIES}"

    keeper_clause = "AND fbref_position LIKE '%%GK%%'" if domain == "gk" else ""

    query = f"""
        WITH season_stats AS (
            SELECT season_id, AVG("{column_name}") AS mean, STDDEV("{column_name}") AS stddev
            FROM {VIEW_TABLE}
            WHERE "{column_name}" IS NOT NULL
            {minutes_floor_clause}
            {keeper_clause}
            GROUP BY season_id
        )
        SELECT m.player_id, m.canonical_name, m.team, m.season_id,
               m."{column_name}", ss.mean, ss.stddev,
               ABS(m."{column_name}" - ss.mean) / ss.stddev AS z_score
        FROM {VIEW_TABLE} m
        JOIN season_stats ss ON ss.season_id = m.season_id
        WHERE m."{column_name}" IS NOT NULL
          AND ss.stddev > 0
          {minutes_floor_clause}
          {keeper_clause}
          AND ABS(m."{column_name}" - ss.mean) / ss.stddev > %s
    """
    cur.execute(query, (Z_SCORE_THRESHOLD,))
    rows = cur.fetchall()

    inserted = 0
    for player_id, canonical_name, team, season_id, value, mean, stddev, z in rows:
        cur.execute("""
            INSERT INTO flagged_outliers
                (column_name, domain, player_id, canonical_name, team, season_id,
                 value, season_mean, season_stddev, z_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (column_name, player_id, team, season_id) DO UPDATE SET
                value = EXCLUDED.value,
                season_mean = EXCLUDED.season_mean,
                season_stddev = EXCLUDED.season_stddev,
                z_score = EXCLUDED.z_score,
                flagged_at = now()
            -- reviewed/explanation deliberately NOT overwritten -- a
            -- human decision on this exact cell survives a re-run.
        """, (column_name, domain, player_id, canonical_name, team, season_id,
              value, mean, stddev, z))
        inserted += 1
    return inserted


def clear_stale_unreviewed(cur):
    """ON CONFLICT DO UPDATE (in flag_column) only adds/updates rows --
    it never removes ones that no longer meet the current criteria
    (e.g. after MIN_NINETIES or Z_SCORE_THRESHOLD changes). Without
    this, a stale flag from an earlier, looser run would sit in the
    table forever. Only clears reviewed = FALSE rows -- anything a
    human has already reviewed is preserved regardless of whether it'd
    still be flagged under the current criteria."""
    cur.execute("DELETE FROM flagged_outliers WHERE reviewed = FALSE")
    cleared = cur.rowcount
    if cleared:
        print(f"Cleared {cleared} stale unreviewed flag(s) from a previous run "
              f"before re-scanning.")


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        ensure_review_table(cur)
        clear_stale_unreviewed(cur)
        domains = get_numeric_columns(cur)
        print(f"Scanning {len(domains)} numeric columns "
              f"(z-score threshold: {Z_SCORE_THRESHOLD}, "
              f"minutes floor: {MIN_NINETIES} nineties, applied to all columns)...")

        total_flagged = 0
        for column_name, domain in domains.items():
            n = flag_column(cur, column_name, domain)
            if n > 0:
                print(f"  {column_name}: {n} flagged")
            total_flagged += n

        conn.commit()

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = RESULTS_DIR / "flagged_outliers.csv"
        # Exports the FULL current table, not just this run's new flags --
        # includes any reviewed/explanation decisions already made in a
        # prior run, so the CSV always reflects the real, current state.
        cur.execute("""
            SELECT flag_id, column_name, domain, player_id, canonical_name, team, season_id,
                   value, season_mean, season_stddev, z_score, flagged_at, reviewed, explanation
            FROM flagged_outliers
            ORDER BY reviewed ASC, z_score DESC
        """)
        rows = cur.fetchall()
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["flag_id", "column_name", "domain", "player_id", "canonical_name",
                              "team", "season_id", "value", "season_mean", "season_stddev",
                              "z_score", "flagged_at", "reviewed", "explanation"])
            writer.writerows(rows)
        print(f"Exported {len(rows)} total rows (all-time, not just this run) to {out_path}")

    print(f"\n{total_flagged} total (column, player, team, season) cells flagged")
    print("\nCheck data_audit/known_issues.md before investigating any of these --")
    print("most will be a real elite performance or an already-documented gap.")
    print("\nWork through the queue:")
    print("  SELECT * FROM flagged_outliers WHERE reviewed = FALSE ORDER BY z_score DESC;")
    print("  -- mark one reviewed:")
    print("  UPDATE flagged_outliers SET reviewed = TRUE, explanation = '...' WHERE flag_id = <id>;")

    conn.close()


if __name__ == "__main__":
    main()
