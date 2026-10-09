"""
Tests for data_audit/validate_dataset.py. Each check is proven in both directions: the clean
synthetic dataset passes every check, and for EVERY check a planted violation makes that check
(and, unless listed in ALSO, only that check) fail. So a check that can never fire cannot hide here.

Needs a local Postgres (the same one the pipelines use). Everything is created as TEMP tables, which
are invisible to other connections and vanish on disconnect, so no real table can be touched. The
tests skip, loudly, if no database can be reached.

Run from the repo root:
    python tests/data_audit/test_validate_dataset.py
"""

import os
import sys
import unittest
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]
for candidate in ("data_audit", "pipelines/audits", "pipelines/data_audit", "audits"):
    if (ROOT / candidate / "validate_dataset.py").exists():
        sys.path.insert(0, str(ROOT / candidate))
        break
else:
    raise ImportError("validate_dataset.py not found under data_audit/, pipelines/audits/, pipelines/data_audit/ or audits/")
import validate_dataset as vd   # noqa: E402

MASTER_COLUMNS = [
    ("canonical_name", "text"),
    ("player_id", "integer"),
    ("team", "text"),
    ("season_id", "integer"),
    ("fbref_nation", "text"),
    ("fbref_position", "text"),
    ("fbref_age", "text"),
    ("fbref_born", "integer"),
    ("fbref_matches_played", "integer"),
    ("fbref_minutes", "integer"),
    ("fbref_minutes_per_match", "numeric(5,1)"),
    ("fbref_minutes_pct", "numeric(5,1)"),
    ("fbref_nineties", "numeric(5,1)"),
    ("fbref_starts", "integer"),
    ("fbref_minutes_per_start", "numeric(5,1)"),
    ("fbref_complete_matches", "integer"),
    ("fbref_substitute_appearances", "integer"),
    ("fbref_minutes_per_sub", "numeric(5,1)"),
    ("fbref_unused_sub", "integer"),
    ("fbref_points_per_match", "numeric(4,2)"),
    ("fbref_team_goals_while_on_pitch", "integer"),
    ("fbref_team_goals_against_while_on_pitch", "integer"),
    ("fbref_plus_minus", "integer"),
    ("fbref_plus_minus_per90", "numeric(5,2)"),
    ("fbref_on_off", "numeric(5,2)"),
    ("fbref_goals", "integer"),
    ("fbref_assists", "integer"),
    ("fbref_goals_plus_assists", "integer"),
    ("fbref_non_penalty_goals", "integer"),
    ("fbref_penalty_goals", "integer"),
    ("fbref_penalty_attempts", "integer"),
    ("fbref_goals_per90", "numeric(5,2)"),
    ("fbref_assists_per90", "numeric(5,2)"),
    ("fbref_goals_plus_assists_per90", "numeric(5,2)"),
    ("fbref_non_penalty_goals_per90", "numeric(5,2)"),
    ("fbref_non_penalty_goals_plus_assists_per90", "numeric(5,2)"),
    ("fbref_shots", "integer"),
    ("fbref_shots_on_target", "integer"),
    ("fbref_shots_on_target_pct", "numeric(5,1)"),
    ("fbref_shots_per90", "numeric(5,2)"),
    ("fbref_shots_on_target_per90", "numeric(5,2)"),
    ("fbref_goals_per_shot", "numeric(5,2)"),
    ("fbref_goals_per_shot_on_target", "numeric(5,2)"),
    ("fbref_yellow_cards", "integer"),
    ("fbref_red_cards", "integer"),
    ("fbref_second_yellow_cards", "integer"),
    ("fbref_fouls_committed", "integer"),
    ("fbref_fouls_drawn", "integer"),
    ("fbref_offsides", "integer"),
    ("fbref_crosses", "integer"),
    ("fbref_interceptions", "integer"),
    ("fbref_tackles_won", "integer"),
    ("fbref_penalty_kicks_won", "integer"),
    ("fbref_penalty_kicks_conceded", "integer"),
    ("fbref_own_goals", "integer"),
    ("gk_goals_against", "integer"),
    ("gk_goals_against_per90", "numeric(5,2)"),
    ("gk_shots_on_target_against", "integer"),
    ("gk_saves", "integer"),
    ("gk_save_pct", "numeric(5,1)"),
    ("gk_wins", "integer"),
    ("gk_draws", "integer"),
    ("gk_losses", "integer"),
    ("gk_clean_sheets", "integer"),
    ("gk_clean_sheet_pct", "numeric(5,1)"),
    ("gk_penalty_kicks_faced", "integer"),
    ("gk_penalty_kicks_allowed", "integer"),
    ("gk_penalty_kicks_saved", "integer"),
    ("gk_penalty_kicks_missed_by_opponent", "integer"),
    ("gk_penalty_kick_save_pct", "numeric(5,1)"),
    ("ws_whoscored_player_id", "integer"),
    ("ws_matches_with_data", "integer"),
    ("ws_passes", "integer"),
    ("ws_passes_completed", "integer"),
    ("ws_passes_pct", "numeric(5,1)"),
    ("ws_touches", "integer"),
    ("ws_touches_def_3rd", "integer"),
    ("ws_touches_mid_3rd", "integer"),
    ("ws_touches_att_3rd", "integer"),
    ("ws_touches_def_pen_area", "integer"),
    ("ws_touches_att_pen_area", "integer"),
    ("ws_take_ons", "integer"),
    ("ws_take_ons_won", "integer"),
    ("ws_take_ons_won_pct", "numeric(5,1)"),
    ("ws_dispossessed", "integer"),
    ("ws_tackles", "integer"),
    ("ws_tackles_won", "integer"),
    ("ws_tackles_def_3rd", "integer"),
    ("ws_tackles_mid_3rd", "integer"),
    ("ws_tackles_att_3rd", "integer"),
    ("ws_interceptions", "integer"),
    ("ws_interceptions_def_3rd", "integer"),
    ("ws_interceptions_mid_3rd", "integer"),
    ("ws_interceptions_att_3rd", "integer"),
    ("ws_clearances", "integer"),
    ("ws_dribbled_past", "integer"),
    ("ws_errors", "integer"),
    ("ws_final_third_entries", "integer"),
    ("ws_pen_area_entries", "integer"),
    ("ws_aerials", "integer"),
    ("ws_aerials_won", "integer"),
    ("ws_aerial_duel_win_pct", "numeric(5,1)"),
    ("ws_ground_duel_win_pct", "numeric"),
    ("tm_height_cm", "smallint"),
    ("tm_foot", "text"),
    ("fbref_yellow_cards_per90", "numeric"),
    ("fbref_red_cards_per90", "numeric"),
    ("fbref_second_yellow_cards_per90", "numeric"),
    ("fbref_fouls_committed_per90", "numeric"),
    ("fbref_fouls_drawn_per90", "numeric"),
    ("fbref_offsides_per90", "numeric"),
    ("fbref_crosses_per90", "numeric"),
    ("fbref_interceptions_per90", "numeric"),
    ("fbref_tackles_won_per90", "numeric"),
    ("fbref_penalty_kicks_won_per90", "numeric"),
    ("fbref_penalty_kicks_conceded_per90", "numeric"),
    ("fbref_own_goals_per90", "numeric"),
    ("gk_saves_per90", "numeric"),
    ("ws_passes_per90", "numeric"),
    ("ws_passes_completed_per90", "numeric"),
    ("ws_touches_per90", "numeric"),
    ("ws_touches_def_3rd_per90", "numeric"),
    ("ws_touches_mid_3rd_per90", "numeric"),
    ("ws_touches_att_3rd_per90", "numeric"),
    ("ws_touches_def_pen_area_per90", "numeric"),
    ("ws_touches_att_pen_area_per90", "numeric"),
    ("ws_take_ons_per90", "numeric"),
    ("ws_take_ons_won_per90", "numeric"),
    ("ws_dispossessed_per90", "numeric"),
    ("ws_tackles_per90", "numeric"),
    ("ws_tackles_won_per90", "numeric"),
    ("ws_tackles_def_3rd_per90", "numeric"),
    ("ws_tackles_mid_3rd_per90", "numeric"),
    ("ws_tackles_att_3rd_per90", "numeric"),
    ("ws_interceptions_per90", "numeric"),
    ("ws_interceptions_def_3rd_per90", "numeric"),
    ("ws_interceptions_mid_3rd_per90", "numeric"),
    ("ws_interceptions_att_3rd_per90", "numeric"),
    ("ws_clearances_per90", "numeric"),
    ("ws_dribbled_past_per90", "numeric"),
    ("ws_errors_per90", "numeric"),
    ("ws_final_third_entries_per90", "numeric"),
    ("ws_pen_area_entries_per90", "numeric"),
    ("ws_aerials_per90", "numeric"),
    ("ws_aerials_won_per90", "numeric"),
]

TYPES = {"integer": "integer", "text": "text", "smallint": "smallint", "numeric": "numeric"}


def connect():
    dsn = os.environ.get("TEST_DATABASE_URL")
    try:
        if dsn:
            return psycopg2.connect(dsn)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "modeling"))
        from build_style_percentiles import get_connection
        return get_connection()
    except Exception as e:
        return None


def make_tables(cur):
    cols = ", ".join(f"{c} {t}" for c, t in MASTER_COLUMNS)
    cur.execute(f"CREATE TEMP TABLE master_player_season_stats ({cols})")
    pct = ", ".join(f"pct_f{j} numeric" for j in range(3))
    cur.execute(f"CREATE TEMP TABLE player_season_style_percentiles (player_id int, season_id int, {pct})")
    cur.execute("CREATE TEMP TABLE player_season_archetypes (player_id int, season_id int, archetype_id int)")
    cur.execute("CREATE TEMP TABLE archetype_centroids (archetype_id int, feature text, feature_group text, centroid_pct numeric)")
    cur.execute("CREATE TEMP TABLE eredivisie_transfers (transfer_id serial, player_name text, season_id int, fee_amount numeric)")


SEASONS = [2019, 2022, 2023]
CLUBS = [f"Club {i:02d}" for i in range(18)]
PLAYERS_PER_CLUB = 14
MINUTES = 2400          # 14 x 2400 = 33,600 per club, inside 85%-110% of 33,660
MINUTES_2019 = 1835     # 2019-20 was cut at 26 rounds: 14 x 1835 = 25,690, inside 85%-110% of 25,740


def clean_row(pid, season, team, gk=False):
    """One internally consistent player-season (every identity holds, with room to break each one)."""
    MINUTES_ = MINUTES_2019 if season == 2019 else MINUTES
    r = {c: None for c, _ in MASTER_COLUMNS}
    r.update(canonical_name=f"Player {pid}", player_id=pid, team=team, season_id=season,
             fbref_born=season - 25, fbref_position="GK" if gk else "MF", fbref_matches_played=30, fbref_starts=28,
             fbref_minutes=MINUTES_, fbref_nineties=round(MINUTES_ / 90, 1), fbref_points_per_match=1.5,
             fbref_goals=6, fbref_penalty_goals=1, fbref_non_penalty_goals=5, fbref_penalty_attempts=2,
             fbref_assists=4, fbref_goals_plus_assists=10, fbref_non_penalty_goals_per90=round(5 / (round(MINUTES_ / 90, 1)), 2),
             fbref_shots=40, fbref_shots_on_target=20, fbref_yellow_cards=3, fbref_red_cards=1, fbref_second_yellow_cards=0,
             fbref_minutes_pct=80.0, fbref_shots_on_target_pct=50.0,
             ws_matches_with_data=30, ws_passes=1000, ws_passes_completed=800, ws_passes_pct=80.0, ws_passes_per90=37.5,
             ws_touches=1500, ws_touches_def_3rd=300, ws_touches_mid_3rd=700, ws_touches_att_3rd=500, ws_touches_per90=56.2,
             ws_touches_def_pen_area=40, ws_touches_att_pen_area=60,
             ws_take_ons=50, ws_take_ons_won=30, ws_take_ons_won_pct=60.0, ws_take_ons_per90=1.9,
             ws_tackles=80, ws_tackles_won=50, ws_tackles_def_3rd=30, ws_tackles_mid_3rd=30, ws_tackles_att_3rd=10, ws_tackles_per90=3.0,
             ws_interceptions=40, ws_interceptions_def_3rd=15, ws_interceptions_mid_3rd=15, ws_interceptions_att_3rd=5,
             ws_clearances=20, ws_clearances_per90=0.8, ws_aerials=60, ws_aerials_won=30, ws_aerial_duel_win_pct=50.0, ws_aerials_per90=2.2,
             tm_height_cm=182)
    if gk:
        r.update(gk_goals_against=30, gk_shots_on_target_against=120, gk_saves=90, gk_wins=15, gk_draws=7, gk_losses=8,
                 gk_clean_sheets=10, gk_penalty_kicks_faced=3, gk_penalty_kicks_saved=1, gk_save_pct=75.0)
    return r


def insert_rows(cur, rows):
    cols = [c for c, _ in MASTER_COLUMNS]
    cur.executemany(f"INSERT INTO master_player_season_stats ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    [[r[c] for c in cols] for r in rows])


def load_clean(cur):
    pid = 1
    rows = []
    for season in SEASONS:
        for t, team in enumerate(CLUBS):
            for k in range(PLAYERS_PER_CLUB):
                rows.append(clean_row(pid + k + t * 100 + SEASONS.index(season) * 10000, season, team, gk=(k == 0)))
    insert_rows(cur, rows)
    cur.execute("INSERT INTO player_season_style_percentiles SELECT player_id, season_id, 50, 20, 80 FROM master_player_season_stats WHERE player_id %% 7 = 0".replace("%%", "%"))
    cur.execute("INSERT INTO player_season_archetypes SELECT player_id, season_id, 1 FROM player_season_style_percentiles")
    cur.execute("INSERT INTO archetype_centroids SELECT a, 'f' || f, 'g', 50 FROM generate_series(1, 3) a, generate_series(1, 23) f")
    cur.execute("INSERT INTO eredivisie_transfers (player_name, season_id, fee_amount) VALUES ('a', 2022, 5.0), ('b', 2023, 0.0)")


M = "master_player_season_stats"
ONE = f"WHERE player_id = 1"      # the first clean player: a non-keeper? k==0 is the keeper; pid 1 is k=0 of club 0 -> a keeper
FIELD = f"WHERE player_id = 2"    # an outfielder (k = 1)
KEEPER = f"WHERE player_id = 1"

# check name -> SQL that plants exactly one violation of it in an otherwise clean dataset
PLANTED = {
    "duplicate_player_season_team": f"INSERT INTO {M} SELECT * FROM {M} {FIELD} AND season_id = 2019",
    "one_birth_year_per_player": f"UPDATE {M} SET player_id = 2 WHERE player_id = 10002",
    "born_plausible": f"UPDATE {M} SET fbref_born = 1900 WHERE player_id IN (2, 3, 4)",
    "clubs_per_season": f"UPDATE {M} SET team = 'FC Club 00' WHERE team = 'Club 00' AND season_id = 2022 AND player_id %% 2 = 0".replace("%%", "%"),
    "team_season_minutes": f"UPDATE {M} SET fbref_minutes = 1200, fbref_nineties = 13.3 WHERE team = 'Club 05' AND season_id = 2023",
    "nineties_match_minutes": f"UPDATE {M} SET fbref_nineties = 20.0 {FIELD}",
    "starts_le_matches": f"UPDATE {M} SET fbref_starts = 31 {FIELD}",
    "minutes_le_matches_cap": f"UPDATE {M} SET fbref_matches_played = 10, fbref_starts = 10 {FIELD}",
    "cards_le_matches": f"UPDATE {M} SET fbref_yellow_cards = 40 WHERE player_id IN (2, 3)",
    "second_yellow_le_red": f"UPDATE {M} SET fbref_second_yellow_cards = 3 {FIELD}",
    "non_negative_counts": f"UPDATE {M} SET fbref_offsides = -1 {FIELD}",
    "percent_columns_in_range": f"UPDATE {M} SET ws_passes_pct = 130 {FIELD}",
    "points_per_match_range": f"UPDATE {M} SET fbref_points_per_match = 4.2 {FIELD}",
    "goals_identity": f"UPDATE {M} SET fbref_goals = 9 {FIELD}",
    "goals_plus_assists_identity": f"UPDATE {M} SET fbref_goals_plus_assists = 12 {FIELD}",
    "penalty_goals_le_attempts": f"UPDATE {M} SET fbref_penalty_attempts = 0 {FIELD}",
    "shots_on_target_le_shots": f"UPDATE {M} SET fbref_shots_on_target = 60 {FIELD}",
    "goals_le_shots": f"UPDATE {M} SET fbref_shots = 3, fbref_shots_on_target = 2 {FIELD}",
    "np_goals_per90_matches_count": f"UPDATE {M} SET fbref_non_penalty_goals_per90 = 0.80 {FIELD}",
    "ws_passes_completed_le_passes": f"UPDATE {M} SET ws_passes_completed = 1200, ws_passes_pct = 120.0 {FIELD}",
    "ws_take_ons_won_le_take_ons": f"UPDATE {M} SET ws_take_ons_won = 70, ws_take_ons_won_pct = 140.0 {FIELD}",
    "ws_tackles_won_le_tackles": f"UPDATE {M} SET ws_tackles_won = 100 {FIELD}",
    "ws_aerials_won_le_aerials": f"UPDATE {M} SET ws_aerials_won = 90, ws_aerial_duel_win_pct = 150.0 {FIELD}",
    "ws_touch_zones_sum": f"UPDATE {M} SET ws_touches_att_3rd = 900 {FIELD}",
    "ws_penalty_area_touches_le_touches": f"UPDATE {M} SET ws_touches_def_pen_area = 1000, ws_touches_att_pen_area = 1000 {FIELD}",
    "ws_tackle_zones_le_tackles": f"UPDATE {M} SET ws_tackles_att_3rd = 70 {FIELD}",
    "ws_interception_zones_le_interceptions": f"UPDATE {M} SET ws_interceptions_att_3rd = 30 {FIELD}",
    "ws_passes_pct_matches_counts": f"UPDATE {M} SET ws_passes_pct = 65.0 {FIELD}",
    "ws_take_ons_pct_matches_counts": f"UPDATE {M} SET ws_take_ons_won_pct = 35.0 {FIELD}",
    "ws_aerial_pct_matches_counts": f"UPDATE {M} SET ws_aerial_duel_win_pct = 20.0 {FIELD}",
    "ws_per90_sign_consistent": f"UPDATE {M} SET ws_tackles_per90 = 0 {FIELD}",
    "ws_matches_le_fbref_matches": f"UPDATE {M} SET ws_matches_with_data = 36 {FIELD}",
    "gk_saves_le_shots_faced": f"UPDATE {M} SET gk_saves = 150 {KEEPER}",
    "gk_clean_sheets_le_matches": f"UPDATE {M} SET gk_clean_sheets = 40 {KEEPER}",
    "gk_results_le_matches": f"UPDATE {M} SET gk_wins = 30 {KEEPER}",
    "gk_penalties_saved_le_faced": f"UPDATE {M} SET gk_penalty_kicks_saved = 5 {KEEPER}",
    "outfielders_with_keeper_stats": f"UPDATE {M} SET gk_goals_against = 5 {FIELD}",
    "height_range": f"UPDATE {M} SET tm_height_cm = 120 WHERE player_id IN (2, 3, 4)",
    "percentile_columns_in_range": "UPDATE player_season_style_percentiles SET pct_f1 = 140 WHERE player_id = (SELECT MIN(player_id) FROM player_season_style_percentiles)",
    "percentiles_unique_key": "INSERT INTO player_season_style_percentiles SELECT * FROM player_season_style_percentiles LIMIT 1",
    "percentiles_have_stats": "INSERT INTO player_season_style_percentiles VALUES (999999, 2022, 50, 50, 50)",
    "archetypes_have_percentiles": "INSERT INTO player_season_archetypes VALUES (999999, 2022, 1)",
    "centroids_complete": "DELETE FROM archetype_centroids WHERE archetype_id = 2 AND feature = 'f7'",
    "transfer_fee_range": "UPDATE eredivisie_transfers SET fee_amount = 400 WHERE player_name = 'a'",
    "transfer_season_range": "UPDATE eredivisie_transfers SET season_id = 1850 WHERE player_name = 'a'",
}
# A planted violation that legitimately breaks a neighbouring check too (named, so nothing is accidental).
ALSO = {
    "team_season_minutes": {"np_goals_per90_matches_count"},
    "nineties_match_minutes": {"np_goals_per90_matches_count"},
    "goals_identity": {"goals_plus_assists_identity"},
    "minutes_le_matches_cap": {"ws_matches_le_fbref_matches"},
    "duplicate_player_season_team": {"team_season_minutes"},
    "clubs_per_season": {"team_season_minutes"},
    "ws_passes_completed_le_passes": {"ws_passes_pct_matches_counts", "percent_columns_in_range"},
    "ws_take_ons_won_le_take_ons": {"ws_take_ons_pct_matches_counts", "percent_columns_in_range"},
    "ws_aerials_won_le_aerials": {"ws_aerial_pct_matches_counts", "percent_columns_in_range"},
    "percent_columns_in_range": {"ws_passes_pct_matches_counts"},
}


class DatabaseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = connect()
        if cls.conn is None:
            raise unittest.SkipTest("no Postgres reachable (set TEST_DATABASE_URL or configure get_connection)")

    @classmethod
    def tearDownClass(cls):
        if cls.conn is not None:
            cls.conn.close()

    def setUp(self):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS pg_temp.master_player_season_stats, pg_temp.player_season_style_percentiles, "
                        "pg_temp.player_season_archetypes, pg_temp.archetype_centroids, pg_temp.eredivisie_transfers")
            make_tables(cur)
            load_clean(cur)

    def results(self, only=None):
        return {r["name"]: r for r in vd.run_all(self.conn, only)}


class TestCleanData(DatabaseCase):
    def test_clean_dataset_passes_every_check(self):
        res = self.results()
        bad = {n: (r["status"], r["violations"], r["detail"]) for n, r in res.items() if r["status"] != "PASS"}
        self.assertEqual(bad, {})
        self.assertEqual(vd.exit_code(list(res.values())), 0)

    def test_every_check_has_a_planted_case(self):
        self.assertEqual(set(PLANTED), set(vd.CHECK_NAMES))


class TestEachCheckFires(DatabaseCase):
    def test_every_check_catches_its_planted_violation(self):
        failures = []
        for name, sql in PLANTED.items():
            self.setUp()
            with self.conn.cursor() as cur:
                try:
                    cur.execute(sql)
                except Exception as e:
                    failures.append((name, f"planting SQL failed: {e}"))
                    self.conn.rollback()
                    continue
            res = self.results()
            if res[name]["status"] not in ("FAIL", "WARN"):
                failures.append((name, f"did not fire: {res[name]['status']} ({res[name]['violations']})"))
            extra = {n for n, r in res.items() if r["status"] in ("FAIL", "WARN") and n != name} - ALSO.get(name, set())
            if extra:
                failures.append((name, f"also fired: {sorted(extra)}"))
        self.assertEqual(failures, [])


class TestSeverityAndExit(DatabaseCase):
    def test_error_check_fails_the_run(self):
        with self.conn.cursor() as cur:
            cur.execute(PLANTED["goals_identity"])
        res = list(self.results().values())
        self.assertEqual(vd.exit_code(res), 1)

    def test_warn_check_does_not_fail_the_run(self):
        with self.conn.cursor() as cur:
            cur.execute(PLANTED["second_yellow_le_red"])
        res = self.results()
        self.assertEqual(res["second_yellow_le_red"]["status"], "WARN")
        self.assertEqual(vd.exit_code(list(res.values())), 0)


class TestAllowedKnownIssues(DatabaseCase):
    def test_known_height_rows_are_tolerated_but_a_third_fails(self):
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET tm_height_cm = 875 WHERE player_id IN (2, 3)")
        self.assertEqual(self.results()["height_range"]["status"], "KNOWN")
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET tm_height_cm = 875 WHERE player_id = 4")
        self.assertEqual(self.results()["height_range"]["status"], "FAIL")


class TestNeverSilent(DatabaseCase):
    def test_missing_table_is_skipped_not_passed(self):
        missing = vd.Check("missing", "error", "table absent", "table_that_does_not_exist_xyz",
                           "SELECT 1 FROM table_that_does_not_exist_xyz")
        r = vd.run_check(self.conn, missing)
        self.assertEqual(r["status"], "SKIPPED")
        self.assertNotIn(r["status"], ("PASS", "KNOWN"))
        self.assertIn("NOT passes", vd.format_report([r]))

    def test_broken_check_is_an_error_not_a_pass(self):
        broken = vd.Check("broken", "error", "bad sql", M, f"SELECT nonexistent_column FROM {M}")
        r = vd.run_check(self.conn, broken)
        self.assertEqual(r["status"], "ERROR")
        self.assertEqual(vd.exit_code([r]), 1)

    def test_null_values_never_trigger_a_violation(self):
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET ws_passes = NULL, ws_passes_completed = NULL, ws_touches = NULL, "
                        "fbref_goals = NULL, fbref_shots = NULL, fbref_nineties = NULL")
        res = self.results()
        fired = [n for n, r in res.items() if r["status"] in ("FAIL", "WARN") and n not in ("team_season_minutes",)]
        self.assertEqual(fired, [])


class TestSeasonLength(DatabaseCase):
    def test_short_season_passes_with_26_match_totals(self):
        self.assertEqual(self.results(["team_season_minutes"])["team_season_minutes"]["status"], "PASS")

    def test_full_season_totals_in_the_short_season_are_flagged_as_double_counting(self):
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET fbref_minutes = 2400, fbref_nineties = 26.7 WHERE team = 'Club 03' AND season_id = 2019")
        r = self.results(["team_season_minutes"])["team_season_minutes"]
        self.assertEqual(r["violations"], 1)

    def test_normal_seasons_still_expect_34_matches(self):
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET fbref_minutes = 1835, fbref_nineties = 20.4 WHERE team = 'Club 03' AND season_id = 2022")
        r = self.results(["team_season_minutes"])["team_season_minutes"]
        self.assertEqual(r["violations"], 1)


class TestBoundaries(DatabaseCase):
    def test_birth_year_too_recent_and_exact_limit(self):
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET fbref_born = season_id - 14 WHERE player_id = 2")   # exactly 14: allowed
            cur.execute(f"UPDATE {M} SET fbref_born = 1960 WHERE player_id = 3")             # exactly 1960: allowed
        self.assertEqual(self.results(["born_plausible"])["born_plausible"]["status"], "PASS")
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET fbref_born = season_id - 13 WHERE player_id = 4")
        self.assertEqual(self.results(["born_plausible"])["born_plausible"]["violations"], 1)

    def test_height_limits_are_inclusive(self):
        with self.conn.cursor() as cur:
            cur.execute(f"UPDATE {M} SET tm_height_cm = 150 WHERE player_id = 2")
            cur.execute(f"UPDATE {M} SET tm_height_cm = 215 WHERE player_id = 3")
        self.assertEqual(self.results(["height_range"])["height_range"]["status"], "PASS")


class TestReport(DatabaseCase):
    def test_report_names_failures_and_shows_sample_rows(self):
        with self.conn.cursor() as cur:
            cur.execute(PLANTED["goals_identity"])
        text = vd.format_report(vd.run_all(self.conn))
        self.assertIn("FAIL", text)
        self.assertIn("goals_identity", text)
        self.assertIn("Player 2", text)

    def test_only_filter_runs_only_those_checks(self):
        res = vd.run_all(self.conn, only=["goals_identity"])
        self.assertEqual([r["name"] for r in res], ["goals_identity"])


if __name__ == "__main__":
    unittest.main()
