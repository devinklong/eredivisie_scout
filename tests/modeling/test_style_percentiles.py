"""
Offline tests for pipelines/modeling/build_style_percentiles.py. Synthetic data
only, with expectations worked out by hand. The DB path is exercised separately
against a real Postgres.

Run from the repo root:
    python tests/modeling/test_style_percentiles.py
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "modeling"))
import build_style_percentiles as bsp   # noqa: E402

COLUMNS = list(bsp.READ_COLUMNS)


def rows(season, pos, n, pid0, nineties=10.0, values=None, team="T", **extra):
    """n players. Every style feature equals the player's value (1..n by default), shots per 90
    included (via the raw count), except height (kept inside the sane range) and the guard
    columns (plenty of attempts)."""
    values = list(range(1, n + 1)) if values is None else list(values)
    out = []
    for i, v in enumerate(values):
        r = {c: float(v) for c in bsp.RAW_FEATURES}
        r["fbref_shots"] = float(v) * nineties        # so derived_shots_per90 equals the player's value
        r.update(player_id=pid0 + i, canonical_name=f"P{pid0 + i}", team=team, season_id=season,
                 fbref_position=pos, fbref_nineties=nineties, tm_height_cm=160.0 + ((pid0 + i) % 40),
                 ws_passes=500.0, ws_take_ons=50.0, ws_aerials=50.0)
        r.update(extra)
        out.append(r)
    return pd.DataFrame(out, columns=COLUMNS)


def frame(*parts):
    return pd.concat(parts, ignore_index=True)


def one(result, pid, season):
    return result[(result.player_id == pid) & (result.season_id == season)].iloc[0]


class PercentileMathTests(unittest.TestCase):
    def test_distinct_values_use_midpoint_percentiles_and_never_hit_100(self):
        got = bsp.mean_percentile_rank(pd.Series([10, 20, 30, 40])).tolist()
        self.assertEqual(got, [12.5, 37.5, 62.5, 87.5])

    def test_ties_share_the_midpoint_of_their_ranks(self):
        got = bsp.mean_percentile_rank(pd.Series([5, 5, 9])).round(1).tolist()
        self.assertEqual(got, [33.3, 33.3, 83.3])           # (0+1)/3 for both, (2+0.5)/3 for the 9

    def test_nan_stays_nan_and_is_not_counted_in_n(self):
        got = bsp.mean_percentile_rank(pd.Series([1.0, np.nan, 3.0])).tolist()
        self.assertEqual(got[0], 25.0)
        self.assertTrue(np.isnan(got[1]))
        self.assertEqual(got[2], 75.0)

    def test_all_nan_does_not_raise(self):
        self.assertTrue(bsp.mean_percentile_rank(pd.Series([np.nan, np.nan])).isna().all())


class PositionTests(unittest.TestCase):
    def test_primary_position_is_the_first_token(self):
        self.assertEqual(bsp.primary_position("FW,MF"), "FW")
        self.assertEqual(bsp.primary_position("MF,DF"), "MF")
        self.assertEqual(bsp.primary_position(" gk "), "GK")
        self.assertIsNone(bsp.primary_position(""))
        self.assertIsNone(bsp.primary_position(None))
        self.assertIsNone(bsp.primary_position(float("nan")))


class DominantRowTests(unittest.TestCase):
    def test_keeps_the_row_with_the_most_nineties_and_counts_movers(self):
        df = frame(rows(2018, "DF", 1, 1, nineties=6.0, team="PSV"), rows(2018, "DF", 1, 1, nineties=9.0, team="Ajax"),
                   rows(2018, "DF", 1, 2, nineties=12.0, team="AZ"))
        kept, n_multi = bsp.pick_dominant_rows(df)
        self.assertEqual(n_multi, 1)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[kept.player_id == 1].iloc[0].team, "Ajax")

    def test_a_tie_is_broken_by_team_name_deterministically(self):
        df = frame(rows(2018, "DF", 1, 1, nineties=7.0, team="PSV"), rows(2018, "DF", 1, 1, nineties=7.0, team="Ajax"))
        for _ in range(3):
            kept, _ = bsp.pick_dominant_rows(df.sample(frac=1))
            self.assertEqual(kept.iloc[0].team, "Ajax")

    def test_different_seasons_are_different_player_seasons(self):
        df = frame(rows(2018, "DF", 1, 1), rows(2019, "DF", 1, 1))
        kept, n_multi = bsp.pick_dominant_rows(df)
        self.assertEqual((len(kept), n_multi), (2, 0))


class BuildPercentileTests(unittest.TestCase):
    def setUp(self):
        regular = frame(*[rows(s, p, 40, pid0) for s, p, pid0 in
                          [(2018, "DF", 1000), (2018, "MF", 2000), (2018, "FW", 3000),
                           (2019, "DF", 4000), (2019, "MF", 5000), (2019, "FW", 6000)]])
        self.regular = regular

    def test_excluded_rows_never_appear_and_included_rows_are_counted(self):
        extras = frame(rows(2018, "GK", 5, 7000),                                    # goalkeepers: left out of v1
                       rows(2018, "", 2, 7100),                                      # blank position
                       rows(2018, "DF", 3, 7200, nineties=4.9),                      # under the floor
                       rows(2018, "DF", 2, 7300).assign(player_id=np.nan))           # no canonical player
        result, report = bsp.build_percentiles(frame(self.regular, extras))
        self.assertEqual(len(result), 240)
        self.assertEqual(set(result.primary_position), {"DF", "MF", "FW"})
        self.assertEqual(result.groupby(["player_id", "season_id"]).size().max(), 1)      # one row per player-season
        self.assertEqual(report["input_rows"], 240 + 5 + 2 + 3 + 2)
        self.assertEqual(report["after_nineties_floor"], 240 + 5 + 2)     # GK and blank have enough minutes
        self.assertEqual(report["after_outfield_only"], 240)

    def test_goalkeepers_are_excluded_even_when_there_are_enough_to_rank(self):
        keepers = rows(2018, "GK", 40, 7000)                    # a full-size GK group: excluded by position, not by size
        result, _ = bsp.build_percentiles(frame(self.regular, keepers))
        self.assertNotIn("GK", set(result.primary_position))
        self.assertEqual(len(result), 240)

    def test_the_nineties_floor_is_inclusive_at_exactly_five(self):
        edge = rows(2018, "DF", 30, 9000).assign(fbref_nineties=5.0)
        result, _ = bsp.build_percentiles(edge)
        self.assertEqual(len(result), 30)

    def test_percentiles_are_within_season_and_position_not_across(self):
        df = frame(rows(2018, "DF", 40, 1000),                                       # values 1..40
                   rows(2018, "FW", 40, 3000, values=range(21, 61)),                 # values 21..60
                   rows(2019, "DF", 40, 4000, values=range(41, 81)))                 # next season, higher values
        result, _ = bsp.build_percentiles(df)
        # the SAME raw value 21 is mid-pack among defenders and the very bottom among forwards
        self.assertEqual(one(result, 1020, 2018).pct_ws_touches_per90, 51.2)         # DF rank 21 of 40: 20.5/40
        self.assertEqual(one(result, 3000, 2018).pct_ws_touches_per90, 1.2)          # FW rank 1 of 40: 0.5/40 = 1.25
        # a 2019 defender with value 41 is the bottom of 2019, though it would top 2018
        self.assertEqual(one(result, 4000, 2019).pct_ws_touches_per90, 1.2)
        self.assertEqual(one(result, 1039, 2018).pct_ws_touches_per90, 98.8)         # 2018's value 40 is its top

    def test_group_size_column(self):
        result, _ = bsp.build_percentiles(self.regular)
        self.assertEqual(set(result.group_size), {40})

    def test_the_mover_is_ranked_once_with_their_dominant_row(self):
        mover = frame(rows(2018, "DF", 1, 1500, nineties=6.0, team="PSV", values=[500]),
                      rows(2018, "DF", 1, 1500, nineties=9.0, team="Ajax", values=[0.5]))   # dominant row = lowest value
        result, report = bsp.build_percentiles(frame(self.regular, mover))
        self.assertEqual(report["multi_row_player_seasons"], 1)
        self.assertEqual(len(result[result.player_id == 1500]), 1)
        self.assertEqual(one(result, 1500, 2018).nineties, 9.0)
        self.assertEqual(one(result, 1500, 2018).pct_ws_touches_per90, 1.2)          # 0.5 of 41
        self.assertEqual(one(result, 1000, 2018).pct_ws_touches_per90, 3.7)          # value 1 now rank 2: 1.5/41

    def test_a_mover_is_floored_on_their_dominant_row_not_their_total(self):
        both_short = frame(rows(2018, "DF", 1, 8000, nineties=4.0, team="A"), rows(2018, "DF", 1, 8000, nineties=3.0, team="B"))
        enough = frame(rows(2018, "DF", 1, 8001, nineties=6.0, team="A"), rows(2018, "DF", 1, 8001, nineties=3.0, team="B"))
        result, _ = bsp.build_percentiles(frame(self.regular, both_short, enough))
        self.assertEqual(len(result[result.player_id == 8000]), 0)       # 4.0 and 3.0: neither qualifies (7 combined is not used)
        self.assertEqual(len(result[result.player_id == 8001]), 1)       # 6.0 qualifies


class GuardTests(unittest.TestCase):
    def _group(self, **per_row):
        df = rows(2018, "DF", 40, 1000)
        for k, v in per_row.items():
            df.loc[df.player_id == 1000, k] = v
        return df

    def test_a_rate_with_too_few_attempts_is_nulled_and_not_counted_in_n(self):
        # one defender is 3-for-3 on take-ons (rate 1000, would top the group), with only 3 attempts
        df = rows(2018, "DF", 40, 1000, values=[1000] + list(range(1, 40)))
        df.loc[0, "ws_take_ons"] = 3.0
        result, report = bsp.build_percentiles(df)
        self.assertTrue(np.isnan(one(result, 1000, 2018).pct_ws_take_ons_won_pct))
        self.assertEqual(report["rates_nulled"]["ws_take_ons_won_pct"], 1)
        self.assertEqual(one(result, 1039, 2018).pct_ws_take_ons_won_pct, 98.7)      # (39-0.5)/39, not (39-0.5)/40
        self.assertFalse(np.isnan(one(result, 1000, 2018).pct_ws_take_ons_per90))    # his other features still rank

    def test_each_rate_has_its_own_minimum_and_the_boundary_is_kept(self):
        for feat, (count_col, minimum) in bsp.RATE_GUARDS.items():
            below = self._group(**{count_col: float(minimum - 1)})
            at = self._group(**{count_col: float(minimum)})
            r_below, _ = bsp.build_percentiles(below)
            r_at, _ = bsp.build_percentiles(at)
            self.assertTrue(np.isnan(one(r_below, 1000, 2018)["pct_" + feat]), feat)
            self.assertFalse(np.isnan(one(r_at, 1000, 2018)["pct_" + feat]), feat)

    def test_an_impossible_height_is_nulled_and_reported_but_the_edges_are_kept(self):
        df = rows(2018, "DF", 40, 1000)
        df.loc[0, "tm_height_cm"] = 875.0
        df.loc[1, "tm_height_cm"] = 149.0
        df.loc[2, "tm_height_cm"] = 150.0
        df.loc[3, "tm_height_cm"] = 215.0
        result, report = bsp.build_percentiles(df)
        self.assertTrue(np.isnan(one(result, 1000, 2018).pct_tm_height_cm))
        self.assertTrue(np.isnan(one(result, 1001, 2018).pct_tm_height_cm))
        self.assertFalse(np.isnan(one(result, 1002, 2018).pct_tm_height_cm))
        self.assertFalse(np.isnan(one(result, 1003, 2018).pct_tm_height_cm))
        self.assertEqual(report["bad_heights"], [(1000, 875.0), (1001, 149.0)])

    def test_a_feature_needs_30_non_null_values_in_the_group_to_be_ranked(self):
        sparse = rows(2018, "DF", 40, 1000)
        sparse.loc[:10, "fbref_crosses_per90"] = np.nan                   # 11 missing -> 29 left
        result, _ = bsp.build_percentiles(sparse)
        self.assertTrue(result.pct_fbref_crosses_per90.isna().all())
        exact = rows(2018, "DF", 40, 1000)
        exact.loc[:9, "fbref_crosses_per90"] = np.nan                     # 10 missing -> 30 left
        result, _ = bsp.build_percentiles(exact)
        self.assertEqual(result.pct_fbref_crosses_per90.notna().sum(), 30)

    def test_a_group_below_the_minimum_size_stops_the_run(self):
        with self.assertRaises(bsp.GroupTooSmall):
            bsp.build_percentiles(rows(2018, "DF", 29, 1000))
        bsp.build_percentiles(rows(2018, "DF", 30, 1000))                  # exactly the minimum is fine


class CoverageTests(unittest.TestCase):
    def test_a_season_without_whoscored_data_shows_zero_whoscored_coverage(self):
        early = rows(2011, "DF", 40, 1000)
        for c in bsp.STYLE_FEATURES:
            if c.startswith("ws_"):
                early[c] = np.nan
        early["ws_passes"] = early["ws_take_ons"] = early["ws_aerials"] = np.nan
        late = rows(2015, "DF", 40, 2000)
        result, _ = bsp.build_percentiles(frame(early, late))
        cov = bsp.coverage_by_season(result)
        self.assertEqual((cov.loc[2011, "with_whoscored"], cov.loc[2011, "with_fbref"]), (0.0, 1.0))
        self.assertEqual((cov.loc[2015, "with_whoscored"], cov.loc[2015, "with_fbref"]), (1.0, 1.0))


class EmptyFeatureSeasonTests(unittest.TestCase):
    def test_names_exactly_which_features_are_empty_in_which_seasons(self):
        early = rows(2011, "DF", 40, 1000)
        for c in bsp.STYLE_FEATURES:
            if c.startswith("ws_"):
                early[c] = np.nan
        early["ws_passes"] = early["ws_take_ons"] = early["ws_aerials"] = np.nan
        misc_gap = rows(2018, "DF", 40, 2000)                          # FBref misc missing, the rest fine
        for c in ("fbref_crosses_per90", "fbref_offsides_per90", "fbref_fouls_drawn_per90", "fbref_fouls_committed_per90"):
            misc_gap[c] = np.nan
        full = rows(2015, "DF", 40, 3000)
        result, _ = bsp.build_percentiles(frame(early, misc_gap, full))
        gaps = bsp.empty_feature_seasons(result)
        ws = sorted(f for f in bsp.STYLE_FEATURES if f.startswith("ws_"))
        self.assertEqual(sorted(gaps[(2011,)]), ws)
        self.assertEqual(sorted(gaps[(2018,)]), sorted(["fbref_crosses_per90", "fbref_offsides_per90",
                                                        "fbref_fouls_drawn_per90", "fbref_fouls_committed_per90"]))
        self.assertEqual(set(gaps), {(2011,), (2018,)})               # nothing else is reported

    def test_a_complete_dataset_reports_no_gaps(self):
        result, _ = bsp.build_percentiles(frame(rows(2015, "DF", 40, 1000), rows(2016, "DF", 40, 2000)))
        self.assertEqual(bsp.empty_feature_seasons(result), {})


class DerivedShotsTests(unittest.TestCase):
    """fbref_shots_per90 (FBref's own column) is a literal 0 for 2016 and 2017, so shots per 90
    are derived from the repaired fbref_shots count instead."""

    def test_the_native_per90_column_is_not_a_feature_but_the_repaired_count_is_read(self):
        self.assertNotIn("fbref_shots_per90", bsp.STYLE_FEATURES)
        self.assertIn("derived_shots_per90", bsp.STYLE_FEATURES)
        self.assertIn("fbref_shots", bsp.READ_COLUMNS)
        self.assertNotIn("derived_shots_per90", bsp.READ_COLUMNS)          # it is computed, not read

    def test_it_is_a_per_90_rate_so_the_same_shots_in_fewer_minutes_rank_higher(self):
        df = rows(2018, "DF", 40, 1000)
        df["fbref_shots"] = 20.0                                          # every player took 20 shots
        df["fbref_nineties"] = [5.0 + 0.5 * i for i in range(40)]         # 5.0 ... 24.5 nineties
        result, _ = bsp.build_percentiles(df)
        self.assertEqual(one(result, 1000, 2018).pct_derived_shots_per90, 98.8)    # fewest minutes: 4.0 per 90, the top
        self.assertEqual(one(result, 1039, 2018).pct_derived_shots_per90, 1.2)     # most minutes: ~0.8 per 90, the bottom

    def test_a_missing_shot_count_gives_a_null_percentile_not_a_zero(self):
        df = rows(2018, "DF", 40, 1000)
        df.loc[0, "fbref_shots"] = np.nan
        result, _ = bsp.build_percentiles(df)
        self.assertTrue(np.isnan(one(result, 1000, 2018).pct_derived_shots_per90))
        self.assertFalse(np.isnan(one(result, 1000, 2018).pct_ws_touches_per90))

    def test_a_season_where_the_count_is_all_zero_is_not_ranked(self):
        zero = rows(2016, "DF", 40, 1000)
        zero["fbref_shots"] = 0.0                                         # FBref's literal zeros
        ok = rows(2019, "DF", 40, 2000)
        result, report = bsp.build_percentiles(frame(zero, ok))
        self.assertTrue(result[result.season_id == 2016].pct_derived_shots_per90.isna().all())
        self.assertTrue(result[result.season_id == 2019].pct_derived_shots_per90.notna().all())
        self.assertEqual(report["constant_features"]["derived_shots_per90"], [2016])
        self.assertIn("derived_shots_per90", bsp.empty_feature_seasons(result)[(2016,)])


class AddDerivedTests(unittest.TestCase):
    def test_zero_or_negative_nineties_gives_nan_not_infinity(self):
        df = rows(2018, "DF", 3, 1000)
        df["fbref_nineties"] = [0.0, -1.0, 10.0]
        out = bsp.add_derived(df)
        self.assertTrue(out.derived_shots_per90.iloc[:2].isna().all())
        self.assertFalse(np.isinf(out.derived_shots_per90.fillna(0)).any())
        self.assertEqual(out.derived_shots_per90.iloc[2], 3.0)            # the third player's value is 3: 30 shots in 10.0 nineties


class ConstantFeatureTests(unittest.TestCase):
    def test_an_all_identical_group_is_nulled_while_a_varied_group_in_the_same_season_is_ranked(self):
        flat = rows(2018, "DF", 40, 1000)
        flat["fbref_crosses_per90"] = 0.0                                  # every defender: 0 crosses
        varied = rows(2018, "MF", 40, 2000)
        result, report = bsp.build_percentiles(frame(flat, varied))
        self.assertTrue(result[result.primary_position == "DF"].pct_fbref_crosses_per90.isna().all())
        self.assertTrue(result[result.primary_position == "MF"].pct_fbref_crosses_per90.notna().all())
        self.assertEqual(report["constant_features"], {"fbref_crosses_per90": [2018]})

    def test_two_distinct_values_are_enough_to_rank(self):
        df = rows(2018, "DF", 40, 1000)
        df["fbref_crosses_per90"] = [0.0] * 20 + [1.0] * 20
        result, report = bsp.build_percentiles(df)
        self.assertTrue(result.pct_fbref_crosses_per90.notna().all())
        self.assertNotIn("fbref_crosses_per90", report["constant_features"])
        self.assertEqual(sorted(set(result.pct_fbref_crosses_per90)), [25.0, 75.0])        # ties share the midpoint of their block

    def test_nulls_do_not_make_a_varied_group_look_constant(self):
        df = rows(2018, "DF", 40, 1000)
        df["fbref_crosses_per90"] = [1.0] * 30 + [np.nan] * 10             # one value among 30 non-null: constant
        result, report = bsp.build_percentiles(df)
        self.assertTrue(result.pct_fbref_crosses_per90.isna().all())
        self.assertIn("fbref_crosses_per90", report["constant_features"])


class SchemaTests(unittest.TestCase):
    def test_ddl_has_every_percentile_column_and_a_primary_key(self):
        ddl = bsp.table_ddl()
        for f in bsp.STYLE_FEATURES:
            self.assertIn(f"pct_{f} NUMERIC(5,1)", ddl)
        self.assertIn("PRIMARY KEY (player_id, season_id)", ddl)

    def test_the_excluded_feature_stays_excluded_and_every_guarded_rate_is_a_feature(self):
        self.assertNotIn("ws_ground_duel_win_pct", bsp.STYLE_FEATURES)
        self.assertTrue(set(bsp.RATE_GUARDS) <= set(bsp.STYLE_FEATURES))
        self.assertEqual(len(bsp.STYLE_FEATURES), len(set(bsp.STYLE_FEATURES)))


if __name__ == "__main__":
    unittest.main(verbosity=1)
