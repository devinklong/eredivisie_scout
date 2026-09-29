"""
Cross-references the coverage matrices against documented, already-
explained gaps -- so a low pct_populated cell in season_column_coverage/
team_column_coverage/player_column_coverage doesn't require manually
checking known_issues.md by hand for every row. Adds two columns to
each table: explanation_tier ('explained' / 'likely_explained' /
'unexplained') and explanation (the reasoning, or NULL for unexplained
cells that genuinely need a human look).

DELIBERATE DESIGN CHOICE: the FBref 2010-2017 historical gap
(documented in known_issues.md) is detected from the REAL DATA
directly -- low coverage in that season range for fbref_-domain
columns -- rather than a hardcoded list of exact column names copied
from memory. Real evidence from tonight's outlier review contradicted
part of that documented list (fbref_goals_per90 had real, populated
2011 data for at least one player), so hardcoding a possibly-wrong
column list risked suppressing attention on something genuinely worth
investigating. Detecting the PATTERN instead (season range + domain +
near-zero coverage) self-corrects regardless of whether the prose
description in known_issues.md is exactly right about which columns.

TIER 1 (explained, high confidence, structural/deterministic):
  - season_id < 2013 AND domain = 'ws' -- WhoScored has zero coverage
    before 2013-14, documented and structurally certain, not a
    pattern match.

TIER 2 (likely_explained, pattern-matched against documented findings,
not proof for this specific cell):
  - domain = 'fbref' AND season_id BETWEEN 2010 AND 2017 AND
    pct_populated < 10 -- matches the SHAPE of the documented FBref
    2010-2017 gap (see known_issues.md) without asserting the exact
    column list from memory.
  - domain = 'ws' AND season_id >= 2013 AND pct_populated BETWEEN 20
    AND 60 -- consistent with the documented ~30-45% baseline
    WhoScored crosswalk gap, not confirmed as THIS specific cell.

TIER 3 (unexplained): everything else below a low-coverage threshold
that doesn't match tier 1/2 -- these are the ones actually worth
looking at.

LIMITATION, stated plainly rather than hidden: team_column_coverage
and player_column_coverage aggregate across ALL seasons for a given
team/player, so the season-based rules above don't map cleanly onto
them the way they do for season_column_coverage. Those two tables get
a softer, explicitly-labeled heuristic instead -- for anything low and
in the ws/fbref domain, a note pointing back to season_column_coverage
for the precise per-season breakdown, rather than a confident
explanation this script can't actually verify at that grain.
"""

import csv
from pathlib import Path

import psycopg2

RESULTS_DIR = Path(__file__).parent / "results"

# Below this, a cell is worth classifying at all (explained or not) --
# above it, coverage is fine and doesn't need annotation either way.
LOW_COVERAGE_THRESHOLD = 80.0


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def ensure_annotation_columns(cur, table_name):
    cur.execute(f"""
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS explanation_tier TEXT,
        ADD COLUMN IF NOT EXISTS explanation TEXT
    """)


def annotate_season_coverage(cur):
    """Full two-tier annotation -- season_column_coverage has a real
    season_id in group_key, so both season-based rules apply cleanly."""
    ensure_annotation_columns(cur, "season_column_coverage")

    # Reset before re-annotating, so a re-run reflects current rules,
    # not stale ones from a previous version of this script.
    cur.execute("UPDATE season_column_coverage SET explanation_tier = NULL, explanation = NULL")

    # Tier 1: pre-2013 WhoScored, deterministic.
    cur.execute("""
        UPDATE season_column_coverage
        SET explanation_tier = 'explained',
            explanation = 'No WhoScored coverage before 2013-14 -- documented, structural, not a data problem.'
        WHERE domain = 'ws' AND group_key::integer < 2013
    """)
    tier1 = cur.rowcount

    # Tier 2a: FBref 2010-2017 gap shape, detected from real coverage numbers.
    cur.execute("""
        UPDATE season_column_coverage
        SET explanation_tier = 'likely_explained',
            explanation = 'Matches the shape of the documented FBref 2010-2017 historical data gap (see known_issues.md) -- near-zero coverage in exactly that season range and domain. Detected from actual coverage numbers, not a hardcoded column list -- worth a quick individual confirmation if this is being relied on for a specific column, not just accepted blind.'
        WHERE domain = 'fbref' AND group_key::integer BETWEEN 2010 AND 2017
          AND pct_populated < 10 AND explanation_tier IS NULL
    """)
    tier2a = cur.rowcount

    # Tier 2b: WhoScored baseline crosswalk gap shape.
    cur.execute("""
        UPDATE season_column_coverage
        SET explanation_tier = 'likely_explained',
            explanation = 'Consistent with the documented ~30-45% baseline WhoScored crosswalk coverage gap (see known_issues.md) -- not confirmed as this specific cell, but falls within the known structural range.'
        WHERE domain = 'ws' AND group_key::integer >= 2013
          AND pct_populated BETWEEN 20 AND 60 AND explanation_tier IS NULL
    """)
    tier2b = cur.rowcount

    # Tier 3: still low, doesn't match either pattern -- genuinely worth a look.
    cur.execute(f"""
        UPDATE season_column_coverage
        SET explanation_tier = 'unexplained'
        WHERE pct_populated < {LOW_COVERAGE_THRESHOLD} AND explanation_tier IS NULL
    """)
    tier3 = cur.rowcount

    print(f"  season_column_coverage: {tier1} explained (tier 1), "
          f"{tier2a + tier2b} likely_explained (tier 2), {tier3} unexplained")


def annotate_blended_coverage(cur, table_name):
    """Softer heuristic for team/player tables -- these aggregate
    across all seasons, so the season-based rules can't apply cleanly.
    See module docstring's LIMITATION note."""
    ensure_annotation_columns(cur, table_name)
    cur.execute(f"UPDATE {table_name} SET explanation_tier = NULL, explanation = NULL")

    cur.execute(f"""
        UPDATE {table_name}
        SET explanation_tier = 'unexplained_blended',
            explanation = 'Low coverage in a domain/season-sensitive column, but this table blends all seasons together -- check season_column_coverage for this column for the real per-season breakdown before treating this as a new finding.'
        WHERE domain IN ('ws', 'fbref') AND pct_populated < {LOW_COVERAGE_THRESHOLD}
    """)
    flagged = cur.rowcount

    print(f"  {table_name}: {flagged} rows flagged 'unexplained_blended' "
          f"(needs season_column_coverage cross-reference, not a direct answer)")


def export_table_to_csv(cur, table_name, columns_sql):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{table_name}.csv"
    cur.execute(f"SELECT {columns_sql} FROM {table_name} ORDER BY group_key, pct_populated ASC")
    rows = cur.fetchall()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns_sql.replace(" ", "").split(","))
        writer.writerows(rows)
    print(f"  Re-exported {len(rows)} rows to {out_path}")


def add_canonical_team_name(cur):
    """team_column_coverage.group_key currently holds FBref's raw team
    spelling (e.g. 'Sparta R.') since master_player_season_stats is
    FBref-anchored and was never rewritten to one consistent name.
    Adds a canonical_team column resolved through team_name_alias back
    to Transfermarkt's canonical spelling, so team-level results are
    human-readable without needing to know FBref's specific naming
    quirks for each club."""
    cur.execute("""
        ALTER TABLE team_column_coverage
        ADD COLUMN IF NOT EXISTS canonical_team TEXT
    """)
    cur.execute("""
        UPDATE team_column_coverage tcc
        SET canonical_team = canon.source_name
        FROM team_name_alias fbref_alias
        JOIN team_name_alias canon ON canon.club_id = fbref_alias.club_id AND canon.source = 'transfermarkt'
        WHERE fbref_alias.source = 'fbref' AND fbref_alias.source_name = tcc.group_key
    """)
    updated = cur.rowcount
    print(f"  team_column_coverage: {updated} rows given a canonical_team name")


def main():
    conn = get_connection()
    with conn.cursor() as cur:
        print("Annotating season_column_coverage (full two-tier rules)...")
        annotate_season_coverage(cur)

        print("Annotating team_column_coverage (blended-seasons heuristic)...")
        annotate_blended_coverage(cur, "team_column_coverage")

        print("Adding canonical_team display names...")
        add_canonical_team_name(cur)

        print("Annotating player_column_coverage (blended-seasons heuristic)...")
        annotate_blended_coverage(cur, "player_column_coverage")

        conn.commit()

        print("\nRe-exporting annotated CSVs...")
        export_table_to_csv(cur, "season_column_coverage",
            "group_key, column_name, domain, total_rows, non_null_rows, pct_populated, explanation_tier, explanation")
        export_table_to_csv(cur, "team_column_coverage",
            "group_key, canonical_team, column_name, domain, total_rows, non_null_rows, pct_populated, explanation_tier, explanation")
        export_table_to_csv(cur, "player_column_coverage",
            "group_key, canonical_name, column_name, domain, total_rows, non_null_rows, pct_populated, explanation_tier, explanation")

    conn.close()

    print("\nDone. Query the real remainder directly, e.g.:")
    print("  SELECT * FROM season_column_coverage WHERE explanation_tier = 'unexplained' ORDER BY pct_populated;")
    print("  SELECT * FROM team_column_coverage WHERE explanation_tier = 'unexplained_blended' ORDER BY pct_populated;")


if __name__ == "__main__":
    main()
