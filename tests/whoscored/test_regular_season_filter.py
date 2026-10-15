"""
Offline tests for the regular-season filter: pipelines/whoscored/build_regular_season_manifest.py
and the manifest handling in aggregate_and_load_whoscored_season.py. Synthetic double
round-robin schedules (18 clubs, 34 rounds) with play-off matches appended, so the expected
answer is known exactly.

Run from the repo root:
    python tests/whoscored/test_regular_season_filter.py
"""

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "whoscored"))
import aggregate_and_load_whoscored_season as agg      # noqa: E402
import build_regular_season_manifest as man             # noqa: E402

CLUBS = [f"Club {i:02d}" for i in range(18)]


def round_robin(clubs):
    """Circle method: returns a list of rounds, each a list of (home, away); first half then mirrored."""
    n = len(clubs)
    rot = list(clubs)
    first = []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = rot[i], rot[n - 1 - i]
            pairs.append((a, b) if r % 2 == 0 else (b, a))
        first.append(pairs)
        rot = [rot[0]] + [rot[-1]] + rot[1:-1]
    second = [[(b, a) for a, b in rnd] for rnd in first]
    return first + second


def schedule(n_rounds=34, playoff_clubs=("Club 03", "Club 04", "Club 05", "Club 06"), seed=1, playoffs=True):
    rnd = random.Random(seed)
    rows = []
    ids = list(range(1000, 1000 + 400))
    rnd.shuffle(ids)                      # ids carry NO order information
    k = 0
    for r, pairs in enumerate(round_robin(CLUBS)[:n_rounds]):
        for h, a in pairs:
            rows.append({"game_id": ids[k], "date": pd.Timestamp("2020-08-01") + pd.Timedelta(days=7 * r), "home_team": h, "away_team": a})
            k += 1
    playoff_ids = []
    if playoffs:
        c = playoff_clubs
        legs = [(c[0], c[3]), (c[3], c[0]), (c[1], c[2]), (c[2], c[1]), (c[0], c[1]), (c[1], c[0])]   # two semis, a final
        for j, (h, a) in enumerate(legs):
            gid = ids[k]
            rows.append({"game_id": gid, "date": pd.Timestamp("2021-05-10") + pd.Timedelta(days=4 * j), "home_team": h, "away_team": a})
            playoff_ids.append(gid)
            k += 1
    return pd.DataFrame(rows), playoff_ids


class TestRegularSeasonIds(unittest.TestCase):
    def test_play_offs_are_excluded_and_the_rest_is_a_clean_round_robin(self):
        s, playoff_ids = schedule()
        self.assertEqual(len(s), 306 + 6)
        regular, excluded, counts = man.regular_season_ids(s)
        self.assertEqual(len(regular), 306)
        self.assertEqual(sorted(excluded), sorted(playoff_ids))
        self.assertEqual(set(counts.values()), {34})
        self.assertEqual(len(counts), 18)

    def test_order_comes_from_the_date_not_the_id(self):
        s, playoff_ids = schedule(seed=7)
        s.loc[s["game_id"].isin(playoff_ids), "game_id"] = [1, 2, 3, 4, 5, 6]     # play-offs now have the LOWEST ids
        regular, excluded, _ = man.regular_season_ids(s)
        self.assertEqual(sorted(excluded), [1, 2, 3, 4, 5, 6])
        self.assertEqual(len(regular), 306)

    def test_a_season_without_play_offs_excludes_nothing(self):
        s, _ = schedule(playoffs=False)
        regular, excluded, _ = man.regular_season_ids(s)
        self.assertEqual((len(regular), excluded), (306, []))

    def test_extra_matches_for_one_club_only(self):
        s, playoff_ids = schedule(playoff_clubs=("Club 00", "Club 01", "Club 02", "Club 03"))
        _, excluded, counts = man.regular_season_ids(s)
        self.assertEqual(sorted(excluded), sorted(playoff_ids))
        self.assertEqual(set(counts.values()), {34})

    def test_incomplete_schedule_raises(self):
        s, _ = schedule(playoffs=False)
        with self.assertRaises(man.ManifestError):
            man.regular_season_ids(s.iloc[1:])                 # one regular match missing

    def test_a_short_club_is_reported_at_its_own_count_and_the_extra_match_is_excluded(self):
        s, _ = schedule(playoffs=False)
        first = s.sort_values("date").iloc[0]
        s = s[s["game_id"] != first["game_id"]]                  # one regular match missing: its two clubs have 33
        other = next(c for c in CLUBS if c not in (first["home_team"], first["away_team"]))
        extra = pd.DataFrame([{"game_id": 7, "date": pd.Timestamp("2021-06-01"), "home_team": first["home_team"], "away_team": other}])
        with self.assertRaises(man.ManifestError) as cm:
            man.regular_season_ids(pd.concat([s, extra]))
        self.assertIn("33", str(cm.exception))
        self.assertNotIn("35", str(cm.exception))                # the club already at 34 did not take the extra match

    def test_a_partial_extra_match_is_rejected_not_silently_dropped(self):
        s, _ = schedule(playoffs=False)
        s = pd.concat([s, pd.DataFrame([{"game_id": 5, "date": pd.Timestamp("2021-06-01"), "home_team": "Club 00", "away_team": "Club 17"}])])
        regular, excluded, _ = man.regular_season_ids(s)
        self.assertEqual(excluded, [5])                          # 35th match of both clubs: excluded
        self.assertEqual(len(regular), 306)

    def test_bad_schedules_raise(self):
        s, _ = schedule()
        with self.assertRaises(man.ManifestError):
            man.regular_season_ids(s.drop(columns=["date"]))
        t = s.copy()
        t.loc[t.index[3], "date"] = pd.NaT
        with self.assertRaises(man.ManifestError):
            man.regular_season_ids(t)
        u = pd.concat([s, s.iloc[:1]])
        with self.assertRaisesRegex(man.ManifestError, "twice"):
            man.regular_season_ids(u)

    def test_abandoned_season_keeps_everything_but_not_more_than_34_per_club(self):
        s, _ = schedule(n_rounds=26, playoffs=False)
        regular, excluded, counts = man.regular_season_ids(s, None)
        self.assertEqual((len(regular), excluded), (26 * 9, []))
        self.assertEqual(set(counts.values()), {26})
        too_many, _ = schedule()
        long = pd.concat([too_many, too_many.assign(game_id=too_many["game_id"] + 5000, date=too_many["date"] + pd.Timedelta(days=400))])
        with self.assertRaises(man.ManifestError):
            man.regular_season_ids(long, None)

    def test_same_date_ties_are_broken_by_game_id(self):
        s, _ = schedule(playoffs=False)
        s["date"] = pd.Timestamp("2020-08-01")                  # every match on one day
        regular, _, _ = man.regular_season_ids(s)
        self.assertEqual(len(regular), 306)

    def test_season_settings(self):
        s, _ = schedule(n_rounds=26, playoffs=False)
        m = man.build_manifest("2019-20", s)
        self.assertEqual(m["matches_per_club"], None)
        self.assertEqual(len(m["regular_match_ids"]), 234)
        s2, pids = schedule()
        m2 = man.build_manifest("2021-22", s2)
        self.assertEqual((m2["matches_per_club"], len(m2["regular_match_ids"]), sorted(m2["excluded_match_ids"])), (34, 306, sorted(pids)))


def match_json(player_team_passes):
    """A per-match JSON in the shape the scraper writes: category -> list of records."""
    return {"passing": [{"player": p, "team": t, "player_id": pid, "passes": n, "passes_completed": n // 2}
                        for p, t, pid, n in player_team_passes]}


class TestAggregation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "2013-14"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, mid, rows):
        (self.dir / f"{mid}.json").write_text(json.dumps(match_json(rows)))

    def test_play_off_matches_are_not_summed(self):
        for mid in range(1, 35):
            self.write(mid, [("A", "Utrecht", 11, 10)])
        for mid in (101, 102, 103, 104):
            self.write(mid, [("A", "Utrecht", 11, 10)])                     # play-off legs
        (self.dir / agg.MANIFEST_NAME).write_text(json.dumps({"regular_match_ids": list(range(1, 35))}))
        ids = agg.load_regular_match_ids(self.dir)
        totals, seen, pids, names, n = agg.aggregate_season(self.dir, ids)
        key = (11, "Utrecht")
        self.assertEqual(totals[key]["passes"], 340)
        self.assertEqual(len(seen[key]), 34)
        self.assertEqual(n, 34)

    def test_without_a_filter_everything_is_summed_as_before(self):
        for mid in (1, 2, 3):
            self.write(mid, [("A", "Utrecht", 11, 10)])
        totals, seen, *_ = agg.aggregate_season(self.dir)
        self.assertEqual(totals[(11, "Utrecht")]["passes"], 30)

    def test_the_manifest_file_is_never_read_as_a_match(self):
        self.write(1, [("A", "Utrecht", 11, 10)])
        (self.dir / agg.MANIFEST_NAME).write_text(json.dumps({"regular_match_ids": [1], "season": "2013-14"}))
        totals, seen, _, _, n = agg.aggregate_season(self.dir)
        self.assertEqual(n, 1)
        self.assertEqual(totals[(11, "Utrecht")]["passes"], 10)

    def test_missing_manifest_refuses_to_run(self):
        self.write(1, [("A", "Utrecht", 11, 10)])
        with self.assertRaises(FileNotFoundError) as cm:
            agg.load_regular_match_ids(self.dir)
        self.assertIn("build_regular_season_manifest", str(cm.exception))

    def test_ids_in_the_manifest_may_be_ints_or_strings(self):
        (self.dir / agg.MANIFEST_NAME).write_text(json.dumps({"regular_match_ids": [5, "6"]}))
        self.assertEqual(agg.load_regular_match_ids(self.dir), {"5", "6"})

    def test_written_manifest_round_trips_into_the_aggregator(self):
        s, pids = schedule()
        m = man.build_manifest("2013-14", s)
        root = Path(self.tmp.name)
        path = man.write_manifest("2013-14", m, root)
        self.assertEqual(path, self.dir / man.MANIFEST_NAME)
        ids = agg.load_regular_match_ids(self.dir)
        self.assertEqual(len(ids), 306)
        self.assertFalse(ids & {str(p) for p in pids})


class TestFailureHandling(unittest.TestCase):
    def broken(self):
        """A full season with ONE regular fixture between two clubs missing from the schedule."""
        s, _ = schedule()
        drop = s[(s["home_team"] == "Club 10") & (s["away_team"] == "Club 11")].index[0]
        gone = s[((s["home_team"] == "Club 10") & (s["away_team"] == "Club 11"))
                 | ((s["home_team"] == "Club 11") & (s["away_team"] == "Club 10"))]
        return s.drop(index=gone.index[0]), gone.iloc[0]

    def test_a_missing_fixture_fails_the_season_and_the_diagnosis_names_it(self):
        s, gone = self.broken()
        with self.assertRaises(man.ManifestError):
            man.regular_season_ids(s)
        text = man.diagnose(s)
        self.assertIn("Club 10: 33 regular", text)
        self.assertIn("Club 11: 33 regular", text)
        self.assertIn("Club 10 vs Club 11: 1 scheduled meeting", text)
        self.assertNotIn("Club 03: ", text)           # clubs with 34 are not listed

    def test_diagnose_shows_stage_values_when_the_schedule_has_them(self):
        s, _ = self.broken()
        s["stage"] = "Eredivisie"
        self.assertIn("stage values: {'Eredivisie': 311}", man.diagnose(s))

    def test_one_failed_season_does_not_stop_the_others(self):
        good, _ = schedule()
        bad, _ = self.broken()
        with tempfile.TemporaryDirectory() as tmp:
            lines, failures = man.process_seasons(
                ["2013-14", "2014-15", "2015-16"], {"2013-14": good, "2014-15": bad, "2015-16": good}.get, root=tmp)
            self.assertEqual(list(failures), ["2014-15"])
            self.assertTrue((Path(tmp) / "2013-14" / man.MANIFEST_NAME).exists())
            self.assertTrue((Path(tmp) / "2015-16" / man.MANIFEST_NAME).exists())
            self.assertFalse((Path(tmp) / "2014-15" / man.MANIFEST_NAME).exists())
            self.assertTrue(any(l.startswith("2014-15: FAILED") for l in lines))

    def test_a_stale_manifest_is_not_left_behind_for_a_failed_season_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "2013-14").mkdir()
            (Path(tmp) / "2014-15").mkdir()
            (Path(tmp) / "2013-14" / agg.MANIFEST_NAME).write_text("{}")
            self.assertEqual(agg.missing_manifests(["2013-14", "2014-15", "2015-16"], tmp), ["2014-15"])

    def test_main_exits_nonzero_when_any_season_failed(self):
        import types
        good, _ = schedule()
        bad, _ = self.broken()
        by_season = {"2013-14": good, "2014-15": bad}

        class FakeWS:
            def __init__(self, league, season):
                self.season = season

            def read_schedule(self, force_cache=True):
                return by_season[self.season].copy()

        fake = types.ModuleType("soccerdata")
        fake.WhoScored = FakeWS
        old_mod, old_root = sys.modules.get("soccerdata"), man.DATA_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            sys.modules["soccerdata"], man.DATA_ROOT = fake, Path(tmp)
            try:
                self.assertEqual(man.main(["--seasons", "2013-14"]), 0)
                self.assertEqual(man.main(["--seasons", "2013-14", "2014-15"]), 1)
                self.assertTrue((Path(tmp) / "2013-14" / man.MANIFEST_NAME).exists())     # written under DATA_ROOT only
            finally:
                man.DATA_ROOT = old_root
                if old_mod is None:
                    del sys.modules["soccerdata"]
                else:
                    sys.modules["soccerdata"] = old_mod


def staged(playoffs=True):
    s, playoff_ids = schedule(playoffs=playoffs)
    s["stage"] = ["Europa League Playoff" if g in set(playoff_ids) else "Eredivisie" for g in s["game_id"]]
    return s, playoff_ids


def with_duplicate(s):
    """The 2018-19 shape: one mid-season fixture listed twice under a different game_id."""
    row = s[(s["home_team"] == "Club 10") & (s["away_team"] == "Club 11") & (s["stage"] == "Eredivisie")].iloc[0].copy()
    row["game_id"] = 999999
    row["date"] = row["date"] + pd.Timedelta(days=2)
    return pd.concat([s, row.to_frame().T], ignore_index=True).astype({"game_id": int}), 999999


def write_files(root, season, ids):
    d = Path(root) / season
    d.mkdir(parents=True, exist_ok=True)
    for i in ids:
        (d / f"{i}.json").write_text("{}")


class TestDuplicateFixturesAndStageCheck(unittest.TestCase):
    def test_the_duplicate_really_breaks_the_date_rule_alone(self):
        s, _ = staged()
        dup, _ = with_duplicate(s)
        with self.assertRaises(man.ManifestError):
            man.regular_season_ids(dup)

    def test_duplicate_resolved_by_which_file_exists(self):
        s, playoff_ids = staged()
        dup, dup_id = with_duplicate(s)
        with tempfile.TemporaryDirectory() as tmp:
            write_files(tmp, "2018-19", [g for g in dup["game_id"] if g != dup_id])
            lines, failures = man.process_seasons(["2018-19"], {"2018-19": dup}.get, root=tmp)
            self.assertEqual(failures, {})
            self.assertIn("306 regular, 6 excluded", lines[0])
            self.assertIn(f"dropped 1 duplicate schedule row(s) with no file: [{dup_id}]", lines[0])
            m = json.loads((Path(tmp) / "2018-19" / man.MANIFEST_NAME).read_text())
            self.assertNotIn(dup_id, m["regular_match_ids"])
            self.assertEqual(m["dropped_duplicate_ids"], [dup_id])
            self.assertEqual(sorted(m["excluded_match_ids"]), sorted(playoff_ids))

    def test_duplicate_not_settled_by_files_fails_and_names_the_fixture(self):
        s, _ = staged()
        dup, dup_id = with_duplicate(s)
        for have in (list(dup["game_id"]), [g for g in dup["game_id"] if g not in (dup_id,) and g != dup.loc[dup["game_id"] != dup_id].query("home_team=='Club 10' and away_team=='Club 11' and stage=='Eredivisie'")["game_id"].iloc[0]]):
            with tempfile.TemporaryDirectory() as tmp:
                write_files(tmp, "2018-19", have)
                lines, failures = man.process_seasons(["2018-19"], {"2018-19": dup}.get, root=tmp)
                self.assertIn("2018-19", failures)
                self.assertIn("Club 10 - Club 11", failures["2018-19"])
                self.assertEqual(lines[1].count("repeated fixture"), 2)         # both rows of the pair are shown
                self.assertFalse((Path(tmp) / "2018-19" / man.MANIFEST_NAME).exists())

    def test_clean_season_is_untouched_and_labels_agree(self):
        s, _ = staged()
        with tempfile.TemporaryDirectory() as tmp:
            write_files(tmp, "2013-14", s["game_id"])
            lines, failures = man.process_seasons(["2013-14"], {"2013-14": s}.get, root=tmp)
            self.assertEqual(failures, {})
            self.assertNotIn("dropped", lines[0])
            self.assertIn("stage labels agree", lines[0])

    def test_label_disagreement_is_reported_but_the_date_rule_still_decides(self):
        s, _ = staged()
        victim = s[s["stage"] == "Eredivisie"]["game_id"].iloc[5]
        s.loc[s["game_id"] == victim, "stage"] = "Something else"
        with tempfile.TemporaryDirectory() as tmp:
            lines, failures = man.process_seasons(["2013-14"], {"2013-14": s}.get, root=tmp)
            self.assertEqual(failures, {})
            self.assertIn("306 regular", lines[0])
            self.assertIn("DISAGREE", lines[0])
            self.assertIn(str(int(victim)), lines[0])

    def test_without_a_stage_column_nothing_is_dropped(self):
        s, _ = schedule()
        cleaned, dropped = man.drop_duplicate_fixtures(s, set())
        self.assertEqual(dropped, [])
        self.assertEqual(len(cleaned), len(s))
        self.assertIsNone(man.stage_label_excluded(s))

    def test_rerun_does_not_count_its_own_manifest_as_a_match_file(self):
        s, _ = staged()
        with tempfile.TemporaryDirectory() as tmp:
            write_files(tmp, "2013-14", s["game_id"])
            man.process_seasons(["2013-14"], {"2013-14": s}.get, root=tmp)
            lines, _ = man.process_seasons(["2013-14"], {"2013-14": s}.get, root=tmp)
            self.assertIn("on disk 312: 306 regular, 6 excluded, 0 not in the schedule, 0 regular", lines[0])

    def test_a_stage_column_with_every_value_empty_is_a_single_competition(self):
        s, _ = schedule(playoffs=False)          # the abandoned-season shape: column present, all NaN
        s["stage"] = None
        with tempfile.TemporaryDirectory() as tmp:
            lines, failures = man.process_seasons(["2019-20"], {"2019-20": s}.get, root=tmp)
            self.assertEqual(failures, {})
            self.assertIn("stage labels agree", lines[0])
        self.assertEqual(man.stage_label_excluded(s), set())
        cleaned, dropped = man.drop_duplicate_fixtures(s, set())
        self.assertEqual(dropped, [])

    def test_some_missing_labels_count_as_their_own_label(self):
        s, _ = staged()
        victim = int(s[s["stage"] == "Eredivisie"]["game_id"].iloc[3])
        s.loc[s["game_id"] == victim, "stage"] = None
        self.assertIn(victim, man.stage_label_excluded(s))

    def test_an_unexpected_error_in_one_season_fails_only_that_season(self):
        good, _ = schedule()

        def read(season):
            if season == "2014-15":
                raise RuntimeError("cache unreadable")
            return good
        with tempfile.TemporaryDirectory() as tmp:
            lines, failures = man.process_seasons(["2013-14", "2014-15", "2015-16"], read, root=tmp)
            self.assertEqual(list(failures), ["2014-15"])
            self.assertIn("unexpected RuntimeError: cache unreadable", failures["2014-15"])
            self.assertTrue((Path(tmp) / "2015-16" / man.MANIFEST_NAME).exists())
            self.assertFalse((Path(tmp) / "2014-15" / man.MANIFEST_NAME).exists())


class TestStaleRows(unittest.TestCase):
    def test_rows_the_run_did_not_produce_are_stale(self):
        existing = [("A", "X"), ("B", "X"), ("C", "Y"), ("Kerkez", "AZ")]
        written = [("A", "X"), ("B", "X"), ("C", "Y")]
        self.assertEqual(agg.find_stale(existing, written), [("Kerkez", "AZ")])

    def test_same_name_other_team_is_a_different_row(self):
        self.assertEqual(agg.find_stale([("A", "X"), ("A", "Y")], [("A", "X")]), [("A", "Y")])

    def test_nothing_stale_when_everything_was_written(self):
        self.assertEqual(agg.find_stale([("A", "X")], [("A", "X"), ("B", "Y")]), [])

    def test_prune_flag_defaults_off(self):
        sql = agg.PRUNE_SQL
        self.assertIn("season_id = %s AND player_name = %s AND team = %s", sql)
        self.assertTrue(sql.startswith("DELETE FROM eredivisie_whoscored_player_season_stats"))

    def test_only_playoff_rows_are_deletable(self):
        stale = [("Kerkez", "AZ"), ("Old Dordrecht Player", "Dordrecht"), ("Steffen", "Vitesse")]
        po, other = agg.split_stale(stale, {("Kerkez", "AZ"), ("Steffen", "Vitesse"), ("Someone Else", "AZ")})
        self.assertEqual(po, [("Kerkez", "AZ"), ("Steffen", "Vitesse")])
        self.assertEqual(other, [("Old Dordrecht Player", "Dordrecht")])

    def test_nothing_is_deletable_without_playoff_keys(self):
        po, other = agg.split_stale([("A", "X"), ("B", "Y")], set())
        self.assertEqual(po, [])
        self.assertEqual(len(other), 2)

    def test_count_by_team_orders_largest_first(self):
        keys = [("a", "Emmen"), ("b", "Emmen"), ("c", "Dordrecht"), ("d", "Emmen"), ("e", "Almere")]
        self.assertEqual(agg.count_by_team(keys), [("Emmen", 3), ("Almere", 1), ("Dordrecht", 1)])

    def test_playoff_only_player_is_found_by_aggregating_the_excluded_files(self):
        """Mirrors main(): a player present in a play-off file only is a play-off key; one with a regular file is not."""
        ids = {"Regular Guy": 11, "Playoff Only": 22}
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for i, players in {"1": ["Regular Guy"], "2": ["Regular Guy", "Playoff Only"]}.items():
                (d / f"{i}.json").write_text(json.dumps(match_json([(p, "AZ", ids[p], 10) for p in players])))
            regular = {"1"}
            non_regular = {"1", "2"} - regular
            po = agg.aggregate_season(d, non_regular)
            keys = {(r[0], r[1]) for r in agg.build_rows(*po[:4], 2021)}
            self.assertIn(("Playoff Only", "AZ"), keys)
            reg = agg.aggregate_season(d, regular)
            written = [(r[0], r[1]) for r in agg.build_rows(*reg[:4], 2021)]
            stale = agg.find_stale(list(keys | set(written)), written)
            self.assertEqual(agg.split_stale(stale, keys)[0], [("Playoff Only", "AZ")])


class FakeCursor:
    def __init__(self, existing):
        self.existing, self.calls, self.rowcount, self._result = existing, [], 0, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.rowcount = 0
        if sql == agg.SEASON_KEYS_SQL:
            self._result = list(self.existing)

    def fetchall(self):
        return self._result


class FakeConn:
    def __init__(self, existing):
        self.cur = FakeCursor(existing)

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def close(self):
        pass


class TestMainEndToEnd(unittest.TestCase):
    """main() with a stand-in connection: which rows does it delete?"""

    def run_main(self, argv):
        existing = [("Regular Guy", "Vitesse"), ("Playoff Only", "Vitesse"), ("Old Dordrecht Player", "Dordrecht")]
        conn = FakeConn(existing)
        ids = {"Regular Guy": 11, "Playoff Only": 22}
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "2021-22"
            d.mkdir()
            for i, players in {"1": ["Regular Guy"], "2": ["Regular Guy", "Playoff Only"]}.items():
                (d / f"{i}.json").write_text(json.dumps(match_json([(p, "Vitesse", ids[p], 10) for p in players])))
            (d / agg.MANIFEST_NAME).write_text(json.dumps({"regular_match_ids": [1]}))
            saved = (agg.SEASONS, agg.DATA_ROOT, agg.get_connection, agg.execute_values)
            agg.SEASONS, agg.DATA_ROOT, agg.get_connection = ["2021-22"], Path(tmp), lambda: conn
            agg.execute_values = lambda cur, sql, rows: None
            try:
                import contextlib
                import io
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    agg.main(argv)
            finally:
                agg.SEASONS, agg.DATA_ROOT, agg.get_connection, agg.execute_values = saved
        deletes = [p for sql, p in conn.cur.calls if sql == agg.PRUNE_SQL]
        return deletes, buf.getvalue()

    def test_without_the_flag_nothing_is_deleted_but_it_is_reported(self):
        deletes, out = self.run_main([])
        self.assertEqual(deletes, [])
        self.assertIn("1 play-off-only row(s)", out)
        self.assertIn("Playoff Only (Vitesse)", out)
        self.assertIn("left in place", out)
        self.assertIn("Dordrecht x1", out)

    def test_prune_deletes_only_the_playoff_only_player(self):
        deletes, out = self.run_main(["--prune"])
        self.assertEqual(deletes, [(2021, "Playoff Only", "Vitesse")])       # not the Dordrecht row, not Regular Guy
        self.assertIn("DELETED", out)

    def test_a_missing_manifest_stops_before_any_database_work(self):
        conn = FakeConn([])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "2021-22").mkdir()
            saved = (agg.SEASONS, agg.DATA_ROOT, agg.get_connection)
            agg.SEASONS, agg.DATA_ROOT, agg.get_connection = ["2021-22"], Path(tmp), lambda: conn
            try:
                with self.assertRaises(SystemExit):
                    agg.main([])
            finally:
                agg.SEASONS, agg.DATA_ROOT, agg.get_connection = saved
        self.assertEqual(conn.cur.calls, [])


class TestTeamNameNormalization(unittest.TestCase):
    def test_the_four_clubs_stored_twice_are_mapped_to_the_fbref_names(self):
        self.assertEqual({k: agg.TEAM_NAME_NORMALIZATION[k] for k in ("FC Dordrecht", "FC Emmen", "FC Volendam", "Almere City FC")},
                         {"FC Dordrecht": "Dordrecht", "FC Emmen": "Emmen", "FC Volendam": "Volendam", "Almere City FC": "Almere City"})

    def test_a_raw_name_in_a_match_file_is_written_under_the_normalized_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "1.json").write_text(json.dumps(match_json([("A Player", "FC Emmen", 5, 10), ("B Player", "Almere City FC", 6, 10)])))
            out = agg.aggregate_season(d, {"1"})
            teams = {r[1] for r in agg.build_rows(*out[:4], 2018)}
            self.assertEqual(teams, {"Emmen", "Almere City"})

    def test_every_mapped_name_differs_from_its_target(self):
        for raw, norm in agg.TEAM_NAME_NORMALIZATION.items():
            self.assertNotEqual(raw, norm)


if __name__ == "__main__":
    unittest.main()
