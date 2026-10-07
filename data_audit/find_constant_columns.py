"""
Finds columns that look populated but carry no information, per season.

THE BLIND SPOT THIS CLOSES: the audit's coverage checks count NULLs, and a column
of zeros is 100% populated. FBref returns literal zeros (not NULL) for data it does
not have: shots in 2016-2017 (patch_list, 2026-09-14), and, found 2026-10-06,
crosses, offsides and fouls drawn in the same seasons. Ranking those columns gave
every player exactly 50. The audit called them "real values" because they were not
NULL. This is the same shape as the empty keeper table: zero findings is not the
same as healthy.

For every numeric column of master_player_season_stats, per season, among rows
with 5+ nineties, it reports:
  constant  every non-NULL value is identical (usually 0): a source gap in disguise
  empty     no non-NULL value at all
  sparse    some values, but fewer than MIN_ROWS: too few to rank or model
A season is only judged if it has at least MIN_ROWS rows in the relevant
population (MIN_ROWS_GK for the smaller goalkeeper population).

Populations: gk_* columns are judged on goalkeeper rows only, every other column on
outfield rows only, so a keeper column is not called empty because outfield players
have no keeper stats (the same convention the audit already used).

Not judged: ids, text, and the season itself. A constant value that is legitimately
rare is still reported (an all-zero own_goals column in a small season is plausible),
so read the output; it names suspects, it does not convict.

Writes the full detail to data_audit/results/constant_columns.csv and prints a
grouped summary.

Usage:
    python data_audit/find_constant_columns.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

MIN_NINETIES = 5.0
MIN_ROWS = 30
MIN_ROWS_GK = 15
NOT_JUDGED = {"canonical_name", "team", "fbref_nation", "fbref_position", "fbref_age", "tm_foot",
              "player_id", "ws_whoscored_player_id", "season_id", "fbref_born",
              "fbref_nineties"}      # the column the scan filters on, so judging it is circular
OUT_CSV = Path("data_audit/results/constant_columns.csv")


def primary_position(pos):
    if pos is None or (isinstance(pos, float) and np.isnan(pos)):
        return None
    first = str(pos).split(",")[0].strip().upper()
    return first or None


def judged_columns(df):
    return [c for c in df.columns if c not in NOT_JUDGED and pd.api.types.is_numeric_dtype(df[c])]


def scan(df, min_rows=MIN_ROWS, min_rows_gk=MIN_ROWS_GK, min_nineties=MIN_NINETIES):
    """Returns one row per (column, season) that is constant, empty or sparse."""
    d = df[df["fbref_nineties"] >= min_nineties]
    is_gk = d["fbref_position"].map(primary_position) == "GK"
    findings = []
    for col in judged_columns(d):
        gk_col = col.startswith("gk_")
        population = d[is_gk] if gk_col else d[~is_gk]
        threshold = min_rows_gk if gk_col else min_rows
        for season, g in population.groupby("season_id"):
            if len(g) < threshold:
                continue
            values = g[col].dropna()
            if len(values) == 0:
                kind, value = "empty", np.nan
            elif len(values) < threshold:
                kind, value = "sparse", np.nan
            elif values.nunique() == 1:
                kind, value = "constant", float(values.iloc[0])
            else:
                continue
            findings.append({"column": col, "season_id": int(season), "rows": len(g),
                             "non_null": len(values), "kind": kind, "value": value})
    return pd.DataFrame(findings, columns=["column", "season_id", "rows", "non_null", "kind", "value"])


def group_findings(findings):
    """Merges columns that share (kind, value, seasons): {(kind, value, seasons): [columns]}."""
    out = {}
    for col, g in findings.groupby("column"):
        for (kind, value), gg in g.groupby(["kind", g["value"].fillna(-1e18)]):
            seasons = tuple(sorted(int(s) for s in gg["season_id"]))
            shown = None if value == -1e18 else value
            out.setdefault((kind, shown, seasons), []).append(col)
    return out


def format_report(findings):
    if findings.empty:
        return "No constant, empty or sparse columns found."
    lines = []
    for kind in ("constant", "sparse", "empty"):
        groups = {k: v for k, v in group_findings(findings).items() if k[0] == kind}
        if not groups:
            continue
        lines.append(f"\n--- {kind.upper()}")
        for (_, value, seasons), cols in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0][2])):
            val = f" (value {value:g})" if kind == "constant" and value is not None else ""
            if kind == "constant":      # always name every one: these are the suspects that matter
                shown = ", ".join(sorted(cols))
            else:
                shown = ", ".join(sorted(cols)[:6]) + (f", ... (+{len(cols) - 6} more; full list in the CSV)" if len(cols) > 6 else "")
            lines.append(f"  seasons {list(seasons)}{val}: {len(cols)} column(s): {shown}")
    return "\n".join(lines)


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def read_master(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM master_player_season_stats")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    for c in cols:
        if c not in NOT_JUDGED:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["fbref_position"] = df["fbref_position"].astype(object)
    return df


def main():
    conn = get_connection()
    try:
        df = read_master(conn)
    finally:
        conn.close()
    findings = scan(df)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    findings.sort_values(["kind", "column", "season_id"]).to_csv(OUT_CSV, index=False)
    print(f"{len(df)} rows read; {len(judged_columns(df[df['fbref_nineties'] >= MIN_NINETIES]))} numeric columns judged; "
          f"{len(findings)} (column, season) findings -> {OUT_CSV}")
    print(format_report(findings))


if __name__ == "__main__":
    sys.exit(main())
