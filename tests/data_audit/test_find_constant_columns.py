"""
Offline tests for data_audit/find_constant_columns.py.

Run from the repo root:
    python tests/data_audit/test_find_constant_columns.py
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data_audit"))
import find_constant_columns as fcc   # noqa: E402


def make(season, n, pos="DF", nineties=10.0, pid0=1, **cols):
    """n rows; every extra column is a list/array of n values or a scalar."""
    data = {"player_id": range(pid0, pid0 + n), "season_id": season, "fbref_position": pos,
            "fbref_nineties": nineties, "canonical_name": [f"P{i}" for i in range(pid0, pid0 + n)]}
    for k, v in cols.items():
        data[k] = v if np.ndim(v) else [v] * n
    return pd.DataFrame(data)


def one(findings, column, season):
    m = findings[(findings.column == column) & (findings.season_id == season)]
    return None if m.empty else m.iloc[0]


class ScanTests(unittest.TestCase):
    def test_a_column_of_zeros_is_constant_even_though_it_has_no_nulls(self):
        f = fcc.scan(make(2016, 40, crosses=0.0, varied=range(40)))
        r = one(f, "crosses", 2016)
        self.assertEqual((r.kind, r.value, r.non_null, r.rows), ("constant", 0.0, 40, 40))
        self.assertIsNone(one(f, "varied", 2016))

    def test_an_all_null_column_is_empty(self):
        f = fcc.scan(make(2014, 40, shots=np.nan, varied=range(40)))
        self.assertEqual(one(f, "shots", 2014).kind, "empty")

    def test_a_column_with_too_few_values_is_sparse_not_constant(self):
        vals = [1.0] * 5 + [np.nan] * 35                       # five identical values among 40 rows
        r = one(fcc.scan(make(2014, 40, partial=vals)), "partial", 2014)
        self.assertEqual((r.kind, r.non_null), ("sparse", 5))

    def test_a_varied_column_is_not_reported(self):
        self.assertTrue(fcc.scan(make(2019, 40, good=range(40))).empty)

    def test_exactly_two_distinct_values_is_not_constant(self):
        self.assertTrue(fcc.scan(make(2019, 40, binary=[0.0] * 20 + [1.0] * 20)).empty)

    def test_a_season_below_the_minimum_row_count_is_not_judged(self):
        self.assertTrue(fcc.scan(make(2016, 29, crosses=0.0)).empty)
        self.assertEqual(one(fcc.scan(make(2016, 30, crosses=0.0)), "crosses", 2016).kind, "constant")

    def test_each_season_is_judged_on_its_own(self):
        df = pd.concat([make(2016, 40, crosses=0.0), make(2019, 40, pid0=100, crosses=range(40))], ignore_index=True)
        f = fcc.scan(df)
        self.assertEqual(one(f, "crosses", 2016).kind, "constant")
        self.assertIsNone(one(f, "crosses", 2019))

    def test_rows_under_the_nineties_floor_are_ignored(self):
        df = pd.concat([make(2016, 40, crosses=0.0),
                        make(2016, 20, pid0=500, nineties=2.0, crosses=range(20))], ignore_index=True)   # varied, but low minutes
        self.assertEqual(one(fcc.scan(df), "crosses", 2016).kind, "constant")

    def test_outfield_columns_are_judged_on_outfield_rows_only(self):
        df = pd.concat([make(2016, 40, crosses=0.0),
                        make(2016, 20, pos="GK", pid0=500, crosses=range(20))], ignore_index=True)       # keepers vary, outfield does not
        self.assertEqual(one(fcc.scan(df), "crosses", 2016).kind, "constant")

    def test_keeper_columns_are_judged_on_keepers_only(self):
        outfield = make(2016, 40, gk_saves=np.nan)                                     # outfield players have no keeper stats
        keepers_ok = make(2016, 20, pos="GK", pid0=500, gk_saves=range(20))
        self.assertTrue(fcc.scan(pd.concat([outfield, keepers_ok], ignore_index=True)).empty)       # NOT called empty
        keepers_zero = make(2016, 20, pos="GK", pid0=500, gk_saves=0.0)
        r = one(fcc.scan(pd.concat([outfield, keepers_zero], ignore_index=True)), "gk_saves", 2016)
        self.assertEqual((r.kind, r.value), ("constant", 0.0))

    def test_keeper_seasons_use_the_smaller_row_minimum(self):
        self.assertEqual(one(fcc.scan(make(2016, 15, pos="GK", gk_saves=0.0)), "gk_saves", 2016).kind, "constant")
        self.assertTrue(fcc.scan(make(2016, 14, pos="GK", gk_saves=0.0)).empty)

    def test_primary_position_decides_who_is_a_keeper(self):
        df = make(2016, 40, pos="GK", gk_saves=0.0)
        self.assertEqual(one(fcc.scan(df), "gk_saves", 2016).kind, "constant")

    def test_ids_text_and_season_are_never_judged(self):
        f = fcc.scan(make(2016, 40, tm_foot="right", fbref_born=1990, ws_whoscored_player_id=7))
        self.assertTrue(f.empty)

    def test_a_negative_zero_and_zero_are_the_same_value(self):
        self.assertEqual(one(fcc.scan(make(2016, 40, z=[0.0, -0.0] * 20)), "z", 2016).kind, "constant")


class GroupingTests(unittest.TestCase):
    def test_columns_with_the_same_kind_value_and_seasons_are_merged(self):
        df = pd.concat([make(s, 40, pid0=1000 * i, a=0.0, b=0.0, c=range(40), d=7.0) for i, s in enumerate([2016, 2017], 1)], ignore_index=True)
        groups = fcc.group_findings(fcc.scan(df))
        self.assertEqual(sorted(groups[("constant", 0.0, (2016, 2017))]), ["a", "b"])
        self.assertEqual(groups[("constant", 7.0, (2016, 2017))], ["d"])

    def test_the_report_names_columns_seasons_and_values(self):
        text = fcc.format_report(fcc.scan(make(2016, 40, crosses=0.0)))
        self.assertIn("CONSTANT", text)
        self.assertIn("seasons [2016] (value 0): 1 column(s): crosses", text)

    def test_constant_columns_are_all_named_but_other_groups_are_truncated(self):
        const = {f"c{i}": 0.0 for i in range(9)}
        empty = {f"e{i}": np.nan for i in range(9)}
        text = fcc.format_report(fcc.scan(make(2016, 40, **const, **empty)))
        for i in range(9):
            self.assertIn(f"c{i}", text)                                  # every constant column is named
        self.assertNotIn("(+", text.split("--- EMPTY")[0])                # no truncation in the CONSTANT section
        empty_section = text.split("--- EMPTY")[1]
        self.assertIn("(+3 more; full list in the CSV)", empty_section)   # the EMPTY section is truncated at 6
        self.assertIn("e5", empty_section)
        for hidden in ("e6", "e7", "e8"):
            self.assertNotIn(hidden, empty_section)                       # and the extra names really are hidden

    def test_a_clean_dataset_says_so(self):
        self.assertEqual(fcc.format_report(fcc.scan(make(2019, 40, good=range(40)))), "No constant, empty or sparse columns found.")


if __name__ == "__main__":
    unittest.main(verbosity=1)
