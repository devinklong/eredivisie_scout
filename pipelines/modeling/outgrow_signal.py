"""
Step 4 of the modeling pipeline: which Eredivisie players OUTGROW the league?

"Outgrew the league" is defined by the market, not by us: a paid sale out of the Eredivisie whose fee is
at or above that season's typical Big-5 signing. The yardstick is the season's MEDIAN fee (the main
definition) or MEAN fee (a sensitivity check) paid by clubs in a Big-5 league that season, taken from
buyer_club_transfers joined to league_season_clubs. Using the market of the same season handles transfer
inflation (the median Big-5 signing went from 3.0M in 2010 to 13.5M in 2025) and does not depend on one
record purchase. About a fifth of Eredivisie sales clear the median bar, spread across every season.

THE QUESTION: using only what is known about the PLAYER before the sale, how well can we tell who clears
the bar, and does playing style help?
  PLAYER-SIDE FEATURES ONLY: position, age, minutes, production, sale season, whether the seller is one of
  the big three, the seller team's points per match. The buyer's league, the buyer's spend and the Big-5
  flag are NOT features: they exist only because the buyer is already known, so they would hand the model
  the answer. (This is also why this question is not the same as the fee regression, whose controls
  absorbed most of the signal.)

FIVE ARMS, identical rows and identical folds (same as the fee comparison):
  1 controls  2 + archetype  3 + centroid distances  4 + style axis (PC1, fitted in each fold)  5 + 23 percentiles
Two classifiers per arm: logistic regression (penalty chosen by inner cross-validation) and a shallow
gradient-boosted classifier. Score = log loss (lower is better; it punishes confident wrong answers),
with AUC reported next to it. An arm adds signal only if its 95% interval (log loss minus the controls',
resampling players) is below zero under BOTH schemes and for BOTH models:
  grouped  repeated 5-fold, all of a player's sales in one fold
  time     train on sale seasons up to 2021, test on 2022 on

ALSO PRINTED, no model involved: how often sales clear the bar by position, age band and production
quartile (with the quartile boundaries), so the "threshold" can be read straight off the data.

IS IT THE PLAYER OR THE CLUB? The controls include two seller-side columns (is the seller one of the big
three, the seller's points per match). The ablation re-scores the controls with those removed, with only
those kept, and with only age, position and season, so the reading says how much of the model is the club.
A grid then shows the fitted chance of clearing the bar by age and production (descriptive, fitted on every
sale), separately for big-three and other sellers.

CAVEAT that no model can fix: we only see players who were SOLD. Someone who outgrew the league and stayed
is invisible, so every threshold describes sold players.

Usage:
    python pipelines/modeling/outgrow_signal.py                  # median bar, then mean bar
    python pipelines/modeling/outgrow_signal.py --bar median --repeats 20 --out data_audit/results/outgrow_signal.csv
"""

import argparse
import sys
import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

try:
    import style_price_signal as sp
except ImportError:  # run from the repo root
    sys.path.insert(0, "pipelines/modeling")
    import style_price_signal as sp
ca = sp.ca

SEED = 20261018
EPS = 1e-6
BARS = ("median", "mean")
PLAYER_SIDE_NUMERIC = ["age", "log_nineties", "production", "sale_season", "seller_big3", "seller_points_per_match"]
PLAYER_SIDE_CATEGORICAL = ["primary_position"]
# Anything that exists only because the buyer is known. Never a feature here.
BUYER_SIDE = frozenset({"buyer_league", "buyer_big5", "log_prior_season_spend", "log_prior_5yr_spend",
                        "buyer_page_fee", "pct_of_buyer_season_spend", "pct_of_buyer_5yr_spend"}
                       | {f"arch_x_big5_{j}" for j in range(1, 21)})
ARM_NAMES = {a: sp.ARM_NAMES[a] for a in (1, 2, 3, 4, 5)}

MARKET_INDEX_SQL = """
SELECT t.season_id,
       AVG(t.fee_amount) AS mean_fee,
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.fee_amount) AS median_fee
FROM buyer_club_transfers t
JOIN league_season_clubs l ON l.club_id = t.own_club_id AND l.season_id = t.season_id
WHERE t.direction = 'in' AND t.fee_type IN ('permanent_transfer', 'paid_loan')
  AND t.fee_amount > 0 AND NOT t.is_internal_promotion
GROUP BY t.season_id
ORDER BY t.season_id
"""


def read_market_index(conn):
    with conn.cursor() as cur:
        cur.execute(MARKET_INDEX_SQL)
        rows = cur.fetchall()
    idx = pd.DataFrame(rows, columns=["season_id", "mean_fee", "median_fee"])
    for c in idx.columns:
        idx[c] = pd.to_numeric(idx[c], errors="coerce")
    return idx.set_index("season_id")


def build_outgrow_frame(raw, cent_matrix, weights, market_index, bar="median"):
    """Model inputs plus the target `outgrew` (1 if fee >= that season's Big-5 <bar> signing fee).
    Rows whose sale season has no market index are dropped, and counted. Returns (frame, n_dropped)."""
    if bar not in BARS:
        raise ValueError(f"bar must be one of {BARS}")
    df = sp.build_features(raw, cent_matrix, weights)
    df["market_bar"] = df["sale_season"].map(market_index[f"{bar}_fee"])
    n_dropped = int(df["market_bar"].isna().sum())
    df = df[df["market_bar"].notna()].reset_index(drop=True)
    df["outgrew"] = (df["fee_amount"].astype(float) >= df["market_bar"]).astype(int)
    return df, n_dropped


def arm_columns(arm, k):
    """(numeric, categorical, style kind) for an arm, player-side only."""
    num, cat = list(PLAYER_SIDE_NUMERIC), list(PLAYER_SIDE_CATEGORICAL)
    if arm == 1:
        return num, cat, None
    if arm == 2:
        return num, cat + ["archetype"], None
    if arm == 3:
        return num + [f"dist_to_{j + 1}" for j in range(k)], cat, None
    if arm == 4:
        return num, cat, "pc1"
    if arm == 5:
        return num + sp.PCT_COLS, cat, None
    raise ValueError(f"unknown arm {arm}")


def assert_player_side_only(columns):
    bad = sorted(set(columns) & (BUYER_SIDE | sp.FORBIDDEN_FEATURES))
    if bad:
        raise ValueError(f"buyer-side or fee-derived column(s) cannot be features of an 'outgrew' model: {bad}")


def row_log_loss(y, p):
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def fit_predict_proba(kind, num, cat, style, weights, train, test, y_train, seed=SEED):
    """P(outgrew) for the test rows. A training set with one class has nothing to learn from, so it
    returns that class's frequency instead of failing."""
    if len(np.unique(y_train)) < 2:
        return np.full(len(test), float(np.mean(y_train)))
    cols = num + cat + (sp.PCT_COLS if style else [])
    m = sp.make_model(kind, num, cat, style, weights, seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)         # scikit-learn's notices about LogisticRegressionCV's next version
        m.fit(train[cols], y_train)
    return m.predict_proba(test[cols])[:, 1]


def oof_grouped(df, num, cat, style, kind, weights, n_splits, n_repeats, seed=SEED):
    y = df["outgrew"].to_numpy(dtype=int)
    pred = np.full((n_repeats, len(df)), np.nan)
    for r, tr, te in sp.grouped_repeated_folds(df["player_id"].to_numpy(), n_splits, n_repeats, seed):
        pred[r, te] = fit_predict_proba(kind, num, cat, style, weights, df.iloc[tr], df.iloc[te], y[tr], seed)
    return pred


def predict_time(df, num, cat, style, kind, weights, seed=SEED):
    tr, te = sp.time_fold(df["sale_season"])
    y = df["outgrew"].to_numpy(dtype=int)
    return te, fit_predict_proba(kind, num, cat, style, weights, df.iloc[tr], df.iloc[te], y[tr], seed)


def cluster_bootstrap_mean_diff(loss_arm, loss_base, groups, n_boot=1000, seed=SEED):
    """mean(loss_arm) - mean(loss_base) with a 95% interval, resampling players (all their sales together)."""
    groups = np.asarray(groups)
    uniq, inv = np.unique(groups, return_inverse=True)
    idx_by_group = [np.where(inv == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(seed)
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, len(uniq), len(uniq))
        rows = np.concatenate([idx_by_group[i] for i in pick])
        diffs[b] = loss_arm[rows].mean() - loss_base[rows].mean()
    return (float(loss_arm.mean() - loss_base.mean()),
            float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def _auc(y, p):
    return float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")


def _score(df, specs, base_key, weights, n_splits, n_repeats, n_boot, seed, models):
    """Score every spec x model x scheme. specs: ordered {key: (name, numeric, categorical, style kind)}.
    Each spec is compared with specs[base_key]. Returns a long DataFrame."""
    y = df["outgrew"].to_numpy(dtype=int)
    groups = df["player_id"].to_numpy()
    te_idx = sp.time_fold(df["sale_season"])[1]
    loss, rep_loss, auc = {}, {}, {}
    for kind in models:
        for key, (name, n, c, s) in specs.items():
            pred = oof_grouped(df, n, c, s, kind, weights, n_splits, n_repeats, seed)
            ll = row_log_loss(y[None, :], pred)
            loss[("grouped", kind, key)] = ll.mean(axis=0)
            rep_loss[("grouped", kind, key)] = ll.mean(axis=1)
            auc[("grouped", kind, key)] = float(np.nanmean([_auc(y, pred[r]) for r in range(n_repeats)]))
            te, p = predict_time(df, n, c, s, kind, weights, seed)
            full = np.full(len(df), np.nan)
            full[te] = row_log_loss(y[te], p)
            loss[("time", kind, key)] = full
            auc[("time", kind, key)] = _auc(y[te], p)
    rows = []
    for (scheme, kind, key), e in loss.items():
        base = loss[(scheme, kind, base_key)]
        sel = te_idx if scheme == "time" else np.arange(len(df))
        point, lo, hi = (cluster_bootstrap_mean_diff(e[sel], base[sel], groups[sel], n_boot, seed)
                         if key != base_key else (0.0, 0.0, 0.0))
        beats = (float((rep_loss[(scheme, kind, key)] < rep_loss[(scheme, kind, base_key)]).mean())
                 if scheme == "grouped" and key != base_key else np.nan)
        rows.append({"scheme": scheme, "model": kind, "key": key, "name": specs[key][0],
                     "log_loss": float(e[sel].mean()), "diff": point, "ci_low": lo, "ci_high": hi,
                     "auc": auc[(scheme, kind, key)], "share_beating_base": beats,
                     "n_scored": int(len(sel)), "n_positive": int(y[sel].sum())})
    return pd.DataFrame(rows)


def compare(df, k, weights, n_splits=5, n_repeats=10, n_boot=1000, seed=SEED, arms=(1, 2, 3, 4, 5), models=("logit", "gbm_clf")):
    """Every arm x model x scheme, as a long DataFrame. Arm 1 (controls) must be included."""
    if 1 not in arms:
        raise ValueError("arm 1 (controls) is the baseline and must be run")
    specs = {a: (ARM_NAMES[a],) + arm_columns(a, k) for a in arms}
    all_cols = set()
    for _, n, c, s in specs.values():
        all_cols |= set(n) | set(c) | (set(sp.PCT_COLS) if s else set())
    assert_player_side_only(sorted(all_cols))
    sp.assert_no_leak(sorted(all_cols), df, target="outgrew")
    r = _score(df, specs, 1, weights, n_splits, n_repeats, n_boot, seed, models)
    r = r.rename(columns={"key": "arm", "name": "arm_name", "diff": "diff_vs_controls",
                          "share_beating_base": "share_repeats_beating_controls"})
    return r[["scheme", "model", "arm", "arm_name", "log_loss", "diff_vs_controls", "ci_low", "ci_high", "auc",
              "share_repeats_beating_controls", "n_scored", "n_positive"]]


SELLER_SIDE = ["seller_big3", "seller_points_per_match"]


def ablation_variants():
    """Which part of the controls carries the model: the player, or the club he sells from? First entry is the baseline."""
    full = list(PLAYER_SIDE_NUMERIC)
    return {
        "all controls": (full, list(PLAYER_SIDE_CATEGORICAL), None),
        "no seller context": ([c for c in full if c not in SELLER_SIDE], list(PLAYER_SIDE_CATEGORICAL), None),
        "seller context only": (SELLER_SIDE + ["sale_season"], [], None),
        "age, position, season only": (["age", "sale_season"], list(PLAYER_SIDE_CATEGORICAL), None),
    }


def compare_variants(df, variants, weights, n_splits=5, n_repeats=10, n_boot=1000, seed=SEED, models=("logit", "gbm_clf")):
    """Score named column sets against the FIRST one. variants: {name: (numeric, categorical, style kind)}."""
    names = list(variants)
    if not names:
        raise ValueError("no variants")
    specs = {i: (name,) + tuple(variants[name]) for i, name in enumerate(names)}
    all_cols = set()
    for _, n, c, s in specs.values():
        all_cols |= set(n) | set(c) | (set(sp.PCT_COLS) if s else set())
    assert_player_side_only(sorted(all_cols))
    sp.assert_no_leak(sorted(all_cols), df, target="outgrew")
    r = _score(df, specs, 0, weights, n_splits, n_repeats, n_boot, seed, models)
    r = r.rename(columns={"name": "variant", "diff": "diff_vs_first", "share_beating_base": "share_repeats_beating_first"})
    return r.drop(columns=["key"])[["scheme", "model", "variant", "log_loss", "diff_vs_first", "ci_low", "ci_high", "auc",
                                    "share_repeats_beating_first", "n_scored", "n_positive"]]


def ablation_reading(results):
    """Plain-language reading from the grouped logistic rows."""
    g = results[(results["scheme"] == "grouped") & (results["model"] == "logit")].set_index("variant")
    lines = []
    ns, so = g.loc["no seller context"], g.loc["seller context only"]
    allc = g.loc["all controls"]
    if ns["ci_low"] > 0:
        lines.append(f"  Removing the seller context makes the model clearly worse (log loss +{ns['diff_vs_first']:.3f}, AUC {allc['auc']:.3f} -> {ns['auc']:.3f}): part of the signal is the CLUB he sells from.")
    else:
        lines.append(f"  Removing the seller context does not clearly hurt (log loss {ns['diff_vs_first']:+.3f}, AUC {allc['auc']:.3f} -> {ns['auc']:.3f}): the PLAYER side carries the model.")
    if so["ci_low"] > 0:
        lines.append(f"  The seller context alone is clearly worse than everything (log loss +{so['diff_vs_first']:.3f}, AUC {so['auc']:.3f}): the player side adds real signal on top of the club.")
    else:
        lines.append(f"  The seller context alone does about as well as everything (log loss {so['diff_vs_first']:+.3f}, AUC {so['auc']:.3f}): the club explains most of it.")
    return "\n".join(lines)


def probability_grid(df, k, weights, position, ages=(19, 21, 23, 25, 27, 29), seed=SEED):
    """Fit the controls model on every row and return {seller_big3 value: DataFrame of P(outgrew) in percent,
    age down, production quartile medians across}. Descriptive only: the model sees every row it describes.
    Everything else is held at its median (sale season at the latest one)."""
    num, cat, _ = arm_columns(1, k)
    q = pd.qcut(df["production"], 4, duplicates="drop")
    meds = df.groupby(q, observed=True)["production"].median().tolist()
    m = sp.make_model("logit", num, cat, None, weights, seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        m.fit(df[num + cat], df["outgrew"].to_numpy(dtype=int))
    base = {c: df[c].median() for c in num}
    base["sale_season"] = float(df["sale_season"].max())
    out = {}
    for big3 in (0.0, 1.0):
        rows = []
        for age in ages:
            for prod in meds:
                r = dict(base)
                r.update(age=float(age), production=float(prod), seller_big3=big3)
                r["primary_position"] = position
                rows.append(r)
        grid = pd.DataFrame(rows)
        p = m.predict_proba(grid[num + cat])[:, 1].reshape(len(ages), len(meds))
        out[big3] = pd.DataFrame(np.round(100 * p, 0).astype(int), index=[f"age {a}" for a in ages],
                                 columns=[f"production {x:.2f}" for x in meds])
    return out


def verdict(results):
    """An arm adds signal only if its 95% interval sits below zero under BOTH schemes and for BOTH models."""
    lines = []
    for a in sorted(results["arm"].unique()):
        if a == 1:
            continue
        sub = results[results["arm"] == a]
        wins = sub[sub["ci_high"] < 0]
        status = "ADDS signal" if len(wins) == len(sub) else ("mixed" if len(wins) else "no clear gain")
        lines.append(f"  arm {a} {ARM_NAMES[a]:<22} {status}  ({len(wins)} of {len(sub)} scheme/model combinations beat the controls)")
    return "\n".join(lines)


def format_results(results):
    out = results.copy()
    for c in ("log_loss", "diff_vs_controls", "ci_low", "ci_high", "auc"):
        out[c] = out[c].round(3)
    out["share_repeats_beating_controls"] = out["share_repeats_beating_controls"].round(2)
    return out.drop(columns=["arm"]).to_string(index=False)


def baseline_log_loss(df):
    """Log loss of predicting the base rate for everyone: the number a useless model scores."""
    y = df["outgrew"].to_numpy(dtype=float)
    return float(row_log_loss(y, np.full(len(y), y.mean())).mean())


def profile_tables(df):
    """How often sales clear the bar, by position, age band and production quartile. No model."""
    d = df.copy()
    d["age_band"] = pd.cut(d["age"], [-np.inf, 20, 22, 24, 26, np.inf], labels=["<=20", "21-22", "23-24", "25-26", "27+"])
    _, bins = pd.qcut(d["production"], 4, retbins=True, duplicates="drop")
    labels = [f"Q{i + 1} ({bins[i]:.2f} to {bins[i + 1]:.2f})" for i in range(len(bins) - 1)]
    d["production_quartile"] = pd.qcut(d["production"], 4, labels=labels, duplicates="drop")

    def table(col):
        g = d.groupby(col, observed=True)["outgrew"].agg(sales="size", cleared="sum")
        g["rate_pct"] = (100 * g["cleared"] / g["sales"]).round(0)
        return g.reset_index()
    return {"position": table("primary_position"), "age band": table("age_band"),
            "production (non-penalty goals + assists per 90)": table("production_quartile")}


def run(conn, bar="median", n_repeats=10, n_boot=1000, out=print, csv_path=None, position=None):
    raw = sp.read_dataset(conn)
    cent = sp.centroid_matrix(sp.read_centroids(conn))
    k = cent.shape[0]
    weights = ca.feature_weights()
    market = read_market_index(conn)
    df, dropped = build_outgrow_frame(raw, cent, weights, market, bar)
    te = sp.time_fold(df["sale_season"])[1]
    out(f"=== BAR: fee at or above the season's Big-5 {bar} signing fee ===")
    out(f"Usable sales: {len(df)} ({dropped} dropped: no market index for their sale season)   players: {df['player_id'].nunique()}")
    out(f"Cleared the bar: {int(df['outgrew'].sum())} ({100 * df['outgrew'].mean():.0f}%)   "
        f"train (sale seasons <= {sp.TIME_SPLIT_LAST_TRAIN_SEASON}): {int(df['outgrew'].sum() - df['outgrew'].iloc[te].sum())} of {len(df) - len(te)}   "
        f"test: {int(df['outgrew'].iloc[te].sum())} of {len(te)}")
    out(f"Cleared by sale season: {df.groupby('sale_season')['outgrew'].sum().to_dict()}")
    out(f"Reference: predicting the base rate for everyone scores log loss {baseline_log_loss(df):.3f}")
    out("\nHow often sales clear the bar (no model):")
    for name, t in profile_tables(df).items():
        out(f"\n  by {name}")
        out("    " + t.to_string(index=False).replace("\n", "\n    "))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        results = compare(df, k, weights, n_repeats=n_repeats, n_boot=n_boot)
    out("\nLog loss (lower is better) and AUC; diff = arm minus controls, 95% interval from resampling players:")
    out(format_results(results))
    out("\nReading (an arm adds signal only if its interval is below zero for both models and both schemes):")
    out(verdict(results))
    out("\n--- Is it the PLAYER or the CLUB? Same controls with the seller-side columns removed or kept alone ---")
    out("(diff = variant minus 'all controls'; positive = worse)")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        abl = compare_variants(df, ablation_variants(), weights, n_repeats=n_repeats, n_boot=n_boot)
    t = abl.copy()
    for c in ("log_loss", "diff_vs_first", "ci_low", "ci_high", "auc"):
        t[c] = t[c].round(3)
    out(t.drop(columns=["share_repeats_beating_first"]).to_string(index=False))
    out("\n" + ablation_reading(abl))
    pos = position or df["primary_position"].value_counts().index[0]
    out(f"\n--- Chance of clearing the bar by age and production (%), {pos}, everything else at its median, latest sale season ---")
    out("(descriptive: the controls model fitted on every sale; production = non-penalty goals + assists per 90, at each quartile's median)")
    for big3, grid in probability_grid(df, k, weights, pos).items():
        out(f"\n  seller is {'one of the big three' if big3 else 'NOT one of the big three'}")
        out("    " + grid.to_string().replace("\n", "\n    "))
    if csv_path:
        results.assign(bar=bar).to_csv(csv_path, index=False)
        out(f"\nWrote {csv_path}")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bar", choices=list(BARS) + ["both"], default="both")
    ap.add_argument("--repeats", type=int, default=10)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--position", choices=["DF", "MF", "FW"], default=None, help="position for the probability grid (default: the most common)")
    ap.add_argument("--out", default=None, help="write the result table to this CSV (the bar name is added as a column)")
    args = ap.parse_args(argv)
    conn = ca.get_connection()
    try:
        for bar in (BARS if args.bar == "both" else (args.bar,)):
            run(conn, bar, args.repeats, args.boot, position=args.position, csv_path=args.out if args.bar != "both" else (args.out and args.out.replace(".csv", f"_{bar}.csv")))
            print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
