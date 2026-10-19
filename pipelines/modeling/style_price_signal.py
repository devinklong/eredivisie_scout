"""
Step 3 of the modeling pipeline: does playing style add price signal?

Archetype 1 sells for a median 5.0M against 1.0-2.4M for the others, but the big three
(Ajax, PSV, Feyenoord) sell far more of it, and they get higher fees for every archetype.
The only fair question is whether style predicts the fee AFTER the things a buyer already
sees: position, age, minutes, production, who is selling, who is buying, and when.

ONE ROW PER USABLE SALE: a paid Eredivisie sale from sale season 2014 on, whose player links
to a canonical id and has an archetype for the previous season (the stats a buyer would have
seen). The target is log(1 + fee in millions of euros).

FIVE ARMS, identical rows and identical folds:
  1 controls          position, age, minutes, production, sale season, seller in the big three,
                      the seller team's points per match while the player was on the pitch,
                      buyer league, prior buyer spend (before the sale's own season)
  2 + archetype       controls + the hard archetype (one-hot)
  3 + distances       controls + distance to each of the six centroids (soft assignment)
  4 + style axis      controls + the first principal component of the style percentiles
                      (fitted inside each training fold)
  5 + all percentiles controls + the 23 style percentiles
  6 + archetype x Big-5   arm 2 plus a Big-5-buyer flag and archetype x flag: the thesis itself (do Big-5
                      clubs pay a premium for certain styles?). Judged against ARM 2, not the controls, so
                      it cannot take credit for a main effect of style
  7 + style axis x Big-5  the same question for the PC1 axis, judged against arm 4
Two models per arm: ridge regression and a shallow gradient-boosted model. Trees find interactions on
their own, so for the gradient-boosted model the explicit products add little; the ridge model is where
the interaction arms have teeth.

TWO VALIDATION SCHEMES:
  grouped    repeated 5-fold, all of a player's sales in one fold (a player sold twice must not
             sit on both sides of a split)
  time       train on sale seasons up to 2021, test on 2022 on
A style arm only counts if it beats its baseline (the controls, or for arms 6 and 7 the same style
information without the interaction) under both.

LEAKAGE GUARD: the fee itself, the buyer page's fee and every share of the buyer's spend that
contains the fee (season and trailing windows end at the sale's own season) are forbidden as
features by name, and any feature that correlates with the target above 0.98 is refused too.
Only prior_season_* and prior_5yr_* buyer spend are used.

The centroids and archetypes come from clustering that never sees a fee, so reusing them
across folds leaks no price information. The principal component is refitted per fold anyway.

Usage:
    python pipelines/modeling/style_price_signal.py
    python pipelines/modeling/style_price_signal.py --repeats 20 --out data_audit/results/style_price_signal.csv
"""

import argparse
import sys
import warnings

import numpy as np
import pandas as pd
import psycopg2
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

try:
    import cluster_archetypes as ca
except ImportError:  # run from the repo root
    sys.path.insert(0, "pipelines/modeling")
    import cluster_archetypes as ca

SEED = 20261009
FIRST_SALE_SEASON = 2014
TIME_SPLIT_LAST_TRAIN_SEASON = 2021
# Transfermarkt club ids of the three sellers whose fees run 2-6x higher for every archetype.
# The report prints their names from eredivisie_club_status so a wrong id is visible.
BIG_THREE = {"Ajax": 610, "PSV": 383, "Feyenoord": 234}

FORBIDDEN_FEATURES = frozenset({
    "fee_amount", "log_fee", "buyer_page_fee",
    "pct_of_buyer_season_spend", "pct_of_buyer_5yr_spend",
    "season_paid_total", "season_paid_count", "trailing_5yr_paid_total", "trailing_5yr_paid_count",
})
MAX_TARGET_CORRELATION = 0.98

PCT_COLS = ["pct_" + f for f in ca.CLUSTERING_FEATURES]
CONTROL_NUMERIC = ["age", "log_nineties", "production", "sale_season", "seller_big3",
                   "seller_points_per_match", "log_prior_season_spend", "log_prior_5yr_spend"]
CONTROL_CATEGORICAL = ["primary_position", "buyer_league"]
CONTROL_COLUMNS = CONTROL_NUMERIC + CONTROL_CATEGORICAL
ARM_NAMES = {1: "controls", 2: "+ archetype", 3: "+ centroid distances", 4: "+ style axis (PC1)", 5: "+ 23 percentiles",
             6: "+ archetype x Big-5 buyer", 7: "+ style axis x Big-5 buyer"}
# Each arm is judged against the arm that has the same style information WITHOUT the interaction, so an
# interaction arm cannot take credit for a main effect: 6 against 2, 7 against 4; every other arm against 1.
BASELINE_ARM = {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2, 7: 4}
BIG5_LEAGUES = frozenset({"GB1", "ES1", "IT1", "L1", "FR1"})      # Transfermarkt competition codes


DATASET_SQL = """
WITH tm_link AS (
    SELECT DISTINCT source_native_id::text AS tm_player_id, player_id AS canonical_player_id
    FROM player_source_crosswalk
    WHERE source = 'transfermarkt' AND source_native_id IS NOT NULL
),
best_row AS (
    SELECT DISTINCT ON (player_id, season_id)
           player_id, season_id, fbref_born, fbref_nineties,
           fbref_non_penalty_goals_per90, fbref_assists_per90, fbref_points_per_match
    FROM master_player_season_stats
    WHERE player_id IS NOT NULL
    ORDER BY player_id, season_id, fbref_nineties DESC NULLS LAST
)
SELECT s.transfer_id, l.canonical_player_id AS player_id, s.season_id AS sale_season,
       s.fee_amount, s.seller_club_id,
       s.prior_season_paid_total, s.prior_5yr_paid_total,
       bl.buyer_league_that_season AS buyer_league,
       a.archetype_id, p.primary_position, p.nineties AS style_nineties,
       b.fbref_born, b.fbref_nineties,
       b.fbref_non_penalty_goals_per90, b.fbref_assists_per90, b.fbref_points_per_match,
       {pct_select}
FROM buyer_spend_context s
JOIN tm_link l ON l.tm_player_id = s.player_id::text
JOIN player_season_archetypes a ON a.player_id = l.canonical_player_id AND a.season_id = s.season_id - 1
JOIN player_season_style_percentiles p ON p.player_id = l.canonical_player_id AND p.season_id = s.season_id - 1
LEFT JOIN best_row b ON b.player_id = l.canonical_player_id AND b.season_id = s.season_id - 1
LEFT JOIN buyer_league_context bl ON bl.transfer_id = s.transfer_id
WHERE s.season_id >= %s AND s.fee_amount IS NOT NULL
ORDER BY s.transfer_id
"""


def read_dataset(conn, first_sale_season=FIRST_SALE_SEASON):
    sql = DATASET_SQL.format(pct_select=", ".join("p." + c for c in PCT_COLS))
    with conn.cursor() as cur:
        cur.execute(sql, (first_sale_season,))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    for c in df.columns:
        if c not in ("primary_position", "buyer_league"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def read_centroids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT archetype_id, feature, centroid_pct FROM archetype_centroids")
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["archetype_id", "feature", "centroid_pct"])


def centroid_matrix(cent, features=ca.CLUSTERING_FEATURES):
    """(k, n_features) matrix of centroid percentiles in `features` order, rows by archetype id."""
    wide = cent.assign(centroid_pct=pd.to_numeric(cent["centroid_pct"])).pivot(
        index="archetype_id", columns="feature", values="centroid_pct")
    missing = [f for f in features if f not in wide.columns]
    if missing:
        raise ValueError(f"archetype_centroids lacks features: {missing}")
    return wide[features].sort_index().to_numpy(dtype=float)


def build_features(raw, cent_matrix, weights):
    """Turn the dataset rows into model inputs. Pure function of its arguments."""
    df = raw.copy()
    df["log_fee"] = np.log1p(df["fee_amount"].astype(float))
    df["age"] = df["sale_season"] - df["fbref_born"]
    nineties = df["fbref_nineties"].where(df["fbref_nineties"].notna(), df["style_nineties"])
    df["log_nineties"] = np.log1p(nineties.astype(float))
    df["production"] = df["fbref_non_penalty_goals_per90"] + df["fbref_assists_per90"]
    df["seller_big3"] = df["seller_club_id"].isin(BIG_THREE.values()).astype(float)
    df["seller_points_per_match"] = df["fbref_points_per_match"]
    df["log_prior_season_spend"] = np.log1p(df["prior_season_paid_total"].astype(float))
    df["log_prior_5yr_spend"] = np.log1p(df["prior_5yr_paid_total"].astype(float))
    df["buyer_league"] = df["buyer_league"].fillna("UNKNOWN")
    df["primary_position"] = df["primary_position"].fillna("UNKNOWN")
    Xw = df[PCT_COLS].to_numpy(dtype=float) / 100.0 * weights
    cw = cent_matrix / 100.0 * weights
    dist = ca.centroid_distances(Xw, cw, weights)
    for j in range(dist.shape[1]):
        df[f"dist_to_{j + 1}"] = dist[:, j]
    df["archetype"] = df["archetype_id"].astype(int).astype(str)
    df["buyer_big5"] = df["buyer_league"].isin(BIG5_LEAGUES).astype(float)       # UNKNOWN counts as not Big-5
    for j in range(cent_matrix.shape[0]):
        df[f"arch_x_big5_{j + 1}"] = (df["archetype_id"].astype(int) == j + 1).astype(float) * df["buyer_big5"]
    return df


def arm_columns(arm, k):
    """(numeric columns, categorical columns, style kind) for an arm."""
    num, cat = list(CONTROL_NUMERIC), list(CONTROL_CATEGORICAL)
    if arm == 1:
        return num, cat, None
    if arm == 2:
        return num, cat + ["archetype"], None
    if arm == 3:
        return num + [f"dist_to_{j + 1}" for j in range(k)], cat, None
    if arm == 4:
        return num, cat, "pc1"
    if arm == 5:
        return num + PCT_COLS, cat, None
    if arm == 6:   # archetype, the Big-5 flag, and archetype x Big-5 (the thesis: do Big-5 buyers pay more for some styles?)
        return num + ["buyer_big5"] + [f"arch_x_big5_{j + 1}" for j in range(k)], cat + ["archetype"], None
    if arm == 7:   # the same question for the continuous style axis
        return num + ["buyer_big5"], cat, "pc1_x_big5"
    raise ValueError(f"unknown arm {arm}")


def assert_no_leak(columns, df, target="log_fee"):
    """Refuse to run if a forbidden column, or one that nearly equals the target, is a feature."""
    bad = sorted(set(columns) & FORBIDDEN_FEATURES)
    if bad:
        raise ValueError(f"leakage guard: forbidden feature(s) {bad}")
    y = df[target].astype(float)
    for c in columns:
        if c in df.columns and pd.api.types.is_numeric_dtype(df[c]):
            x = df[c].astype(float)
            ok = x.notna() & y.notna()
            if ok.sum() > 10 and x[ok].std() > 0:
                r = np.corrcoef(x[ok], y[ok])[0, 1]
                if abs(r) > MAX_TARGET_CORRELATION:
                    raise ValueError(f"leakage guard: {c} correlates {r:.3f} with the target")


def _fill_50_and_weight(weights):
    def f(X):
        X = np.where(np.isnan(X), 50.0, X)
        return X / 100.0 * weights
    return FunctionTransformer(f)


class PC1TimesFlag(BaseEstimator, TransformerMixin):
    """Input: the 23 style percentiles then a 0/1 flag. Output: the first principal component (fitted on the
    rows it is given, so inside each training fold only) and that component times the flag."""

    def __init__(self, weights):
        self.weights = weights

    def _prep(self, X):
        P = np.where(np.isnan(X[:, :-1]), 50.0, X[:, :-1])
        return P / 100.0 * self.weights

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        self.pca_ = PCA(n_components=1).fit(self._prep(X))
        return self

    def transform(self, X):
        X = np.asarray(X, dtype=float)
        z = self.pca_.transform(self._prep(X))
        return np.hstack([z, z * X[:, -1:]])


def make_model(kind, num, cat, style, weights, seed=SEED):
    transformers = [
        ("num", Pipeline([("imp", SimpleImputer(strategy="median", add_indicator=True)),
                          ("sc", StandardScaler())]), num),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), cat),
    ]
    if style == "pc1":
        transformers.append(("pc1", Pipeline([("w", _fill_50_and_weight(weights)), ("pca", PCA(n_components=1)),
                                              ("sc", StandardScaler())]), PCT_COLS))
    if style == "pc1_x_big5":
        transformers.append(("pc1x", Pipeline([("pc", PC1TimesFlag(weights)), ("sc", StandardScaler())]),
                             PCT_COLS + ["buyer_big5"]))
    pre = ColumnTransformer(transformers)
    if kind == "ridge":
        est = RidgeCV(alphas=np.logspace(-1, 3, 20))
    elif kind == "gbm":
        est = HistGradientBoostingRegressor(max_depth=3, max_iter=150, learning_rate=0.05,
                                            min_samples_leaf=15, random_state=seed)
    else:
        raise ValueError(kind)
    return Pipeline([("pre", pre), ("est", est)])


def grouped_repeated_folds(groups, n_splits=5, n_repeats=10, seed=SEED):
    """Yield (repeat, train_idx, test_idx). Each repeat shuffles the groups and deals them into
    n_splits folds, so every row of a group lands in the same fold."""
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    rng = np.random.default_rng(seed)
    for r in range(n_repeats):
        order = rng.permutation(uniq)
        fold_of = {g: i % n_splits for i, g in enumerate(order)}
        fold = np.array([fold_of[g] for g in groups])
        for f in range(n_splits):
            yield r, np.where(fold != f)[0], np.where(fold == f)[0]


def time_fold(sale_season, last_train=TIME_SPLIT_LAST_TRAIN_SEASON):
    s = np.asarray(sale_season)
    return np.where(s <= last_train)[0], np.where(s > last_train)[0]


def oof_grouped(df, num, cat, style, kind, weights, n_splits, n_repeats, seed=SEED):
    """Out-of-fold predictions, shape (n_repeats, n_rows)."""
    y = df["log_fee"].to_numpy(dtype=float)
    pred = np.full((n_repeats, len(df)), np.nan)
    for r, tr, te in grouped_repeated_folds(df["player_id"].to_numpy(), n_splits, n_repeats, seed):
        m = make_model(kind, num, cat, style, weights, seed)
        m.fit(df.iloc[tr][num + cat + (PCT_COLS if style else [])], y[tr])
        pred[r, te] = m.predict(df.iloc[te][num + cat + (PCT_COLS if style else [])])
    return pred


def predict_time(df, num, cat, style, kind, weights, seed=SEED):
    tr, te = time_fold(df["sale_season"])
    y = df["log_fee"].to_numpy(dtype=float)
    cols = num + cat + (PCT_COLS if style else [])
    m = make_model(kind, num, cat, style, weights, seed)
    m.fit(df.iloc[tr][cols], y[tr])
    return te, m.predict(df.iloc[te][cols])


def rmse(err2):
    return float(np.sqrt(np.mean(err2)))


def cluster_bootstrap_diff(se_arm, se_base, groups, n_boot=1000, seed=SEED):
    """RMSE(arm) - RMSE(base) with a 95% interval, resampling players (all their sales together)."""
    groups = np.asarray(groups)
    uniq, inv = np.unique(groups, return_inverse=True)
    idx_by_group = [np.where(inv == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(uniq), len(uniq))
        rows = np.concatenate([idx_by_group[i] for i in pick])
        diffs[b] = rmse(se_arm[rows]) - rmse(se_base[rows])
    point = rmse(se_arm) - rmse(se_base)
    return point, float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def compare(df, k, weights, n_splits=5, n_repeats=10, n_boot=1000, seed=SEED, arms=(1, 2, 3, 4, 5, 6, 7), models=("ridge", "gbm")):
    """Run every arm x model x scheme. Returns a long DataFrame of results. Each arm is compared with its
    BASELINE_ARM (the controls, except the two interaction arms, which are compared with the same style
    information without the interaction)."""
    missing = sorted({BASELINE_ARM[a] for a in arms} - set(arms))
    if missing:
        raise ValueError(f"arms {missing} are the baseline of a requested arm and must be run too")
    y = df["log_fee"].to_numpy(dtype=float)
    groups = df["player_id"].to_numpy()
    # guard once over every column any arm uses
    all_cols = set()
    for a in arms:
        n, c, s = arm_columns(a, k)
        all_cols |= set(n) | set(c) | (set(PCT_COLS) if s else set())
    assert_no_leak(sorted(all_cols), df)

    se = {}   # (scheme, model, arm) -> per-row squared error (averaged over repeats for grouped)
    rep_rmse = {}
    te_idx = time_fold(df["sale_season"])[1]
    for kind in models:
        for a in arms:
            n, c, s = arm_columns(a, k)
            pred = oof_grouped(df, n, c, s, kind, weights, n_splits, n_repeats, seed)
            err2 = (pred - y[None, :]) ** 2
            se[("grouped", kind, a)] = err2.mean(axis=0)
            rep_rmse[("grouped", kind, a)] = np.sqrt(err2.mean(axis=1))
            te, p = predict_time(df, n, c, s, kind, weights, seed)
            full = np.full(len(df), np.nan)
            full[te] = (p - y[te]) ** 2
            se[("time", kind, a)] = full
    rows = []
    for (scheme, kind, a), e in se.items():
        b = BASELINE_ARM[a]
        base = se[(scheme, kind, b)]
        if scheme == "time":
            sel = te_idx
            point, lo, hi = cluster_bootstrap_diff(e[sel], base[sel], groups[sel], n_boot, seed) if a != b else (0.0, 0.0, 0.0)
            r = rmse(e[sel])
            beats = np.nan
        else:
            point, lo, hi = cluster_bootstrap_diff(e, base, groups, n_boot, seed) if a != b else (0.0, 0.0, 0.0)
            r = rmse(e)
            beats = float((rep_rmse[(scheme, kind, a)] < rep_rmse[(scheme, kind, b)]).mean()) if a != b else np.nan
        rows.append({"scheme": scheme, "model": kind, "arm": a, "arm_name": ARM_NAMES[a], "baseline_arm": b,
                     "rmse_log": r, "diff_vs_baseline": point, "ci_low": lo, "ci_high": hi,
                     "share_repeats_beating_baseline": beats,
                     "n_scored": int(len(e) if scheme == "grouped" else len(te_idx))})
    return pd.DataFrame(rows)


def verdict(results):
    """Plain-language reading. An arm 'adds signal' only if its 95% interval (against its baseline arm)
    sits below zero under BOTH schemes and for BOTH models."""
    lines = []
    for a in sorted(results["arm"].unique()):
        if BASELINE_ARM[a] == a:
            continue
        sub = results[results["arm"] == a]
        wins = sub[sub["ci_high"] < 0]
        status = "ADDS signal" if len(wins) == len(sub) else ("mixed" if len(wins) else "no clear gain")
        base = "the controls" if BASELINE_ARM[a] == 1 else f"arm {BASELINE_ARM[a]} ({ARM_NAMES[BASELINE_ARM[a]]})"
        lines.append(f"  arm {a} {ARM_NAMES[a]:<28} {status}  ({len(wins)} of {len(sub)} scheme/model combinations beat {base})")
    return "\n".join(lines)


def format_results(results):
    out = results.copy()
    for c in ("rmse_log", "diff_vs_baseline", "ci_low", "ci_high"):
        out[c] = out[c].round(3)
    out["share_repeats_beating_baseline"] = out["share_repeats_beating_baseline"].round(2)
    return out.drop(columns=["arm"]).to_string(index=False)


def baseline_rmse(df):
    y = df["log_fee"].to_numpy(dtype=float)
    return float(np.sqrt(np.mean((y - y.mean()) ** 2)))


def run(conn, n_repeats=10, n_boot=1000, out=print, csv_path=None):
    raw = read_dataset(conn)
    cent = centroid_matrix(read_centroids(conn))
    k = cent.shape[0]
    weights = ca.feature_weights()
    df = build_features(raw, cent, weights)
    names = {}
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT club_id, club_name FROM eredivisie_club_status WHERE club_id = ANY(%s)",
                    (list(BIG_THREE.values()),))
        names = dict(cur.fetchall())
    out(f"Usable sales (sale seasons {FIRST_SALE_SEASON}+, archetype and style row from the season before): {len(df)}"
        f"   players: {df['player_id'].nunique()}   archetypes: {k}")
    out("Big three seller ids -> club names found: " + ", ".join(f"{n} {i} -> {names.get(i, 'NOT FOUND')}" for n, i in BIG_THREE.items()))
    out(f"Sales by sale season: {df['sale_season'].value_counts().sort_index().to_dict()}")
    te = time_fold(df["sale_season"])[1]
    out(f"Time split: train sale seasons <= {TIME_SPLIT_LAST_TRAIN_SEASON} ({len(df) - len(te)} sales), test {len(te)} sales")
    out(f"Reference: predicting the mean fee gives RMSE {baseline_rmse(df):.3f} on log(1 + fee in M)")
    miss = {c: int(df[c].isna().sum()) for c in CONTROL_NUMERIC if df[c].isna().any()}
    out(f"Missing control values (imputed by the median, with a missing-flag): {miss or 'none'}")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        results = compare(df, k, weights, n_repeats=n_repeats, n_boot=n_boot)
    out("\nRMSE on log(1 + fee) (lower is better); diff = arm minus its baseline arm (controls for arms 2-5, arm 2 for arm 6, arm 4 for arm 7), with a 95% interval from resampling players:")
    out(format_results(results))
    out("\nReading (an arm adds signal only if its interval is below zero for both models and both schemes):")
    out(verdict(results))
    if csv_path:
        results.to_csv(csv_path, index=False)
        out(f"\nWrote {csv_path}")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--out", default=None, help="write the result table to this CSV")
    args = ap.parse_args(argv)
    conn = ca.get_connection()
    try:
        run(conn, args.repeats, args.boot, csv_path=args.out)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
