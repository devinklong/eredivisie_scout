"""
Step 1 of the modeling pipeline: position-relative normalization.

Turns each outfield player-season's raw style stats into PERCENTILES within the
players who played the same position group in the same season. A raw stat mostly
measures role: the audit found ws_touches_def_pen_area flagged 31 of 31 outliers
as keepers, so across all positions it says "is he a keeper". A percentile
within position asks how unusual he is among his own kind. Output feeds step 2
(archetype clustering); outcome stats (goals, assists, efficiency) are NOT
normalized here and go to the valuation model only.

WHAT IS RANKED
  - Rows with fbref_nineties >= 5.0 (below that, per-90 rates are noise).
  - Outfield players only, grouped by PRIMARY position, the first token of
    fbref_position (as I understand FBref's convention the main position is
    listed first): DF, MF, FW. Goalkeepers are left out of v1: about 25 a
    season is too few for stable percentiles, and gk_* stats against outfield
    stats splits them trivially.
  - One row per player-season. A player who moved clubs mid-season has two rows;
    the one with the most nineties is kept (ties broken by team name so the choice
    is deterministic) and the number of such player-seasons is reported.
  - Percentile within (season, primary position), i.e. same-season only, using the
    mean percentile rank (L + 0.5 * E) / N, which treats ties fairly (many
    defenders have exactly 0 att-pen-area touches) and never hands the top
    player exactly 100.

WHAT IS GUARDED (a percentile can be quietly wrong without any error)
  - RATES need a minimum number of attempts: a defender who wins 3 of 3 take-ons
    is not the best dribbler. See RATE_GUARDS.
  - A feature needs at least MIN_GROUP_SIZE non-null values in a group-season
    to be ranked there. Missing data (WhoScored before 2013, FBref misc in 2018)
    leaves NULL rather than a ranking of a handful of survivors.
  - A position-season group smaller than MIN_GROUP_SIZE raises GroupTooSmall.
  - tm_height_cm outside 150-215 is nulled and reported (two known bad rows read
    875).

SHOTS ARE DERIVED, NOT TAKEN FROM FBref'S PER-90 COLUMN (found on the first real
run, 2026-10-06). The shots fix (fix_shots_with_whoscored_derivation.sql) repaired
the raw count fbref_shots (WhoScored-derived from 2013, NULL before) but never
touched fbref_shots_per90, which the loader takes from FBref as-is. FBref returns a
literal 0, not NULL, for shots in 2016 and 2017, so that column was present but
constant in exactly those seasons and ranking it gave everyone exactly 50. So the
feature is derived_shots_per90 = fbref_shots / fbref_nineties, from the repaired
count.

CONSTANT FEATURES ARE NULLED, NOT RANKED: a feature whose values in a group-season
are all identical carries no information, and ties give everyone the midpoint. That
is the shots trap above, in general form, and it is reported by name.

LEFT OUT OF v1: ws_ground_duel_win_pct. It has no attempt count to guard it
with. If its definition is known it can come back with a guard.

NULLs are never imputed. The table is derived and fully rebuilt on every run.

Usage:
    python pipelines/modeling/build_style_percentiles.py
"""

import sys

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

MIN_NINETIES = 5.0
OUTFIELD_GROUPS = ("DF", "MF", "FW")
MIN_GROUP_SIZE = 30
HEIGHT_BOUNDS_CM = (150, 215)
OUT_TABLE = "player_season_style_percentiles"

STYLE_FEATURES = [
    # where he operates
    "ws_touches_per90", "ws_touches_def_3rd_per90", "ws_touches_mid_3rd_per90",
    "ws_touches_att_3rd_per90", "ws_touches_def_pen_area_per90", "ws_touches_att_pen_area_per90",
    # passing and progression
    "ws_passes_per90", "ws_passes_pct", "ws_final_third_entries_per90", "ws_pen_area_entries_per90",
    # dribbling
    "ws_take_ons_per90", "ws_take_ons_won_pct", "ws_dispossessed_per90",
    # defending
    "ws_tackles_per90", "ws_tackles_def_3rd_per90", "ws_tackles_mid_3rd_per90", "ws_tackles_att_3rd_per90",
    "ws_interceptions_per90", "ws_interceptions_def_3rd_per90", "ws_interceptions_mid_3rd_per90",
    "ws_interceptions_att_3rd_per90", "ws_clearances_per90", "ws_dribbled_past_per90",
    # duels
    "ws_aerials_per90", "ws_aerial_duel_win_pct",
    # attacking habits (shots derived from the repaired count, the rest FBref)
    "derived_shots_per90", "fbref_crosses_per90", "fbref_offsides_per90",
    "fbref_fouls_drawn_per90", "fbref_fouls_committed_per90",
    # physical
    "tm_height_cm",
]

# rate feature -> (its attempts column, minimum attempts before it is ranked)
RATE_GUARDS = {
    "ws_passes_pct": ("ws_passes", 100),
    "ws_take_ons_won_pct": ("ws_take_ons", 10),
    "ws_aerial_duel_win_pct": ("ws_aerials", 10),
}
GUARD_COLUMNS = sorted({col for col, _ in RATE_GUARDS.values()})
# feature -> the raw count column it is derived from (divided by fbref_nineties)
DERIVED_FEATURES = {"derived_shots_per90": "fbref_shots"}
RAW_FEATURES = [f for f in STYLE_FEATURES if f not in DERIVED_FEATURES]
# The CLUSTERING vector (step 2) holds what a player DOES (volume, zone, habit). How WELL he does it
# (the success rates) and physical attributes go to the valuation model, which accepts NULLs. Left out of
# the clustering vector, and why, from the first real readiness report (2026-10-06):
#   FBref misc: crosses, offsides and fouls drawn are real only from 2019 (FBref zeros in 2016-2017, NULL
#     before and in 2018), fouls committed is missing in 2018.
#   The three success rates: skill not style, the ones needing attempt guards, 23% / 4.4% / 0.2% NULL.
#   tm_height_cm: physical not style, 31.8% NULL because Transfermarkt bio coverage reaches only
#     crosswalk-linked players (44% NULL in 2017, 14% in 2025), a data-linkage artifact not a player trait.
# Clustering cannot take NULLs, so everything left should be nearly complete for stat seasons 2013-2025.
FBREF_MISC_EXCLUDED = ["fbref_crosses_per90", "fbref_offsides_per90",
                       "fbref_fouls_drawn_per90", "fbref_fouls_committed_per90"]
RATE_FEATURES = list(RATE_GUARDS)
HEIGHT_FEATURE = "tm_height_cm"
V1_FEATURES = [f for f in STYLE_FEATURES if f not in FBREF_MISC_EXCLUDED]     # the 27-feature vector of the first readiness report
CLUSTERING_FEATURES = [f for f in V1_FEATURES if f not in RATE_FEATURES and f != HEIGHT_FEATURE]
CLUSTERING_FIRST_SEASON = 2013          # WhoScored starts in 2013
ID_COLUMNS = ["player_id", "canonical_name", "team", "season_id", "fbref_position", "fbref_nineties"]
READ_COLUMNS = list(dict.fromkeys(ID_COLUMNS + RAW_FEATURES + sorted(DERIVED_FEATURES.values()) + GUARD_COLUMNS))


class GroupTooSmall(Exception):
    """A (season, position) group has too few qualifying players to rank."""


def primary_position(pos):
    """'FW,MF' -> 'FW'. Blank or missing -> None."""
    if pos is None or (isinstance(pos, float) and np.isnan(pos)):
        return None
    first = str(pos).split(",")[0].strip().upper()
    return first or None


def pick_dominant_rows(df):
    """One row per (player_id, season_id): the one with the most nineties, ties
    broken by team name. Returns (rows, number_of_player_seasons_with_2+_rows)."""
    ordered = df.sort_values(["player_id", "season_id", "fbref_nineties", "team"],
                             ascending=[True, True, False, True], kind="mergesort")
    n_multi = int((ordered.groupby(["player_id", "season_id"]).size() > 1).sum())
    kept = ordered.drop_duplicates(["player_id", "season_id"], keep="first").reset_index(drop=True)
    return kept, n_multi


def mean_percentile_rank(values):
    """Series -> 0-100 mean percentile rank, (L + 0.5E)/N, NaN stays NaN and is
    not counted in N."""
    n = values.notna().sum()
    if n == 0:
        return values.astype(float)
    return (values.rank(method="average") - 0.5) / n * 100.0


def add_derived(df):
    """Adds the derived per-90 features. A non-positive nineties value gives NaN."""
    out = df.copy()
    nineties = out["fbref_nineties"].where(out["fbref_nineties"] > 0)
    for feat, count_col in DERIVED_FEATURES.items():
        out[feat] = out[count_col] / nineties
    return out


def apply_guards(df):
    """Nulls rate features with too few attempts and heights outside the sane
    range. Returns (guarded_df, report)."""
    out = df.copy()
    report = {"rates_nulled": {}, "bad_heights": []}
    for feat, (count_col, minimum) in RATE_GUARDS.items():
        too_few = out[feat].notna() & (out[count_col].fillna(0) < minimum)
        report["rates_nulled"][feat] = int(too_few.sum())
        out.loc[too_few, feat] = np.nan
    lo, hi = HEIGHT_BOUNDS_CM
    bad = out["tm_height_cm"].notna() & ~out["tm_height_cm"].between(lo, hi)
    report["bad_heights"] = [(int(r.player_id), float(r.tm_height_cm)) for r in out[bad].itertuples()]
    out.loc[bad, "tm_height_cm"] = np.nan
    return out, report


def build_percentiles(raw, features=STYLE_FEATURES, min_group_size=MIN_GROUP_SIZE):
    """raw: rows of master_player_season_stats (any position, any minutes).
    Returns (result, report). result has one row per qualifying player-season
    and a pct_<feature> column for each feature."""
    report = {"input_rows": len(raw)}
    df = raw[raw["player_id"].notna()].copy()
    report["with_canonical_player"] = len(df)
    df["primary_position"] = df["fbref_position"].map(primary_position)

    df, n_multi = pick_dominant_rows(df)
    report["multi_row_player_seasons"] = n_multi
    report["player_seasons"] = len(df)

    df = df[df["fbref_nineties"] >= MIN_NINETIES]
    report["after_nineties_floor"] = len(df)
    df = df[df["primary_position"].isin(OUTFIELD_GROUPS)].copy()
    report["after_outfield_only"] = len(df)

    sizes = df.groupby(["season_id", "primary_position"]).size()
    small = sizes[sizes < min_group_size]
    if len(small):
        raise GroupTooSmall(f"{len(small)} (season, position) group(s) below {min_group_size} qualifying "
                            f"players: {small.to_dict()}")
    df["group_size"] = df.groupby(["season_id", "primary_position"])["player_id"].transform("size")

    df = add_derived(df)
    df, guard_report = apply_guards(df)
    report.update(guard_report)

    keys = ["season_id", "primary_position"]
    report["constant_features"] = {}
    for feat in features:
        grouped = df.groupby(keys)[feat]
        pct = grouped.transform(mean_percentile_rank)
        enough = grouped.transform("count") >= min_group_size
        constant = enough & (grouped.transform("nunique") <= 1)          # all values identical: no information
        if constant.any():
            report["constant_features"][feat] = sorted(int(x) for x in df.loc[constant, "season_id"].unique())
        df["pct_" + feat] = pct.where(enough & ~constant).round(1)

    pct_cols = ["pct_" + f for f in features]
    result = df[["player_id", "season_id", "canonical_name", "team", "primary_position",
                 "fbref_nineties", "group_size"] + pct_cols].rename(columns={"fbref_nineties": "nineties"})
    return result.sort_values(["season_id", "primary_position", "player_id"]).reset_index(drop=True), report


def coverage_by_season(result, features=STYLE_FEATURES):
    """Share of ranked rows with at least one ranked WhoScored / FBref feature, per season."""
    ws = ["pct_" + f for f in features if f.startswith("ws_")]
    fb = ["pct_" + f for f in features if f.startswith("fbref_")]
    flags = pd.DataFrame({"season_id": result["season_id"],
                          "with_whoscored": result[ws].notna().any(axis=1),
                          "with_fbref": result[fb].notna().any(axis=1)})
    out = flags.groupby("season_id").agg(rows=("with_whoscored", "size"),
                                         with_whoscored=("with_whoscored", "mean"),
                                         with_fbref=("with_fbref", "mean"))
    return out


def clustering_readiness(result, first_season=CLUSTERING_FIRST_SEASON, features=CLUSTERING_FEATURES):
    """Ranked rows from first_season on whose clustering vector is COMPLETE (no NULL percentile), next to
    how many would be complete under the earlier 27-feature vector that also required the three success
    rates and height. Clustering cannot take NULLs, so this is what the vector choice costs."""
    r = result[result["season_id"] >= first_season]
    flags = pd.DataFrame({"season_id": r["season_id"].values,
                          "complete": r[["pct_" + f for f in features]].notna().all(axis=1).values,
                          "complete_27_feature_vector": r[["pct_" + f for f in V1_FEATURES]].notna().all(axis=1).values})
    out = flags.groupby("season_id").agg(ranked=("complete", "size"), complete=("complete", "sum"),
                                         complete_27_feature_vector=("complete_27_feature_vector", "sum"))
    total = out.sum()
    out.index = out.index.astype(str)
    out.loc["ALL"] = total
    return out.astype(int)


def null_share_by_feature(result, features=V1_FEATURES, first_season=CLUSTERING_FIRST_SEASON):
    """For each clustering feature, the share of ranked rows (from first_season on) with a NULL
    percentile, overall and in its best and worst season, sorted worst first. This names WHICH feature
    is costing rows; clustering_readiness only says how many rows are incomplete."""
    r = result[result["season_id"] >= first_season]
    out = []
    for f in features:
        isnull = r["pct_" + f].isna()
        by_season = isnull.groupby(r["season_id"]).mean()
        out.append({"feature": f, "null_share": float(isnull.mean()),
                    "worst_season": int(by_season.idxmax()), "worst_share": float(by_season.max()),
                    "best_season": int(by_season.idxmin()), "best_share": float(by_season.min())})
    return pd.DataFrame(out).sort_values("null_share", ascending=False, kind="mergesort").reset_index(drop=True)


def empty_feature_seasons(result, features=STYLE_FEATURES):
    """Features with NO ranked value at all in some season, grouped by which
    seasons: {(seasons...): [features]}. Complete features are not listed. The
    'any feature' coverage above can hide a gap like FBref's 2018 misc stats, where
    most columns are fine and a few are empty, so this names them."""
    grouped = {}
    for f in features:
        has = (result.assign(_has=result["pct_" + f].notna()).groupby("season_id")["_has"].any())
        seasons = tuple(int(x) for x in sorted(has[~has].index))
        if seasons:
            grouped.setdefault(seasons, []).append(f)
    return grouped


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def read_raw(conn):
    cols = READ_COLUMNS
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(cols)} FROM master_player_season_stats")
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    for c in cols:
        if c not in ("canonical_name", "team", "fbref_position"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def table_ddl(features=STYLE_FEATURES):
    pct_cols = ",\n    ".join(f"pct_{f} NUMERIC(5,1)" for f in features)
    return f"""
    DROP TABLE IF EXISTS {OUT_TABLE};
    CREATE TABLE {OUT_TABLE} (
        player_id INTEGER NOT NULL,
        season_id INTEGER NOT NULL,
        canonical_name TEXT,
        team TEXT,
        primary_position TEXT NOT NULL,
        nineties NUMERIC(5,1) NOT NULL,
        group_size INTEGER NOT NULL,
        {pct_cols},
        PRIMARY KEY (player_id, season_id)
    );"""


def write_result(conn, result):
    cols = list(result.columns)
    values = [tuple(None if (isinstance(v, float) and np.isnan(v)) or v is pd.NA else
                    (int(v) if isinstance(v, (np.integer,)) else (float(v) if isinstance(v, np.floating) else v))
                    for v in row) for row in result.itertuples(index=False, name=None)]
    try:
        with conn.cursor() as cur:
            cur.execute(table_ddl())
            execute_values(cur, f"INSERT INTO {OUT_TABLE} ({', '.join(cols)}) VALUES %s", values)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def print_report(report, result):
    print(f"Rows read from master_player_season_stats:   {report['input_rows']}")
    print(f"  with a canonical player id:                {report['with_canonical_player']}")
    print(f"  player-seasons (one row each):             {report['player_seasons']}   "
          f"({report['multi_row_player_seasons']} had 2+ rows from a mid-season move; most-nineties row kept)")
    print(f"  with {MIN_NINETIES:g}+ nineties:                         {report['after_nineties_floor']}")
    print(f"  outfield (DF/MF/FW) = ranked:              {report['after_outfield_only']}")
    print("Rates nulled for too few attempts: " +
          ", ".join(f"{k}: {v}" for k, v in report["rates_nulled"].items()))
    if report["constant_features"]:
        print("Constant (all-identical) groups nulled, not ranked: " +
              "; ".join(f"{f} in {seasons}" for f, seasons in report["constant_features"].items()))
    if report["bad_heights"]:
        print(f"WARNING: {len(report['bad_heights'])} height(s) outside {HEIGHT_BOUNDS_CM} nulled: {report['bad_heights']}")
    print("\nRanked rows by position:")
    print(result.groupby("primary_position").size().to_string())
    print("\nCoverage by season (share of ranked rows with at least one ranked feature):")
    print(coverage_by_season(result).round(2).to_string())
    ready = clustering_readiness(result)
    print(f"\nClustering-ready rows (stat seasons {CLUSTERING_FIRST_SEASON}+): complete = all {len(CLUSTERING_FEATURES)} clustering features present; "
          f"the last column is the earlier {len(V1_FEATURES)}-feature vector that also required the success rates and height:")
    print(ready.to_string())
    print(f"  -> the {len(CLUSTERING_FEATURES)}-feature vector is complete for {ready.loc['ALL', 'complete'] / ready.loc['ALL', 'ranked']:.1%} of ranked rows "
          f"(+{int(ready.loc['ALL', 'complete'] - ready.loc['ALL', 'complete_27_feature_vector'])} rows over the {len(V1_FEATURES)}-feature vector)")
    nulls = null_share_by_feature(result)
    print(f"\nWhere the NULLs are (stat seasons {CLUSTERING_FIRST_SEASON}+, share of ranked rows with a NULL percentile; * = not in the clustering vector, kept for the valuation model):")
    shown = nulls[nulls["null_share"] > 0]
    if shown.empty:
        print("  none")
    for r in shown.head(10).itertuples():
        mark = " " if r.feature in CLUSTERING_FEATURES else "*"
        print(f" {mark}{r.feature:<34} {r.null_share:6.1%}   (worst {r.worst_season}: {r.worst_share:.0%}, best {r.best_season}: {r.best_share:.0%})")
    gaps = empty_feature_seasons(result)
    print("\nFeatures with NO ranked value in a season (the clustering step needs to know):")
    if not gaps:
        print("  none")
    for seasons, feats in sorted(gaps.items()):
        shown = ", ".join(feats[:4]) + (f", ... (+{len(feats) - 4} more)" if len(feats) > 4 else "")
        print(f"  seasons {list(seasons)}: {len(feats)} feature(s): {shown}")


def main():
    conn = get_connection()
    try:
        raw = read_raw(conn)
        result, report = build_percentiles(raw)
        print_report(report, result)
        write_result(conn, result)
        print(f"\nWrote {len(result)} rows to {OUT_TABLE}.")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except GroupTooSmall as e:
        sys.exit(f"STOPPED: {e}")
