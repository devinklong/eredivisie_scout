"""
Offline tests for pipelines/modeling/outgrow_signal.py. Synthetic sales where the label "outgrew the league"
(fee at or above that season's Big-5 median signing fee) depends on style in one world and only on the
player-side controls in the other, so the comparison must find style when it is planted and must NOT find it
when it is not. The market-index SQL is the query already run on the real data and is not repeated here.

Run from the repo root:
    python tests/modeling/test_outgrow_signal.py
"""

import sys
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "pipelines" / "modeling"))
import outgrow_signal as og              # noqa: E402
import style_price_signal as sp          # noqa: E402
from test_style_price_signal import CENTERS, K, WEIGHTS, synthetic_raw   # noqa: E402

warnings.filterwarnings("ignore")


def market_for(raw, q_median=0.7, q_mean=0.8):
    """A market index per sale season placed so that roughly 1 - q_median of sales clear the median bar."""
    g = raw.groupby("sale_season")["fee_amount"]
    return pd.DataFrame({"median_fee": g.quantile(q_median), "mean_fee": g.quantile(q_mean)})


def frame(raw, bar="median"):
    return og.build_outgrow_frame(raw, CENTERS, WEIGHTS, market_for(raw), bar)


class TestTarget(unittest.TestCase):
    def setUp(self):
        self.raw = synthetic_raw(n=60)

    def test_a_sale_clears_the_bar_at_exactly_the_bar_and_not_below_it(self):
        raw = self.raw.copy()
        market = pd.DataFrame({"median_fee": 5.0, "mean_fee": 9.0}, index=sorted(raw["sale_season"].unique()))
        raw.loc[raw.index[:3], "fee_amount"] = [4.99, 5.0, 5.01]
        df, _ = og.build_outgrow_frame(raw, CENTERS, WEIGHTS, market, "median")
        self.assertEqual(df["outgrew"].iloc[:3].tolist(), [0, 1, 1])

    def test_the_mean_bar_is_a_different_bar_from_the_median_bar(self):
        raw = self.raw.copy()
        market = pd.DataFrame({"median_fee": 5.0, "mean_fee": 9.0}, index=sorted(raw["sale_season"].unique()))
        raw.loc[raw.index[:1], "fee_amount"] = 7.0
        self.assertEqual(og.build_outgrow_frame(raw, CENTERS, WEIGHTS, market, "median")[0]["outgrew"].iloc[0], 1)
        self.assertEqual(og.build_outgrow_frame(raw, CENTERS, WEIGHTS, market, "mean")[0]["outgrew"].iloc[0], 0)

    def test_each_sale_is_judged_against_its_own_season(self):
        raw = self.raw.copy()
        seasons = sorted(raw["sale_season"].unique())
        market = pd.DataFrame({"median_fee": np.arange(len(seasons), dtype=float) + 1.0, "mean_fee": 99.0}, index=seasons)
        raw["fee_amount"] = 5.5
        df, _ = og.build_outgrow_frame(raw, CENTERS, WEIGHTS, market, "median")
        expect = (df["sale_season"].map(dict(zip(seasons, np.arange(len(seasons)) + 1.0))) <= 5.5).astype(int)
        self.assertEqual(df["outgrew"].tolist(), expect.tolist())

    def test_a_season_without_a_market_index_is_dropped_and_counted(self):
        raw = self.raw.copy()
        market = market_for(raw)
        gone = market.index[0]
        n_gone = int((raw["sale_season"] == gone).sum())
        df, dropped = og.build_outgrow_frame(raw, CENTERS, WEIGHTS, market.drop(index=gone), "median")
        self.assertEqual(dropped, n_gone)
        self.assertEqual(len(df), len(raw) - n_gone)
        self.assertNotIn(gone, set(df["sale_season"]))

    def test_an_unknown_bar_is_refused(self):
        with self.assertRaises(ValueError):
            og.build_outgrow_frame(self.raw, CENTERS, WEIGHTS, market_for(self.raw), "p90")


class TestPlayerSideOnly(unittest.TestCase):
    def test_no_arm_uses_a_buyer_side_or_fee_derived_column(self):
        for arm in og.ARM_NAMES:
            n, c, s = og.arm_columns(arm, K)
            self.assertFalse(set(n + c) & (og.BUYER_SIDE | sp.FORBIDDEN_FEATURES), arm)

    def test_the_guard_refuses_each_buyer_side_column(self):
        for col in ("buyer_league", "buyer_big5", "log_prior_season_spend", "log_prior_5yr_spend", "arch_x_big5_2", "fee_amount"):
            with self.subTest(col=col):
                with self.assertRaises(ValueError):
                    og.assert_player_side_only(["age", col])
        og.assert_player_side_only(og.PLAYER_SIDE_NUMERIC + og.PLAYER_SIDE_CATEGORICAL)

    def test_compare_refuses_when_a_buyer_column_is_made_a_control(self):
        old = og.PLAYER_SIDE_NUMERIC[:]
        try:
            og.PLAYER_SIDE_NUMERIC.append("buyer_big5")
            d, _ = frame(synthetic_raw(n=120))
            with self.assertRaises(ValueError):
                og.compare(d, K, WEIGHTS, n_repeats=1, n_boot=5, arms=(1,), models=("logit",))
        finally:
            og.PLAYER_SIDE_NUMERIC[:] = old

    def test_the_leak_guard_refuses_a_feature_that_is_the_label(self):
        d, _ = frame(synthetic_raw(n=120))
        d["sneaky"] = d["outgrew"] * 1.0
        with self.assertRaises(ValueError):
            sp.assert_no_leak(["age", "sneaky"], d, target="outgrew")

    def test_arm_columns(self):
        n3, c3, _ = og.arm_columns(3, K)
        self.assertEqual([c for c in n3 if c.startswith("dist_to_")], [f"dist_to_{j}" for j in range(1, K + 1)])
        self.assertIn("archetype", og.arm_columns(2, K)[1])
        self.assertEqual(og.arm_columns(4, K)[2], "pc1")
        self.assertTrue(set(sp.PCT_COLS) <= set(og.arm_columns(5, K)[0]))
        with self.assertRaises(ValueError):
            og.arm_columns(6, K)


class TestScoring(unittest.TestCase):
    def test_log_loss_values(self):
        self.assertAlmostEqual(float(og.row_log_loss(np.array([1]), np.array([0.8]))[0]), -np.log(0.8))
        self.assertAlmostEqual(float(og.row_log_loss(np.array([0]), np.array([0.8]))[0]), -np.log(0.2))

    def test_a_certain_wrong_answer_is_punished_hard_but_stays_finite(self):
        loss = og.row_log_loss(np.array([1, 0]), np.array([0.0, 1.0]))
        self.assertTrue(np.isfinite(loss).all())
        self.assertGreater(loss.min(), 10)

    def test_baseline_is_the_entropy_of_the_base_rate(self):
        d = pd.DataFrame({"outgrew": [1] * 25 + [0] * 75})
        self.assertAlmostEqual(og.baseline_log_loss(d), -(0.25 * np.log(0.25) + 0.75 * np.log(0.75)), places=6)

    def test_a_training_set_with_one_class_returns_that_frequency_instead_of_failing(self):
        d, _ = frame(synthetic_raw(n=60))
        n, c, s = og.arm_columns(1, K)
        p = og.fit_predict_proba("logit", n, c, s, WEIGHTS, d.iloc[:40], d.iloc[40:], np.zeros(40, dtype=int))
        self.assertEqual(p.tolist(), [0.0] * 20)

    def test_probabilities_come_back_for_both_classifiers_and_every_arm(self):
        d, _ = frame(synthetic_raw(n=120))
        y = d["outgrew"].to_numpy()
        for arm in og.ARM_NAMES:
            for kind in ("logit", "gbm_clf"):
                n, c, s = og.arm_columns(arm, K)
                p = og.fit_predict_proba(kind, n, c, s, WEIGHTS, d.iloc[:90], d.iloc[90:], y[:90])
                self.assertEqual(p.shape, (30,), (arm, kind))
                self.assertTrue(((p >= 0) & (p <= 1)).all(), (arm, kind))

    def test_every_row_is_predicted_once_per_repeat(self):
        d, _ = frame(synthetic_raw(n=120))
        n, c, s = og.arm_columns(4, K)
        pred = og.oof_grouped(d, n, c, s, "logit", WEIGHTS, 5, 2)
        self.assertEqual(pred.shape, (2, len(d)))
        self.assertFalse(np.isnan(pred).any())


class TestFoldsAndEstimators(unittest.TestCase):
    def test_grouped_folds_are_built_from_the_player_ids(self):
        from unittest import mock
        d, _ = frame(synthetic_raw(n=120))
        n, c, s = og.arm_columns(1, K)
        with mock.patch.object(sp, "grouped_repeated_folds", wraps=sp.grouped_repeated_folds) as spy:
            og.oof_grouped(d, n, c, s, "logit", WEIGHTS, 5, 1)
        self.assertEqual(spy.call_args[0][0].tolist(), d["player_id"].tolist())

    def test_each_classifier_name_builds_the_estimator_it_names(self):
        n, c, s = og.arm_columns(1, K)
        self.assertEqual(type(sp.make_model("logit", n, c, s, WEIGHTS).steps[-1][1]).__name__, "LogisticRegressionCV")
        self.assertEqual(type(sp.make_model("gbm_clf", n, c, s, WEIGHTS).steps[-1][1]).__name__, "HistGradientBoostingClassifier")
        self.assertEqual(type(sp.make_model("ridge", n, c, s, WEIGHTS).steps[-1][1]).__name__, "RidgeCV")
        with self.assertRaises(ValueError):
            sp.make_model("nonsense", n, c, s, WEIGHTS)

    def test_the_time_scheme_trains_on_early_seasons_and_predicts_later_ones(self):
        d, _ = frame(synthetic_raw(n=240))
        n, c, s = og.arm_columns(1, K)
        te, p = og.predict_time(d, n, c, s, "logit", WEIGHTS)
        self.assertTrue((d["sale_season"].iloc[te] > sp.TIME_SPLIT_LAST_TRAIN_SEASON).all())
        self.assertEqual(len(p), len(te))


class TestBootstrap(unittest.TestCase):
    def test_identical_losses_give_zero(self):
        e = np.random.default_rng(0).uniform(0, 1, 100)
        p, lo, hi = og.cluster_bootstrap_mean_diff(e, e.copy(), np.arange(100) // 2, n_boot=100)
        self.assertEqual((p, lo, hi), (0.0, 0.0, 0.0))

    def test_a_clearly_better_arm_has_a_negative_interval(self):
        rng = np.random.default_rng(1)
        base = rng.uniform(0.5, 1.0, 200)
        p, lo, hi = og.cluster_bootstrap_mean_diff(base - 0.2, base, np.arange(200) // 2, n_boot=200)
        self.assertLess(hi, 0)
        self.assertAlmostEqual(p, -0.2)          # the point estimate is arm minus baseline, so better is negative

    def test_it_resamples_whole_players(self):
        # one player holds all the difference: resampling players must be able to lose them entirely
        base = np.zeros(40)
        arm = np.zeros(40)
        arm[:4] = -1.0
        groups = np.array([1] * 4 + list(range(2, 38)))
        p, lo, hi = og.cluster_bootstrap_mean_diff(arm, base, groups, n_boot=400)
        self.assertEqual(hi, 0.0)           # some resamples drop that player, so the upper end is no gain at all
        self.assertLess(lo, p)


class TestComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def run(**kw):
            d, _ = frame(synthetic_raw(n=480, **kw))
            return d, og.compare(d, K, WEIGHTS, n_repeats=3, n_boot=150, arms=(1, 2, 3, 4, 5), models=("logit",))
        cls.signal_df, cls.signal = run(style_effect=0.9)
        cls.noise_df, cls.noise = run()

    @staticmethod
    def grouped(res, arm):
        return res[(res["scheme"] == "grouped") & (res["arm"] == arm)].iloc[0]

    def test_a_planted_style_effect_is_found_by_archetype_and_distances(self):
        for arm in (2, 3):
            r = self.grouped(self.signal, arm)
            self.assertLess(r["ci_high"], 0, f"arm {arm} missed a planted effect")
            self.assertGreater(r["auc"], self.grouped(self.signal, 1)["auc"])

    def test_no_style_effect_means_no_clear_gain(self):
        for arm in (2, 3, 4, 5):
            self.assertGreaterEqual(self.grouped(self.noise, arm)["ci_high"], 0, f"arm {arm} claims signal from noise")

    def test_the_reported_difference_is_the_arm_log_loss_minus_the_controls_log_loss(self):
        for scheme in ("grouped", "time"):
            r = self.signal[self.signal["scheme"] == scheme].set_index("arm")
            for arm in (2, 3, 4, 5):
                self.assertAlmostEqual(r.loc[arm, "diff_vs_controls"], r.loc[arm, "log_loss"] - r.loc[1, "log_loss"], places=9)
                self.assertTrue(r.loc[arm, "ci_low"] <= r.loc[arm, "diff_vs_controls"] <= r.loc[arm, "ci_high"] or scheme == "time")

    def test_controls_are_their_own_baseline(self):
        c = self.noise[self.noise["arm"] == 1]
        self.assertTrue((c["diff_vs_controls"] == 0).all())

    def test_both_schemes_are_reported_and_the_time_scheme_scores_only_the_test_seasons(self):
        self.assertEqual(set(self.noise["scheme"]), {"grouped", "time"})
        n_test = int((self.noise_df["sale_season"] > sp.TIME_SPLIT_LAST_TRAIN_SEASON).sum())
        t = self.noise[self.noise["scheme"] == "time"]
        self.assertTrue((t["n_scored"] == n_test).all())
        self.assertEqual(set(self.noise[self.noise["scheme"] == "grouped"]["n_scored"]), {len(self.noise_df)})

    def test_positives_are_counted_per_scheme(self):
        g = self.grouped(self.noise, 1)
        self.assertEqual(g["n_positive"], int(self.noise_df["outgrew"].sum()))
        te = sp.time_fold(self.noise_df["sale_season"])[1]
        t = self.noise[(self.noise["scheme"] == "time") & (self.noise["arm"] == 1)].iloc[0]
        self.assertEqual(t["n_positive"], int(self.noise_df["outgrew"].iloc[te].sum()))

    def test_a_useful_model_beats_the_base_rate_reference(self):
        self.assertLess(self.grouped(self.signal, 2)["log_loss"], og.baseline_log_loss(self.signal_df))

    def test_baseline_arm_must_be_run(self):
        d, _ = frame(synthetic_raw(n=120))
        with self.assertRaises(ValueError):
            og.compare(d, K, WEIGHTS, n_repeats=1, n_boot=5, arms=(2,), models=("logit",))

    def test_verdict_requires_every_combination(self):
        r = pd.DataFrame([{"arm": 2, "ci_high": -0.1}, {"arm": 2, "ci_high": 0.05},
                          {"arm": 3, "ci_high": -0.1}, {"arm": 3, "ci_high": -0.2},
                          {"arm": 4, "ci_high": 0.1}, {"arm": 4, "ci_high": 0.2}])
        text = og.verdict(r)
        self.assertRegex(text, r"arm 2 .*mixed")
        self.assertRegex(text, r"arm 3 .*ADDS signal")
        self.assertRegex(text, r"arm 4 .*no clear gain")
        self.assertNotIn("arm 1 ", text)


class TestProfileTables(unittest.TestCase):
    def test_counts_rates_and_bands_by_hand(self):
        d = pd.DataFrame({
            "primary_position": ["FW"] * 4 + ["MF"] * 2,
            "age": [19, 20, 21, 27, 23, 24],
            "production": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "outgrew": [1, 1, 0, 0, 1, 0]})
        t = og.profile_tables(d)
        pos = t["position"].set_index("primary_position")
        self.assertEqual((pos.loc["FW", "sales"], pos.loc["FW", "cleared"], pos.loc["FW", "rate_pct"]), (4, 2, 50))
        self.assertEqual((pos.loc["MF", "sales"], pos.loc["MF", "cleared"], pos.loc["MF", "rate_pct"]), (2, 1, 50))
        band = t["age band"].set_index("age_band")
        self.assertEqual((band.loc["<=20", "sales"], band.loc["<=20", "cleared"]), (2, 2))      # ages 19 and 20 (edge is inclusive)
        self.assertEqual((band.loc["21-22", "sales"], band.loc["21-22", "cleared"]), (1, 0))
        self.assertEqual(band.loc["27+", "sales"], 1)
        for name, table in t.items():
            self.assertEqual(int(table["sales"].sum()), len(d), name)
        q = t["production (non-penalty goals + assists per 90)"]
        self.assertEqual(q["cleared"].tolist(), [2, 0, 0, 1])      # cut points 0.225 / 0.35 / 0.475 give quartiles [0.1, 0.2] [0.3] [0.4] [0.5, 0.6]: outcomes [1,1] [0] [0] [1,0]


if __name__ == "__main__":
    unittest.main()
