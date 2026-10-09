"""
Offline tests for pipelines/modeling/style_price_signal.py. Synthetic sales with a known
price rule, so the comparison must find style when it is planted and must NOT find it when
the fee depends only on the controls. The SQL is exercised against a real Postgres separately.

Run from the repo root:
    python tests/modeling/test_style_price_signal.py
"""

import sys
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "modeling"))
import cluster_archetypes as ca          # noqa: E402
import style_price_signal as sp          # noqa: E402

warnings.filterwarnings("ignore")
K = 3
FEATS = list(ca.CLUSTERING_FEATURES)
WEIGHTS = ca.feature_weights()
CENTERS = np.array([[20.0] * 23, [50.0] * 23, [80.0] * 23])
POS = ["DF", "MF", "FW"]


def synthetic_raw(n=240, style_effect=0.0, seed=3):
    """n sales by n/1.2 players. Fee (log scale) = controls rule + style_effect * archetype score."""
    rng = np.random.default_rng(seed)
    n_players = int(n / 1.2)
    pid = rng.integers(1, n_players + 1, n)
    arch = rng.integers(0, K, n)
    pct = np.clip(CENTERS[arch] + rng.normal(0, 8, (n, 23)), 0, 100)
    season = rng.integers(2014, 2026, n)
    big3 = rng.integers(0, 2, n)
    seller = np.where(big3 == 1, rng.choice(list(sp.BIG_THREE.values()), n), 999)
    born = season - rng.integers(19, 30, n)
    nineties = rng.uniform(5, 34, n)
    npg = rng.uniform(0, 0.6, n)
    ast = rng.uniform(0, 0.4, n)
    prior = rng.uniform(0, 300, n)
    log_fee = (0.6 + 1.2 * big3 + 1.5 * (npg + ast) - 0.08 * (season - born - 24) ** 2 / 4
               + 0.0005 * prior + style_effect * (arch - 1) + rng.normal(0, 0.35, n))
    raw = pd.DataFrame({
        "transfer_id": np.arange(n), "player_id": pid, "sale_season": season,
        "fee_amount": np.expm1(log_fee).clip(0.05), "seller_club_id": seller,
        "prior_season_paid_total": prior / 4, "prior_5yr_paid_total": prior,
        "buyer_league": rng.choice(["GB1", "IT1", "ES1", "OTHER"], n),
        "archetype_id": arch + 1, "primary_position": rng.choice(POS, n), "style_nineties": nineties,
        "fbref_born": born, "fbref_nineties": nineties,
        "fbref_non_penalty_goals_per90": npg, "fbref_assists_per90": ast,
        "fbref_points_per_match": rng.uniform(0.8, 2.4, n),
    })
    for j, c in enumerate(sp.PCT_COLS):
        raw[c] = pct[:, j]
    return raw


def features(raw):
    return sp.build_features(raw, CENTERS, WEIGHTS)


class TestFolds(unittest.TestCase):
    def test_every_group_in_exactly_one_test_fold_per_repeat(self):
        groups = np.repeat(np.arange(40), [1, 2, 3, 1] * 10)
        seen = {}
        for r, tr, te in sp.grouped_repeated_folds(groups, 5, 3, seed=1):
            self.assertFalse(set(groups[tr]) & set(groups[te]), "a player sits on both sides of a split")
            for g in set(groups[te]):
                self.assertNotIn((r, g), seen)
                seen[(r, g)] = True
        self.assertEqual(len(seen), 40 * 3)

    def test_every_row_tested_once_per_repeat(self):
        groups = np.arange(100) % 30
        count = np.zeros((4, 100))
        for r, tr, te in sp.grouped_repeated_folds(groups, 5, 4, seed=2):
            count[r, te] += 1
        self.assertTrue((count == 1).all())

    def test_folds_are_reproducible_and_repeats_differ(self):
        groups = np.arange(60) % 25
        a = [te.tolist() for _, _, te in sp.grouped_repeated_folds(groups, 5, 2, seed=5)]
        b = [te.tolist() for _, _, te in sp.grouped_repeated_folds(groups, 5, 2, seed=5)]
        self.assertEqual(a, b)
        self.assertNotEqual(a[:5], a[5:])

    def test_time_split_boundary(self):
        tr, te = sp.time_fold([2019, 2021, 2022, 2025])
        self.assertEqual(tr.tolist(), [0, 1])
        self.assertEqual(te.tolist(), [2, 3])


class TestLeakGuard(unittest.TestCase):
    def setUp(self):
        self.df = features(synthetic_raw())

    def test_forbidden_names_refused(self):
        for name in sorted(sp.FORBIDDEN_FEATURES):
            with self.assertRaises(ValueError, msg=name):
                sp.assert_no_leak(["age", name], self.df.assign(**{name: 1.0}))

    def test_near_copy_of_target_refused(self):
        d = self.df.copy()
        d["sneaky"] = d["log_fee"] * 2.0 + 0.01
        with self.assertRaises(ValueError):
            sp.assert_no_leak(["age", "sneaky"], d)

    def test_clean_columns_pass(self):
        sp.assert_no_leak(sp.CONTROL_NUMERIC + sp.PCT_COLS, self.df)

    def test_no_arm_uses_a_forbidden_column(self):
        for a in sp.ARM_NAMES:
            n, c, s = sp.arm_columns(a, K)
            self.assertFalse(set(n + c) & sp.FORBIDDEN_FEATURES)

    def test_compare_refuses_when_a_forbidden_column_is_an_arm_feature(self):
        old = sp.CONTROL_NUMERIC[:]
        try:
            sp.CONTROL_NUMERIC.append("buyer_page_fee")
            d = self.df.assign(buyer_page_fee=1.0)
            with self.assertRaises(ValueError):
                sp.compare(d, K, WEIGHTS, n_repeats=1, n_boot=5, arms=(1,), models=("ridge",))
        finally:
            sp.CONTROL_NUMERIC[:] = old

    def test_spend_features_are_the_prior_windows_only(self):
        self.assertIn("log_prior_season_spend", sp.CONTROL_NUMERIC)
        self.assertIn("log_prior_5yr_spend", sp.CONTROL_NUMERIC)
        used = " ".join(sp.CONTROL_NUMERIC)
        for banned in ("season_paid", "trailing", "pct_of_buyer"):
            self.assertNotIn(banned, used)


class TestBuildFeatures(unittest.TestCase):
    def test_hand_computed_row(self):
        raw = synthetic_raw(n=6)
        raw.loc[0, ["fee_amount", "sale_season", "fbref_born", "fbref_nineties",
                    "fbref_non_penalty_goals_per90", "fbref_assists_per90", "seller_club_id",
                    "prior_season_paid_total", "prior_5yr_paid_total"]] = [
            9.0, 2020, 1997, 20.0, 0.30, 0.15, 610, 40.0, 100.0]
        f = features(raw).iloc[0]
        self.assertAlmostEqual(f["log_fee"], np.log(10.0))
        self.assertEqual(f["age"], 23)
        self.assertAlmostEqual(f["log_nineties"], np.log(21.0))
        self.assertAlmostEqual(f["production"], 0.45)
        self.assertEqual(f["seller_big3"], 1.0)
        self.assertAlmostEqual(f["log_prior_season_spend"], np.log(41.0))
        self.assertAlmostEqual(f["log_prior_5yr_spend"], np.log(101.0))

    def test_non_big3_seller_flag_and_missing_minutes_fall_back_to_style_nineties(self):
        raw = synthetic_raw(n=6)
        raw.loc[1, ["seller_club_id", "fbref_nineties", "style_nineties"]] = [5, np.nan, 12.0]
        f = features(raw).iloc[1]
        self.assertEqual(f["seller_big3"], 0.0)
        self.assertAlmostEqual(f["log_nineties"], np.log(13.0))

    def test_distance_to_own_centroid_is_smallest_for_clean_rows(self):
        raw = synthetic_raw(n=90)
        raw[sp.PCT_COLS] = CENTERS[raw["archetype_id"].to_numpy() - 1]
        f = features(raw)
        d = f[[f"dist_to_{j + 1}" for j in range(K)]].to_numpy()
        self.assertTrue((d.argmin(axis=1) + 1 == raw["archetype_id"].to_numpy()).all())
        self.assertTrue(np.allclose(d.min(axis=1), 0.0))

    def test_missing_buyer_league_becomes_unknown(self):
        raw = synthetic_raw(n=6)
        raw.loc[0, "buyer_league"] = None
        self.assertEqual(features(raw).loc[0, "buyer_league"], "UNKNOWN")


class TestCentroidMatrix(unittest.TestCase):
    def test_orders_by_archetype_and_feature(self):
        rows = [(a, f, 10.0 * a + i) for a in (2, 1) for i, f in enumerate(FEATS)]
        m = sp.centroid_matrix(pd.DataFrame(rows, columns=["archetype_id", "feature", "centroid_pct"]))
        self.assertEqual(m.shape, (2, 23))
        self.assertEqual(m[0, 0], 10.0)
        self.assertEqual(m[1, 22], 42.0)

    def test_missing_feature_raises(self):
        rows = [(1, f, 1.0) for f in FEATS[:-1]]
        with self.assertRaises(ValueError):
            sp.centroid_matrix(pd.DataFrame(rows, columns=["archetype_id", "feature", "centroid_pct"]))


class TestBootstrap(unittest.TestCase):
    def test_clearly_better_arm_has_negative_interval(self):
        rng = np.random.default_rng(0)
        groups = np.arange(200)
        base = rng.uniform(0.8, 1.2, 200)
        arm = base * 0.5
        point, lo, hi = sp.cluster_bootstrap_diff(arm, base, groups, n_boot=200)
        self.assertLess(hi, 0)
        self.assertLess(point, 0)

    def test_identical_arms_give_zero(self):
        e = np.random.default_rng(1).uniform(0.5, 1.5, 100)
        point, lo, hi = sp.cluster_bootstrap_diff(e, e, np.arange(100), n_boot=50)
        self.assertEqual((point, lo, hi), (0.0, 0.0, 0.0))

    def test_resamples_whole_players(self):
        # one player holds all the error difference: the interval must reach zero when that player is dropped
        groups = np.array([0] * 5 + list(range(1, 30)))
        base = np.ones(34)
        arm = base.copy()
        arm[:5] = 0.0
        point, lo, hi = sp.cluster_bootstrap_diff(arm, base, groups, n_boot=300)
        self.assertLess(point, 0)
        self.assertGreaterEqual(hi, 0.0)


class TestComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signal = sp.compare(features(synthetic_raw(n=360, style_effect=0.9)), K, WEIGHTS,
                                n_repeats=3, n_boot=150, arms=(1, 2, 3, 5), models=("ridge",))
        cls.noise = sp.compare(features(synthetic_raw(n=360, style_effect=0.0)), K, WEIGHTS,
                               n_repeats=3, n_boot=150, arms=(1, 2, 3, 4, 5), models=("ridge",))

    def test_planted_style_effect_is_found_by_archetype_and_distances(self):
        g = self.signal[self.signal["scheme"] == "grouped"].set_index("arm")
        for arm in (2, 3):
            self.assertLess(g.loc[arm, "ci_high"], 0, f"arm {arm} missed a planted effect")
            self.assertLess(g.loc[arm, "rmse_log"], g.loc[1, "rmse_log"])

    def test_no_style_effect_means_no_clear_gain(self):
        g = self.noise[self.noise["scheme"] == "grouped"].set_index("arm")
        for arm in (2, 3, 4, 5):
            self.assertGreaterEqual(g.loc[arm, "ci_high"], 0, f"arm {arm} claims signal from noise")

    def test_controls_row_is_its_own_baseline(self):
        c = self.noise[self.noise["arm"] == 1]
        self.assertTrue((c["diff_vs_controls"] == 0).all())

    def test_both_schemes_reported(self):
        self.assertEqual(set(self.noise["scheme"]), {"grouped", "time"})

    def test_time_scheme_scores_only_the_test_seasons(self):
        df = features(synthetic_raw(n=360))
        n_test = int((df["sale_season"] > sp.TIME_SPLIT_LAST_TRAIN_SEASON).sum())
        t = self.noise[self.noise["scheme"] == "time"]
        self.assertTrue((t["n_scored"] == n_test).all())

    def test_every_arm_scores_every_row_under_grouped_folds(self):
        g = self.noise[self.noise["scheme"] == "grouped"]
        self.assertEqual(set(g["n_scored"]), {360})

    def test_verdict_wording(self):
        text = sp.verdict(self.signal)
        self.assertIn("arm 2", text)
        self.assertNotIn("arm 1 ", text)

    def test_verdict_requires_every_combination(self):
        r = pd.DataFrame([
            {"arm": 2, "ci_high": -0.1}, {"arm": 2, "ci_high": 0.05},
            {"arm": 3, "ci_high": -0.1}, {"arm": 3, "ci_high": -0.2},
            {"arm": 4, "ci_high": 0.1}, {"arm": 4, "ci_high": 0.2},
        ])
        r["arm_name"] = r["arm"].map(sp.ARM_NAMES)
        text = sp.verdict(r)
        self.assertRegex(text, r"arm 2 .*mixed")
        self.assertRegex(text, r"arm 3 .*ADDS signal")
        self.assertRegex(text, r"arm 4 .*no clear gain")


class TestModels(unittest.TestCase):
    def test_pc1_arm_fits_inside_pipeline_and_predicts(self):
        df = features(synthetic_raw(n=120))
        n, c, s = sp.arm_columns(4, K)
        pred = sp.oof_grouped(df, n, c, s, "gbm", WEIGHTS, 5, 1)
        self.assertEqual(pred.shape, (1, 120))
        self.assertFalse(np.isnan(pred).any())

    def test_unseen_category_in_a_test_fold_does_not_crash(self):
        df = features(synthetic_raw(n=120))
        df.loc[df.index[0], "buyer_league"] = "RARE"
        n, c, s = sp.arm_columns(1, K)
        pred = sp.oof_grouped(df, n, c, s, "ridge", WEIGHTS, 5, 1)
        self.assertFalse(np.isnan(pred).any())

    def test_missing_controls_are_imputed_not_dropped(self):
        df = features(synthetic_raw(n=120))
        df.loc[df.index[:20], "seller_points_per_match"] = np.nan
        n, c, s = sp.arm_columns(1, K)
        pred = sp.oof_grouped(df, n, c, s, "ridge", WEIGHTS, 5, 1)
        self.assertFalse(np.isnan(pred).any())

    def test_same_folds_for_every_arm(self):
        df = features(synthetic_raw(n=120))
        a = [te.tolist() for _, _, te in sp.grouped_repeated_folds(df["player_id"], 5, 2, sp.SEED)]
        b = [te.tolist() for _, _, te in sp.grouped_repeated_folds(df["player_id"], 5, 2, sp.SEED)]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
