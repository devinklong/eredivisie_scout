"""
Offline tests for pipelines/modeling/cluster_archetypes.py. Synthetic data with known
structure. The database path (tables, sales report) is exercised against a real Postgres
separately.

Run from the repo root:
    python tests/modeling/test_cluster_archetypes.py
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "modeling"))
import build_style_percentiles as bsp   # noqa: E402
import cluster_archetypes as ca         # noqa: E402

FEATS = list(ca.CLUSTERING_FEATURES)
PCT = ["pct_" + f for f in FEATS]


def frame(n, center, noise, seed, season=2015, pid0=1, pos="DF"):
    """n players around one center (a list of 23 percentiles), clipped to 0-100."""
    rng = np.random.default_rng(seed)
    vals = np.clip(np.asarray(center, float) + rng.normal(0, noise, (n, len(FEATS))), 0, 100)
    df = pd.DataFrame(vals, columns=PCT)
    df.insert(0, "player_id", range(pid0, pid0 + n))
    df.insert(1, "season_id", season)
    df.insert(2, "primary_position", pos)
    return df


CENTERS = [[15.0] * 23, [85.0] * 23, [15.0] * 12 + [85.0] * 11, [85.0] * 12 + [15.0] * 11]    # four far-apart styles


def four_blobs(n=120, noise=6.0, seed=1):
    return pd.concat([frame(n, c, noise, seed + i, pid0=1 + i * 1000) for i, c in enumerate(CENTERS)], ignore_index=True)


class GroupTests(unittest.TestCase):
    def test_the_groups_cover_the_clustering_vector_exactly(self):
        ca.check_groups()
        self.assertEqual(sorted(f for fs in ca.FEATURE_GROUPS.values() for f in fs), sorted(FEATS))

    def test_a_feature_missing_from_the_groups_is_refused(self):
        groups = {g: [f for f in fs if f != "derived_shots_per90"] for g, fs in ca.FEATURE_GROUPS.items()}
        with self.assertRaises(ValueError) as cm:
            ca.check_groups(groups=groups)
        self.assertIn("ungrouped", str(cm.exception))

    def test_a_feature_in_two_groups_is_refused(self):
        groups = dict(ca.FEATURE_GROUPS, aerial=["ws_aerials_per90", "derived_shots_per90"])
        with self.assertRaises(ValueError) as cm:
            ca.check_groups(groups=groups)
        self.assertIn("more than one group", str(cm.exception))

    def test_a_grouped_feature_outside_the_vector_is_refused(self):
        groups = dict(ca.FEATURE_GROUPS, aerial=["ws_aerials_per90", "tm_height_cm"])
        with self.assertRaises(ValueError):
            ca.check_groups(groups=groups)


class WeightTests(unittest.TestCase):
    def test_every_group_contributes_the_same_total_squared_weight(self):
        w = ca.feature_weights()
        for g, feats in ca.FEATURE_GROUPS.items():
            self.assertAlmostEqual(sum(w[FEATS.index(f)] ** 2 for f in feats), 1.0, places=9, msg=g)

    def test_a_defending_feature_weighs_less_than_a_lone_shooting_feature(self):
        w = ca.feature_weights()
        self.assertAlmostEqual(w[FEATS.index("ws_tackles_per90")], 1 / np.sqrt(10))
        self.assertAlmostEqual(w[FEATS.index("derived_shots_per90")], 1.0)

    def test_flipping_the_ten_defending_features_moves_a_player_exactly_as_far_as_flipping_shots(self):
        """The point of the weighting: without it the defending block would be ten times as loud."""
        base = pd.DataFrame([[50.0] * 23], columns=PCT)
        deff, shot = base.copy(), base.copy()
        for f in ca.FEATURE_GROUPS["defending"]:
            deff["pct_" + f] = 90.0                                         # +40 points on all ten
        shot["pct_derived_shots_per90"] = 90.0                              # +40 points on the one
        w = ca.feature_weights()
        d_def = np.linalg.norm(ca.to_matrix(deff, weights=w) - ca.to_matrix(base, weights=w))
        d_shot = np.linalg.norm(ca.to_matrix(shot, weights=w) - ca.to_matrix(base, weights=w))
        self.assertAlmostEqual(d_def, d_shot, places=9)
        ones = np.ones(23)                                                   # unweighted: ten times the squared distance
        d_def_raw = np.linalg.norm(ca.to_matrix(deff, weights=ones) - ca.to_matrix(base, weights=ones))
        d_shot_raw = np.linalg.norm(ca.to_matrix(shot, weights=ones) - ca.to_matrix(base, weights=ones))
        self.assertAlmostEqual(d_def_raw / d_shot_raw, np.sqrt(10))

    def test_a_group_weight_scales_that_group_only(self):
        w = ca.feature_weights(group_weights={"shooting": 2.0})
        self.assertAlmostEqual(w[FEATS.index("derived_shots_per90")], 2.0)
        self.assertAlmostEqual(w[FEATS.index("ws_aerials_per90")], 1.0)

    def test_matrix_scales_percentiles_to_0_1_and_keeps_nan(self):
        df = pd.DataFrame([[100.0] * 23], columns=PCT)
        df["pct_derived_shots_per90"] = np.nan
        m = ca.to_matrix(df)[0]
        self.assertAlmostEqual(m[FEATS.index("ws_aerials_per90")], 1.0)                   # 100/100 * weight 1
        self.assertAlmostEqual(m[FEATS.index("ws_tackles_per90")], 1 / np.sqrt(10))
        self.assertTrue(np.isnan(m[FEATS.index("derived_shots_per90")]))


class SplitTests(unittest.TestCase):
    def test_complete_partial_and_unusable_rows_are_separated(self):
        complete = frame(5, [50.0] * 23, 1, 1, season=2015, pid0=1)
        partial = frame(3, [50.0] * 23, 1, 2, season=2015, pid0=100)
        partial.loc[:, "pct_derived_shots_per90"] = np.nan                    # missing one feature
        early = frame(4, [50.0] * 23, 1, 3, season=2011, pid0=200)            # before WhoScored
        empty = frame(2, [50.0] * 23, 1, 4, season=2016, pid0=300)
        empty[PCT] = np.nan                                                    # nothing at all
        c, p = ca.split_clustering_rows(pd.concat([complete, partial, early, empty], ignore_index=True))
        self.assertEqual(sorted(c.player_id), [1, 2, 3, 4, 5])
        self.assertEqual(sorted(p.player_id), [100, 101, 102])

    def test_the_first_season_is_included(self):
        df = pd.concat([frame(3, [50.0] * 23, 1, 1, season=2012), frame(3, [50.0] * 23, 1, 2, season=2013, pid0=10)], ignore_index=True)
        c, _ = ca.split_clustering_rows(df)
        self.assertEqual(set(c.season_id), {2013})


class StabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.X = ca.to_matrix(four_blobs())
        cls.stab = ca.stability_by_k(cls.X, [4, 8], n_pairs=8).set_index("k")

    def test_the_true_number_of_clusters_is_nearly_perfectly_stable(self):
        self.assertGreater(self.stab.loc[4, "mean_ari"], 0.95)

    def test_splitting_real_blobs_into_more_pieces_is_less_stable(self):
        self.assertLess(self.stab.loc[8, "mean_ari"], self.stab.loc[4, "mean_ari"] - 0.1)

    def test_it_is_deterministic_and_each_k_is_seeded_on_its_own(self):
        again = ca.stability_by_k(self.X, [3, 4, 5], n_pairs=8).set_index("k")
        self.assertAlmostEqual(again.loc[4, "mean_ari"], self.stab.loc[4, "mean_ari"], places=12)

    def test_the_two_fits_use_independent_subsamples(self):
        """If both fits saw the same rows the over-split case would look far more stable than it is."""
        draws = []
        real = np.random.default_rng

        class Recording:
            def __init__(self, rng):
                self.rng = rng
            def choice(self, *a, **kw):
                r = self.rng.choice(*a, **kw)
                draws.append(tuple(np.sort(r)[:10]))
                return r
            def integers(self, *a, **kw):
                return self.rng.integers(*a, **kw)

        np.random.default_rng = lambda seed=None: Recording(real(seed))
        try:
            ca.stability_by_k(self.X, [4], n_pairs=2)
        finally:
            np.random.default_rng = real
        self.assertEqual(len(draws), 4)                                  # two subsamples per pair, two pairs
        self.assertNotEqual(draws[0], draws[1])                          # the pair's two subsamples differ
        self.assertNotEqual(draws[2], draws[3])


class ChooseKTests(unittest.TestCase):
    def table(self, aris, ks=(6, 7, 8, 9, 10)):
        return pd.DataFrame({"k": list(ks), "mean_ari": aris})

    def test_takes_the_largest_k_within_tolerance_of_the_best(self):
        stab = self.table([0.90, 0.89, 0.80, 0.70, 0.60])
        self.assertEqual(ca.choose_k(stab, {k: 100 for k in range(6, 11)}, tolerance=0.03, min_rows=60), 7)

    def test_the_tolerance_matters(self):
        stab = self.table([0.90, 0.89, 0.80, 0.70, 0.60])
        self.assertEqual(ca.choose_k(stab, {k: 100 for k in range(6, 11)}, tolerance=0.15, min_rows=60), 8)
        self.assertEqual(ca.choose_k(stab, {k: 100 for k in range(6, 11)}, tolerance=0.0, min_rows=60), 6)

    def test_a_k_with_a_tiny_cluster_is_ruled_out_even_if_most_stable(self):
        stab = self.table([0.95, 0.90, 0.85, 0.80, 0.70])
        sizes = {6: 30, 7: 100, 8: 100, 9: 100, 10: 100}                        # k=6 has a 30-row cluster
        self.assertEqual(ca.choose_k(stab, sizes, tolerance=0.03, min_rows=60), 7)

    def test_the_size_floor_is_inclusive(self):
        stab = self.table([0.9, 0.5, 0.5, 0.5, 0.5])
        self.assertEqual(ca.choose_k(stab, {6: 60, 7: 100, 8: 100, 9: 100, 10: 100}, tolerance=0.03, min_rows=60), 6)

    def test_no_qualifying_k_raises(self):
        with self.assertRaises(ValueError):
            ca.choose_k(self.table([0.9, 0.8, 0.7, 0.6, 0.5]), {k: 10 for k in range(6, 11)}, min_rows=60)


class RelabelTests(unittest.TestCase):
    def test_ids_run_largest_first_and_centroids_follow(self):
        labels = np.array([0, 0, 0, 1, 1, 1, 1, 1, 2, 2])                      # sizes 3, 5, 2
        centroids = np.array([[0.0], [1.0], [2.0]])
        new, cent = ca.relabel_by_size(labels, centroids)
        self.assertEqual(new.tolist(), [2, 2, 2, 1, 1, 1, 1, 1, 3, 3])
        self.assertEqual(cent.ravel().tolist(), [1.0, 0.0, 2.0])

    def test_ties_break_by_the_old_label(self):
        new, cent = ca.relabel_by_size(np.array([0, 0, 1, 1]), np.array([[0.0], [1.0]]))
        self.assertEqual(new.tolist(), [1, 1, 2, 2])
        self.assertEqual(cent.ravel().tolist(), [0.0, 1.0])


class AssignTests(unittest.TestCase):
    def test_complete_rows_get_the_same_label_as_k_means(self):
        X = ca.to_matrix(four_blobs(n=60))
        model = ca.fit_kmeans(X, 4)
        labels, dist, used = ca.assign_rows(X, model.cluster_centers_, ca.feature_weights())
        self.assertEqual(labels.tolist(), model.predict(X).tolist())
        self.assertTrue((used == 23).all())

    def test_a_partial_distance_is_rescaled_to_full_dimension(self):
        weights = np.ones(4)
        row = np.array([[1.0, np.nan, np.nan, np.nan]])
        labels, dist, used = ca.assign_rows(row, np.zeros((1, 4)), weights)
        self.assertEqual((labels.tolist(), used.tolist()), ([0], [1]))
        self.assertAlmostEqual(dist[0], 2.0)                                    # (1-0)^2 * (4 / 1) = 4, sqrt = 2

    def test_a_missing_feature_contributes_nothing_whatever_the_centroid_holds_there(self):
        """A row missing feature 2 must not be pulled by what the centroid has in that coordinate."""
        centroids = np.array([[0.0, 5.0], [10.0, 0.0]])                          # nothing known about feature 2 for the row
        row = np.array([[1.0, np.nan]])
        labels, dist, used = ca.assign_rows(row, centroids, np.ones(2))
        self.assertEqual(labels.tolist(), [0])                                   # nearest on feature 1 alone: |1-0| < |1-10|
        self.assertAlmostEqual(dist[0], np.sqrt(1.0 * (2.0 / 1.0)))              # (1-0)^2 * (2 total / 1 available) = 2
        flipped = np.array([[0.0, 500.0], [10.0, 0.0]])                          # a wild value in the missing coordinate changes nothing
        labels2, dist2, _ = ca.assign_rows(row, flipped, np.ones(2))
        self.assertEqual((labels2.tolist(), round(float(dist2[0]), 9)), (labels.tolist(), round(float(dist[0]), 9)))

    def test_the_scale_uses_squared_weights_not_a_feature_count(self):
        weights = np.array([2.0, 1.0])
        row = np.array([[1.0, np.nan]])                                          # has the heavy feature only
        _, dist, _ = ca.assign_rows(row, np.zeros((1, 2)), weights)
        self.assertAlmostEqual(dist[0], np.sqrt(1.0 * (4.0 + 1.0) / 4.0))        # (1)^2 * (sum w^2 5 / avail w^2 4)

    def test_a_row_missing_one_feature_still_finds_its_style(self):
        blobs = four_blobs(n=60)
        model = ca.fit_kmeans(ca.to_matrix(blobs), 4)
        probe = frame(1, CENTERS[2], 0.0, 9)
        probe["pct_derived_shots_per90"] = np.nan
        label, _, used = ca.assign_rows(ca.to_matrix(probe), model.cluster_centers_, ca.feature_weights())
        full_label = model.predict(ca.to_matrix(frame(1, CENTERS[2], 0.0, 9)))
        self.assertEqual(label.tolist(), full_label.tolist())
        self.assertEqual(used.tolist(), [22])


class ProfileTests(unittest.TestCase):
    def test_size_position_mix_and_the_features_that_define_the_archetype(self):
        a = frame(30, [50.0] * 23, 0.0, 1, pos="DF", pid0=1)
        a["pct_ws_aerials_per90"] = 90.0                                         # archetype 1: aerial, mostly defenders
        a.loc[:5, "primary_position"] = "MF"                                      # 6 MF + 24 DF
        b = frame(10, [50.0] * 23, 0.0, 2, pos="FW", pid0=100)
        b["pct_derived_shots_per90"] = 95.0                                      # archetype 2: shooters, all forwards
        df = pd.concat([a, b], ignore_index=True)
        labels = np.array([1] * 30 + [2] * 10)
        p1, p2 = ca.profile(df, labels)
        self.assertEqual((p1["rows"], round(p1["share"], 3)), (30, 0.75))
        self.assertEqual(p1["position_mix"], {"DF": 0.8, "MF": 0.2, "FW": 0.0})
        self.assertEqual(p1["highest"][0], ("ws_aerials_per90", 40.0))
        self.assertEqual(p2["position_mix"], {"DF": 0.0, "MF": 0.0, "FW": 1.0})
        self.assertEqual(p2["highest"][0], ("derived_shots_per90", 45.0))
        self.assertAlmostEqual(p2["group_means"]["shooting"], 95.0)
        self.assertAlmostEqual(p2["group_means"]["aerial"], 50.0)

    def test_lowest_features_are_reported_as_negative_deltas(self):
        a = frame(10, [50.0] * 23, 0.0, 1)
        a["pct_ws_clearances_per90"] = 10.0
        (p,) = ca.profile(a, np.array([1] * 10))
        self.assertEqual(p["lowest"][0], ("ws_clearances_per90", -40.0))

    def test_the_text_block_names_the_archetype_and_its_traits(self):
        a = frame(10, [50.0] * 23, 0.0, 1)
        a["pct_ws_aerials_per90"] = 90.0
        text = ca.format_profile(ca.profile(a, np.array([3] * 10))[0])
        self.assertIn("Archetype 3: 10 rows", text)
        self.assertIn("ws_aerials_per90 +40", text)


class DeterminismTests(unittest.TestCase):
    def test_the_same_seed_gives_the_same_clustering(self):
        X = ca.to_matrix(four_blobs(n=60))
        self.assertEqual(ca.fit_kmeans(X, 4).labels_.tolist(), ca.fit_kmeans(X, 4).labels_.tolist())


if __name__ == "__main__":
    unittest.main(verbosity=1)
