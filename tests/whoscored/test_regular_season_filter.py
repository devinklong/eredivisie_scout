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


if __name__ == "__main__":
    unittest.main()
