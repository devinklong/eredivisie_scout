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


def synthetic_raw(n=240, style_effect=0.0, seed=3, interaction_effect=0.0):
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
    if interaction_effect:      # a Big-5 buyer pays more the higher the style score (applied after every random draw, so other tests keep their data)
        big5 = raw["buyer_league"].isin(sp.BIG5_LEAGUES).to_numpy(dtype=float)
        raw["fee_amount"] = np.expm1(np.log1p(raw["fee_amount"]) + interaction_effect * (arch - 1) * big5)
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
        self.assertTrue((c["diff_vs_baseline"] == 0).all())

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


class TestInteractionArms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def run(**kw):
            return sp.compare(features(synthetic_raw(n=480, **kw)), K, WEIGHTS, n_repeats=3, n_boot=150,
                              arms=(1, 2, 4, 6, 7), models=("ridge",))
        cls.interaction = run(interaction_effect=0.9)
        cls.main_effect_only = run(style_effect=0.9)
        cls.nothing = run()

    @staticmethod
    def grouped(res, arm):
        return res[(res["scheme"] == "grouped") & (res["arm"] == arm)].iloc[0]

    def test_a_planted_big5_interaction_is_found_against_the_main_effects_arm(self):
        self.assertLess(self.grouped(self.interaction, 6)["ci_high"], 0)
        self.assertLess(self.grouped(self.interaction, 7)["ci_high"], 0)

    def test_a_main_effect_of_style_is_not_credited_to_the_interaction_arms(self):
        # style pays everywhere, Big-5 or not: arms 2 and 4 find it, arms 6 and 7 add nothing to arms 2 and 4
        self.assertLess(self.grouped(self.main_effect_only, 2)["ci_high"], 0)
        self.assertGreaterEqual(self.grouped(self.main_effect_only, 6)["ci_high"], 0)
        self.assertGreaterEqual(self.grouped(self.main_effect_only, 7)["ci_high"], 0)

    def test_no_effect_means_no_clear_gain_for_either_interaction_arm(self):
        for arm in (6, 7):
            self.assertGreaterEqual(self.grouped(self.nothing, arm)["ci_high"], 0)

    def test_each_interaction_arm_is_compared_with_its_own_baseline(self):
        r = self.interaction
        self.assertEqual(dict(zip(r["arm"], r["baseline_arm"])), {1: 1, 2: 1, 4: 1, 6: 2, 7: 4})
        g = r[r["scheme"] == "grouped"].set_index("arm")
        self.assertAlmostEqual(g.loc[6, "diff_vs_baseline"], g.loc[6, "rmse_log"] - g.loc[2, "rmse_log"], places=6)
        self.assertAlmostEqual(g.loc[7, "diff_vs_baseline"], g.loc[7, "rmse_log"] - g.loc[4, "rmse_log"], places=6)

    def test_share_of_repeats_beating_the_baseline_is_measured_against_the_baseline_arm(self):
        # planted interaction: arm 6 beats arm 2 in every repeat. Main effect only: arm 6 beats the controls
        # in every repeat (it contains arm 2) but must NOT beat arm 2 in most of them.
        self.assertEqual(self.grouped(self.interaction, 6)["share_repeats_beating_baseline"], 1.0)
        self.assertLess(self.grouped(self.main_effect_only, 6)["share_repeats_beating_baseline"], 1.0)
        self.assertTrue(np.isnan(self.grouped(self.interaction, 1)["share_repeats_beating_baseline"]))

    def test_an_interaction_arm_without_its_baseline_is_refused(self):
        with self.assertRaises(ValueError):
            sp.compare(features(synthetic_raw(n=120)), K, WEIGHTS, n_repeats=1, n_boot=5, arms=(1, 6), models=("ridge",))
        with self.assertRaises(ValueError):
            sp.compare(features(synthetic_raw(n=120)), K, WEIGHTS, n_repeats=1, n_boot=5, arms=(1, 2, 7), models=("ridge",))

    def test_the_verdict_names_the_baseline_of_an_interaction_arm(self):
        text = sp.verdict(self.interaction)
        self.assertRegex(text, r"arm 6 .*combinations beat arm 2")
        self.assertRegex(text, r"arm 7 .*combinations beat arm 4")
        self.assertRegex(text, r"arm 2 .*beat the controls")

    def test_features_flag_big5_buyers_and_build_the_archetype_products(self):
        raw = synthetic_raw(n=60)
        raw.loc[raw.index[:5], "buyer_league"] = ["GB1", "ES1", "IT1", "L1", "FR1"]
        raw.loc[raw.index[5:8], "buyer_league"] = ["NL1", "OTHER", None]
        df = features(raw)
        self.assertEqual(df["buyer_big5"].iloc[:8].tolist(), [1, 1, 1, 1, 1, 0, 0, 0])      # NL1, OTHER and unknown are not Big-5
        for j in range(1, K + 1):
            expect = ((df["archetype_id"] == j) & (df["buyer_big5"] == 1)).astype(float)
            self.assertTrue((df[f"arch_x_big5_{j}"] == expect).all())
        self.assertTrue((df[[f"arch_x_big5_{j}" for j in range(1, K + 1)]].sum(axis=1) == df["buyer_big5"]).all())   # exactly one archetype per Big-5 sale

    def test_arm_columns_for_the_interaction_arms(self):
        n6, c6, s6 = sp.arm_columns(6, K)
        self.assertIn("buyer_big5", n6)
        self.assertEqual([c for c in n6 if c.startswith("arch_x_big5_")], [f"arch_x_big5_{j}" for j in range(1, K + 1)])
        self.assertIn("archetype", c6)
        self.assertIsNone(s6)
        n7, c7, s7 = sp.arm_columns(7, K)
        self.assertIn("buyer_big5", n7)
        self.assertEqual(s7, "pc1_x_big5")

    def test_the_pc1_product_is_zero_for_non_big5_buyers_and_the_component_for_big5_buyers(self):
        rng = np.random.default_rng(0)
        X = np.hstack([rng.uniform(0, 100, (40, 23)), (np.arange(40) % 2).reshape(-1, 1)])
        out = sp.PC1TimesFlag(WEIGHTS).fit(X).transform(X)
        self.assertEqual(out.shape, (40, 2))
        np.testing.assert_allclose(out[X[:, -1] == 0, 1], 0)
        np.testing.assert_allclose(out[X[:, -1] == 1, 1], out[X[:, -1] == 1, 0])

    def test_the_pc1_axis_is_fitted_on_the_training_rows_only(self):
        rng = np.random.default_rng(1)
        train = np.hstack([rng.uniform(0, 100, (60, 23)), np.ones((60, 1))])
        test = np.hstack([rng.uniform(0, 100, (20, 23)) * np.array([1] * 22 + [0.01]), np.ones((20, 1))])
        t = sp.PC1TimesFlag(WEIGHTS).fit(train)
        first = t.transform(test)
        t.fit(np.vstack([train, test]))                       # refitting on more rows must be able to change the axis
        self.assertFalse(np.allclose(first, t.transform(test)))

    def test_interaction_arms_fit_inside_the_pipeline_and_predict_for_both_models(self):
        df = features(synthetic_raw(n=120))
        for arm in (6, 7):
            for kind in ("ridge", "gbm"):
                n, c, s = sp.arm_columns(arm, K)
                pred = sp.oof_grouped(df, n, c, s, kind, WEIGHTS, 5, 1)
                self.assertFalse(np.isnan(pred).any(), (arm, kind))


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
