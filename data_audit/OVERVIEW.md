# data_audit

Foundation-layer documentation of the eredivisie_scout dataset: not
"is this data wrong" (that's covered by `pipelines/audits/` and
`schema/entity_resolution/master_players_testing.sql`), but "how
complete is it, and for whatever's missing or unusual, is there a
known explanation." Built starting 2026-09-20 as the reference layer
future users of this dataset -- including a future modeling pass, or
anyone new to the project -- should be able to check instead of
re-discovering the same gaps from scratch.

## Structure

- `known_issues.md` -- the running reference of every EXPLAINED gap,
  structural limitation, or anomaly found across this project's whole
  history. Check here first before treating something as a new bug.
- `season/` -- coverage and (eventually) quality matrices at the
  season grain: for a given season, which columns are populated, for
  how many rows, and why (if known).
- `team/` -- same, at the team grain.
- `player/` -- same, at the player grain.

## Methodology: long-format coverage matrices, not a single blended %

An earlier version of this (see `pipelines/audits/audit_coverage.py`,
2026-09-20, superseded by this folder) computed one blended
"completeness %" per player/team/season across 4 domain buckets
(fbref/ws/tm/gk). That hides exactly the thing this audit needs to
answer: WHICH specific column is missing, for WHICH specific
player/team/season, and WHY. This folder replaces that approach with
long-format tables -- one row per (dimension value, column) -- so
coverage is queryable down to the exact cell, not just an aggregate.

Each of `season_column_coverage`, `team_column_coverage`,
`player_column_coverage` has this shape:

| column | meaning |
|---|---|
| `group_key` | the season_id / team / player_id this row describes |
| `column_name` | the specific master_player_season_stats column |
| `domain` | fbref / ws / tm / gk, from the column's naming prefix |
| `total_rows` | how many rows exist for this group_key |
| `non_null_rows` | how many of those have a real value in `column_name` |
| `pct_populated` | non_null_rows / total_rows * 100 |

Same `gk_*` exclusion rule as the earlier version: those columns are
only counted for rows that are actually goalkeepers
(`fbref_position LIKE '%GK%'`, the same real signal
`master_players_testing.sql` Section 9a confirmed) -- a non-keeper
correctly having no `gk_*` data isn't a gap, so it's excluded from
that row's denominator rather than counted as missing.

## NOT YET BUILT (next phase, see each subfolder's own notes)

The QUALITY half -- per-column outlier detection, organized at the
season/team/player grain, cross-referenced against `known_issues.md`
so a flagged outlier either links to an existing explanation or gets
added as a new one. `pipelines/audits/audit_data_quality.py` and
`audit_per90.py` already do outlier detection, but at the whole-table
grain, not organized per dimension the way this folder's coverage
matrices are. Bringing that logic into this folder, matrix-style, is
the next real chunk of work.
