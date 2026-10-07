"""
Step 2 of the modeling pipeline: archetype clustering.

Groups player-seasons by HOW THEY PLAY, using the percentile vector built by
build_style_percentiles.py. Position is not an input: the percentiles are already
relative to the player's own position group, so a defender and a forward who share
a style (say, high involvement in the final third for their role) can land together.
Position is reported afterwards as a qualifier, not used to cluster.

WHAT IS CLUSTERED: stat seasons from CLUSTERING_FIRST_SEASON on (WhoScored starts in
2013) whose 23-feature clustering vector is COMPLETE (99.1% of ranked rows). Seasons
are pooled: the percentiles are within season, so they are comparable across seasons.
The few rows missing a feature (derived shots) are assigned afterwards by nearest
centroid on the features they have.

FEATURE-GROUP BALANCE: the 23 features are not evenly spread over kinds of play.
Defending has ten (tackles and interceptions by zone, clearances, being dribbled
past), dribbling two, aerial and shooting one each. Raw percentiles would let the
defensive block dominate the distances, so players would mostly be grouped by how
defensive they are. Each of the six groups therefore carries equal weight: a feature's
weight is 1/sqrt(group size), so every group contributes the same total to a squared
distance. FEATURE_GROUPS must cover CLUSTERING_FEATURES exactly (checked), so adding
or removing a feature there forces a decision about its group.

HOW MANY ARCHETYPES: chosen by STABILITY, not by a fit score. For each k in the range,
two k-means models are fitted on independent random subsamples (80%), every row is
assigned with each, and the two labelings are compared by adjusted Rand index. Real
structure survives resampling; an arbitrary split of a blob does not. Stability
always favors fewer clusters, so the range has a deliberate floor (6, for
interpretability). The rule: among k whose full-data solution has no cluster smaller
than MIN_CLUSTER_ROWS, take the LARGEST k whose mean stability is within TOLERANCE of
the best, i.e. the finest solution that is about as stable as the most stable one. The
whole table is printed, and --k overrides the choice.

CROSS-CHECKS printed: Ward hierarchical clustering at the chosen k against k-means
(agreement by adjusted Rand index), and unweighted k-means against the weighted
solution (how much the group weighting matters).

OUTPUT: player_season_archetypes (one row per assigned player-season: archetype id,
distance to its centroid, how many features were used) and archetype_centroids
(centroid percentile per feature). Archetype ids are 1..k ordered by FINAL size
(complete plus partial rows), largest first; they are arbitrary labels until named, and change if the data changes. Then a
read-only report of the usable sales (stat season = sale season - 1) by archetype.

Usage:
    python pipelines/modeling/cluster_archetypes.py
    python pipelines/modeling/cluster_archetypes.py --k 9          # skip the search
    python pipelines/modeling/cluster_archetypes.py --ks 5 12 --pairs 30
    python pipelines/modeling/cluster_archetypes.py --ks 3 8 --no-write      # explore without replacing the tables
"""

import argparse
import sys

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

try:
    from sklearn.cluster import AgglomerativeClustering, KMeans
    from sklearn.metrics import adjusted_rand_score
except ImportError:
    sys.exit("scikit-learn is required for this step: pip install scikit-learn")

from build_style_percentiles import CLUSTERING_FEATURES, CLUSTERING_FIRST_SEASON, get_connection

FEATURE_GROUPS = {
    "footprint": ["ws_touches_per90", "ws_touches_def_3rd_per90", "ws_touches_mid_3rd_per90",
                  "ws_touches_att_3rd_per90", "ws_touches_def_pen_area_per90", "ws_touches_att_pen_area_per90"],
    "passing_progression": ["ws_passes_per90", "ws_final_third_entries_per90", "ws_pen_area_entries_per90"],
    "dribbling": ["ws_take_ons_per90", "ws_dispossessed_per90"],
    "defending": ["ws_tackles_per90", "ws_tackles_def_3rd_per90", "ws_tackles_mid_3rd_per90", "ws_tackles_att_3rd_per90",
                  "ws_interceptions_per90", "ws_interceptions_def_3rd_per90", "ws_interceptions_mid_3rd_per90",
                  "ws_interceptions_att_3rd_per90", "ws_clearances_per90", "ws_dribbled_past_per90"],
    "aerial": ["ws_aerials_per90"],
    "shooting": ["derived_shots_per90"],
}
SEED = 20261006
KS_DEFAULT = (6, 14)
N_PAIRS = 20
SUBSAMPLE = 0.8
TOLERANCE = 0.03
MIN_CLUSTER_ROWS = 60
FIRST_SALE_SEASON = CLUSTERING_FIRST_SEASON + 1       # a sale needs stats from the season before it


def check_groups(features=CLUSTERING_FEATURES, groups=FEATURE_GROUPS):
    """Every clustering feature in exactly one group, and no group feature outside the vector."""
    listed = [f for feats in groups.values() for f in feats]
    dupes = sorted({f for f in listed if listed.count(f) > 1})
    if dupes:
        raise ValueError(f"features in more than one group: {dupes}")
    missing = sorted(set(features) - set(listed))
    extra = sorted(set(listed) - set(features))
    if missing or extra:
        raise ValueError(f"FEATURE_GROUPS and CLUSTERING_FEATURES disagree. In the vector but ungrouped: {missing}. "
                         f"Grouped but not in the vector: {extra}.")


check_groups()


def feature_weights(features=CLUSTERING_FEATURES, groups=FEATURE_GROUPS, group_weights=None):
    """1/sqrt(group size) per feature (times an optional per-group weight), so every group
    contributes equally to a squared distance."""
    group_weights = group_weights or {}
    weight = {}
    for name, feats in groups.items():
        for f in feats:
            weight[f] = group_weights.get(name, 1.0) / np.sqrt(len(feats))
    return np.array([weight[f] for f in features])


def to_matrix(df, features=CLUSTERING_FEATURES, weights=None):
    """Percentiles scaled to 0-1 and weighted. NaN stays NaN."""
    weights = feature_weights(features) if weights is None else weights
    return df[["pct_" + f for f in features]].to_numpy(dtype=float) / 100.0 * weights


def split_clustering_rows(df, first_season=CLUSTERING_FIRST_SEASON, features=CLUSTERING_FEATURES):
    """-> (complete, partial). Rows before first_season are dropped (no WhoScored data). Complete rows
    have every clustering feature; partial rows are missing some but not all."""
    r = df[df["season_id"] >= first_season]
    cols = ["pct_" + f for f in features]
    present = r[cols].notna()
    complete = r[present.all(axis=1)].reset_index(drop=True)
    partial = r[present.any(axis=1) & ~present.all(axis=1)].reset_index(drop=True)
    return complete, partial


def fit_kmeans(X, k, seed=SEED, n_init=10):
    return KMeans(n_clusters=k, n_init=n_init, random_state=seed).fit(X)


def stability_by_k(X, ks, n_pairs=N_PAIRS, frac=SUBSAMPLE, seed=SEED, n_init=5):
    """Mean adjusted Rand index between the labelings (of ALL rows) produced by k-means models fitted
    on two independent subsamples. Seeded per k, so a k's result does not depend on the other ks."""
    n = len(X)
    m = int(frac * n)
    rows = []
    for k in ks:
        rng = np.random.default_rng([seed, k])
        aris = []
        for _ in range(n_pairs):
            a = rng.choice(n, m, replace=False)
            b = rng.choice(n, m, replace=False)
            ma = KMeans(n_clusters=k, n_init=n_init, random_state=int(rng.integers(1_000_000_000))).fit(X[a])
            mb = KMeans(n_clusters=k, n_init=n_init, random_state=int(rng.integers(1_000_000_000))).fit(X[b])
            aris.append(adjusted_rand_score(ma.predict(X), mb.predict(X)))
        rows.append({"k": k, "mean_ari": float(np.mean(aris)), "std_ari": float(np.std(aris)),
                     "min_ari": float(np.min(aris))})
    return pd.DataFrame(rows)


def choose_k(stability, min_sizes, tolerance=TOLERANCE, min_rows=MIN_CLUSTER_ROWS):
    """The largest k whose stability is within `tolerance` of the best, among k whose full-data
    solution has no cluster smaller than min_rows. Raises if no k qualifies."""
    ok = stability[stability["k"].map(min_sizes) >= min_rows]
    if ok.empty:
        raise ValueError(f"no k has every cluster at {min_rows}+ rows: smallest clusters {min_sizes}")
    best = ok["mean_ari"].max()
    return int(ok[ok["mean_ari"] >= best - tolerance]["k"].max())


def relabel_by_size(labels, centroids):
    """Archetype ids 1..k, largest first (ties by old label, so it is deterministic). Returns
    (new_labels, reordered_centroids)."""
    k = len(centroids)
    sizes = np.bincount(labels, minlength=k)
    order = sorted(range(k), key=lambda c: (-sizes[c], c))
    mapping = {old: new for new, old in enumerate(order)}
    return np.array([mapping[l] + 1 for l in labels]), centroids[order]


def assign_rows(Xw, centroids, weights):
    """Nearest centroid for each row, using only the features the row has. A partial row's squared
    distance is rescaled by (sum of all squared weights / sum of its available squared weights), so
    distances are comparable with full rows. A complete row reduces to plain nearest-centroid.
    Returns (labels 0-based, distances, number of features used)."""
    avail = ~np.isnan(Xw)
    w2 = weights ** 2
    scale = w2.sum() / (avail * w2).sum(axis=1)
    diff = np.where(avail[:, None, :], Xw[:, None, :] - centroids[None, :, :], 0.0)
    d2 = (diff ** 2).sum(axis=2) * scale[:, None]
    labels = d2.argmin(axis=1)
    return labels, np.sqrt(d2[np.arange(len(labels)), labels]), avail.sum(axis=1)


def profile(df, labels, features=CLUSTERING_FEATURES, groups=FEATURE_GROUPS, top=4):
    """One dict per archetype: size, share, position mix, group means and the features furthest
    from 50 (the percentile of a typical player), in percentile points."""
    pct = df[["pct_" + f for f in features]].to_numpy(dtype=float)
    out = []
    for a in sorted(set(labels)):
        mask = labels == a
        means = pct[mask].mean(axis=0)
        delta = dict(zip(features, means - 50.0))
        ranked = sorted(delta.items(), key=lambda kv: kv[1])
        pos = df.loc[mask, "primary_position"].value_counts(normalize=True)
        out.append({
            "archetype": int(a), "rows": int(mask.sum()), "share": float(mask.mean()),
            "position_mix": {p: float(pos.get(p, 0.0)) for p in ("DF", "MF", "FW")},
            "group_means": {g: float(np.mean([means[features.index(f)] for f in feats])) for g, feats in groups.items()},
            "highest": [(f, d) for f, d in reversed(ranked[-top:])],
            "lowest": ranked[:top],
        })
    return out


def format_profile(p):
    mix = " / ".join(f"{k} {v:.0%}" for k, v in p["position_mix"].items())
    groups = ", ".join(f"{g} {v:.0f}" for g, v in p["group_means"].items())
    hi = ", ".join(f"{f} {d:+.0f}" for f, d in p["highest"])
    lo = ", ".join(f"{f} {d:+.0f}" for f, d in p["lowest"])
    return (f"Archetype {p['archetype']}: {p['rows']} rows ({p['share']:.1%})   position mix {mix}\n"
            f"    group means (percentile): {groups}\n    highest vs a typical player: {hi}\n    lowest:  {lo}")


def read_percentiles(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM player_season_style_percentiles")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    for c in cols:
        if c.startswith("pct_") or c in ("nineties",):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def write_tables(conn, assigned, centroids_pct, features, groups):
    group_of = {f: g for g, feats in groups.items() for f in feats}
    arch_rows = [(int(r.player_id), int(r.season_id), r.primary_position, int(r.archetype_id),
                  round(float(r.distance), 3), int(r.features_used)) for r in assigned.itertuples()]
    cent_rows = [(a + 1, f, group_of[f], round(float(centroids_pct[a, j]), 1))
                 for a in range(centroids_pct.shape[0]) for j, f in enumerate(features)]
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DROP TABLE IF EXISTS player_season_archetypes;
                CREATE TABLE player_season_archetypes (
                    player_id INTEGER NOT NULL, season_id INTEGER NOT NULL, primary_position TEXT NOT NULL,
                    archetype_id INTEGER NOT NULL, distance NUMERIC(6,3) NOT NULL, features_used INTEGER NOT NULL,
                    PRIMARY KEY (player_id, season_id));
                DROP TABLE IF EXISTS archetype_centroids;
                CREATE TABLE archetype_centroids (
                    archetype_id INTEGER NOT NULL, feature TEXT NOT NULL, feature_group TEXT NOT NULL,
                    centroid_pct NUMERIC(5,1) NOT NULL, PRIMARY KEY (archetype_id, feature));""")
            execute_values(cur, "INSERT INTO player_season_archetypes (player_id, season_id, primary_position, archetype_id, distance, features_used) VALUES %s", arch_rows)
            execute_values(cur, "INSERT INTO archetype_centroids (archetype_id, feature, feature_group, centroid_pct) VALUES %s", cent_rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


SALES_SQL = """
WITH tm_link AS (
    SELECT DISTINCT source_native_id::text AS tm_player_id, player_id AS canonical_player_id
    FROM player_source_crosswalk
    WHERE source = 'transfermarkt' AND source_native_id IS NOT NULL
),
sales AS (
    SELECT t.transfer_id, t.season_id, t.fee_amount, l.canonical_player_id
    FROM eredivisie_transfers t
    LEFT JOIN tm_link l ON l.tm_player_id = t.player_id::text
    WHERE t.direction = 'out' AND t.fee_type IN ('permanent_transfer', 'paid_loan')
      AND t.fee_amount IS NOT NULL AND t.season_id >= %s
)
SELECT COALESCE(a.archetype_id::text, 'none') AS archetype,
       COUNT(*) AS paid_sales,
       ROUND(AVG(s.fee_amount), 1) AS mean_fee_m,
       ROUND(CAST(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY s.fee_amount) AS NUMERIC), 1) AS median_fee_m,
       ROUND(100 * AVG(b.buyer_in_big5_that_season::int), 0) AS pct_to_big5_buyers
FROM sales s
LEFT JOIN player_season_archetypes a ON a.player_id = s.canonical_player_id AND a.season_id = s.season_id - 1
LEFT JOIN buyer_league_context b ON b.transfer_id = s.transfer_id
GROUP BY a.archetype_id
ORDER BY a.archetype_id NULLS LAST
"""


def sales_by_archetype(conn, first_sale_season=FIRST_SALE_SEASON):
    with conn.cursor() as cur:
        cur.execute(SALES_SQL, (first_sale_season,))
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def run(conn, ks=KS_DEFAULT, n_pairs=N_PAIRS, forced_k=None, out=print, write=True):
    df = read_percentiles(conn)
    complete, partial = split_clustering_rows(df)
    weights = feature_weights()
    out(f"Rows in player_season_style_percentiles: {len(df)}")
    out(f"  stat seasons {CLUSTERING_FIRST_SEASON}+, complete 23-feature vector: {len(complete)}   "
        f"(partial, assigned afterwards: {len(partial)})")
    X = to_matrix(complete, weights=weights)

    k_values = list(range(ks[0], ks[1] + 1))
    full = {k: fit_kmeans(X, k) for k in k_values}
    min_sizes = {k: int(np.bincount(m.labels_, minlength=k).min()) for k, m in full.items()}
    if forced_k is None:
        stab = stability_by_k(X, k_values, n_pairs=n_pairs)
        stab["smallest_cluster"] = stab["k"].map(min_sizes)
        out(f"\nStability by k ({n_pairs} subsample pairs each; mean adjusted Rand index between two fits, 1.0 = identical):")
        out(stab.round(3).to_string(index=False))
        k = choose_k(stab, min_sizes)
        out(f"\nChosen k = {k}: the largest k within {TOLERANCE} of the best stability "
            f"({stab['mean_ari'].max():.3f}) with every cluster at {MIN_CLUSTER_ROWS}+ rows.")
    else:
        k = forced_k
        out(f"\nk forced to {k} (stability search skipped).")
        if k not in full:
            full[k] = fit_kmeans(X, k)

    model = fit_kmeans(X, k, n_init=50)
    # Assign the partial rows BEFORE numbering the archetypes, so ids run largest-first by their FINAL
    # size (complete + partial rows), which is what the output table shows.
    if len(partial):
        Xp = to_matrix(partial, weights=weights)
        p_raw, p_dist, p_used = assign_rows(Xp, model.cluster_centers_, weights)
    else:
        p_raw = np.array([], dtype=int)
    all_labels, centroids_w = relabel_by_size(np.concatenate([model.labels_, p_raw]), model.cluster_centers_)
    labels, p_labels = all_labels[:len(complete)], all_labels[len(complete):]
    ward = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X)
    unweighted = KMeans(n_clusters=k, n_init=10, random_state=SEED).fit_predict(
        to_matrix(complete, weights=np.ones(len(weights))))
    out(f"\nCross-checks at k = {k} (adjusted Rand index, 1.0 = same grouping):")
    out(f"  k-means vs Ward hierarchical:               {adjusted_rand_score(labels, ward):.3f}")
    out(f"  weighted vs unweighted k-means (how much the group weighting matters): {adjusted_rand_score(labels, unweighted):.3f}")

    out("\nArchetype profiles (percentile points above or below 50, the typical player in the player's own position group):")
    for p in profile(complete, labels):
        out(format_profile(p))

    dist_w = np.linalg.norm(X - centroids_w[labels - 1], axis=1)
    assigned = pd.DataFrame({"player_id": complete["player_id"], "season_id": complete["season_id"],
                             "primary_position": complete["primary_position"], "archetype_id": labels,
                             "distance": dist_w, "features_used": len(CLUSTERING_FEATURES)})
    if len(partial):
        assigned = pd.concat([assigned, pd.DataFrame({
            "player_id": partial["player_id"], "season_id": partial["season_id"],
            "primary_position": partial["primary_position"], "archetype_id": p_labels,
            "distance": p_dist, "features_used": p_used})], ignore_index=True)
        out(f"\nPartial rows assigned by nearest centroid on the features they have: {len(partial)} "
            f"(features used: {sorted(set(int(u) for u in p_used))})")

    if not write:
        out("\n--no-write: the tables were NOT written and the sales report is skipped (it reads the written table), "
            "so the archetypes from the last real run are untouched.")
        return assigned, None
    centroids_pct = centroids_w / weights * 100.0
    write_tables(conn, assigned, centroids_pct, CLUSTERING_FEATURES, FEATURE_GROUPS)
    out(f"\nWrote {len(assigned)} rows to player_season_archetypes and {k * len(CLUSTERING_FEATURES)} to archetype_centroids.")

    sales = sales_by_archetype(conn)
    out(f"\nUsable sales by archetype (sale seasons {FIRST_SALE_SEASON}+, stats from the season before; "
        f"'none' = no archetype: unlinked, no stat row, under 5 nineties, goalkeeper, or pre-WhoScored):")
    out(sales.to_string(index=False))
    return assigned, sales


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--k", type=int, default=None, help="force k and skip the stability search")
    p.add_argument("--ks", type=int, nargs=2, default=list(KS_DEFAULT), metavar=("LO", "HI"))
    p.add_argument("--pairs", type=int, default=N_PAIRS)
    p.add_argument("--no-write", action="store_true",
                   help="explore only: do not write the archetype tables (each normal run REPLACES them)")
    args = p.parse_args()
    conn = get_connection()
    try:
        run(conn, ks=tuple(args.ks), n_pairs=args.pairs, forced_k=args.k, write=not args.no_write)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
