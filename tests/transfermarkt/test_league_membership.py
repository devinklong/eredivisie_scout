"""
Offline tests for inspect_league_season.py. Synthetic pages only. Whether the
real Transfermarkt pages look like this is exactly what the inspector exists to
show, so these test the logic, not the layout.

Run from the repo root:
    python tests/transfermarkt/test_league_membership.py
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "transfermarkt"))

import inspect_league_season as ils   # noqa: E402
import load_league_season_clubs as lls  # noqa: E402
import scrape_league_seasons as sls  # noqa: E402
from bs4 import BeautifulSoup         # noqa: E402


class FakeCursor:
    def __init__(self, log):
        self.log, self.rowcount = log, 20
    def execute(self, sql, params=None):
        self.log.append(("execute", " ".join(sql.split()), params))
    def __enter__(self): return self
    def __exit__(self, *a): return False


class FakeConn:
    def __init__(self):
        self.log, self.closed = [], False
    def cursor(self): return FakeCursor(self.log)
    def commit(self): self.log.append(("commit",))
    def rollback(self): self.log.append(("rollback",))
    def close(self): self.closed = True


def club_row(club_id, name, season):
    # real-looking rows carry TWO anchors per club: a crest with no text, then the name
    return (f'<tr><td><a href="/c/startseite/verein/{club_id}/saison_id/{season}"><img src="x.png"></a></td>'
            f'<td class="hauptlink"><a href="/c/startseite/verein/{club_id}/saison_id/{season}">{name}</a></td>'
            f'<td>25</td></tr>')


def league_page(clubs, season, selected_season=None, sidebar=((9001, "Sidebar FC"), (9002, "Widget United")),
                title=None):
    """A participants table of `clubs`, a sidebar table of OTHER clubs, and a season dropdown."""
    selected_season = season if selected_season is None else selected_season
    rows = "".join(club_row(cid, n, season) for cid, n in clubs)
    side = "".join(club_row(cid, n, season) for cid, n in sidebar)
    return (f"<html><head><title>{title or f'Serie A {season}/{str(season + 1)[-2:]} | Transfermarkt'}</title></head><body>"
            f"<h1>Serie A</h1>"
            f"<select name='saison_id'><option value='2018'>18/19</option>"
            f"<option value='{selected_season}' selected='selected'>{selected_season}/{str(selected_season + 1)[-2:]}</option></select>"
            f"<h2>Recent transfers</h2><table>{side}</table>"
            f"<h2>Clubs</h2><table><tr><th>Club</th><th></th><th>Squad</th></tr>{rows}</table>"
            f"</body></html>")


SERIE_A_2019 = [(506, "Juventus"), (46, "Inter"), (5, "AC Milan"), (6195, "Napoli"), (12, "Roma"),
                (398, "Lazio"), (800, "Atalanta"), (416, "Torino"), (1025, "Bologna"), (1390, "Cagliari")] + \
               [(7000 + i, f"Other Club {i}") for i in range(10)]
KNOWN = {506: "Juventus", 46: "Inter", 5: "AC Milan", 6195: "Napoli", 12: "Roma", 398: "Lazio",
         800: "Atalanta", 416: "Torino", 1025: "Bologna", 1390: "Cagliari", 631: "Chelsea", 27: "Bayern Munich"}


class ExpectedCountTests(unittest.TestCase):
    def test_league_sizes_including_the_ligue_1_change(self):
        self.assertEqual(ils.expected_club_count("GB1", 2019), 20)
        self.assertEqual(ils.expected_club_count("ES1", 2012), 20)
        self.assertEqual(ils.expected_club_count("IT1", 2025), 20)
        self.assertEqual(ils.expected_club_count("L1", 2015), 18)
        self.assertEqual(ils.expected_club_count("FR1", 2022), 20)    # last 20-club season
        self.assertEqual(ils.expected_club_count("FR1", 2023), 18)    # first 18-club season

    def test_build_url(self):
        self.assertEqual(ils.build_url("IT1", 2019),
                         "https://www.transfermarkt.com/serie-a/startseite/wettbewerb/IT1?saison_id=2019")
        self.assertEqual(ils.build_url("GB1", 2012, slug="x"),
                         "https://www.transfermarkt.com/x/startseite/wettbewerb/GB1?saison_id=2012")


class ClubLinkTests(unittest.TestCase):
    def test_two_anchors_per_club_collapse_to_one_with_the_name(self):
        soup = BeautifulSoup(f"<table>{club_row(506, 'Juventus', 2019)}{club_row(46, 'Inter', 2019)}</table>", "html.parser")
        self.assertEqual(ils.club_links(soup), [(506, "Juventus"), (46, "Inter")])

    def test_non_club_links_are_ignored(self):
        soup = BeautifulSoup('<a href="/x/spieler/123">Player</a><a href="/x/verein/7/saison_id/2019">Club</a>', "html.parser")
        self.assertEqual(ils.club_links(soup), [(7, "Club")])

    def test_a_later_non_empty_text_replaces_an_empty_one(self):
        soup = BeautifulSoup('<a href="/x/verein/7"></a><a href="/x/verein/7">Real Name</a>', "html.parser")
        self.assertEqual(ils.club_links(soup), [(7, "Real Name")])


class BestTableTests(unittest.TestCase):
    def setUp(self):
        self.soup = BeautifulSoup(league_page(SERIE_A_2019, 2019), "html.parser")
        self.tables = ils.describe_tables(self.soup)

    def test_picks_the_participants_table_not_the_sidebar(self):
        best = ils.best_table(self.tables)
        self.assertEqual(len(best["clubs"]), 20)
        self.assertEqual(best["heading"], "Clubs")

    def test_picks_the_largest_when_a_sizeable_widget_also_qualifies(self):
        """A sidebar can easily hold 5+ clubs too (a top-transfers widget). The 20-club table must still win."""
        widget = [(9100 + i, f"Widget {i}") for i in range(8)]
        soup = BeautifulSoup(league_page(SERIE_A_2019, 2019, sidebar=widget), "html.parser")
        tables = ils.describe_tables(soup)
        self.assertEqual(sorted(len(t["clubs"]) for t in tables if t["clubs"]), [8, 20])    # both qualify
        best = ils.best_table(tables)
        self.assertEqual((len(best["clubs"]), best["heading"]), (20, "Clubs"))

    def test_a_page_with_only_a_small_widget_has_no_participants_table(self):
        soup = BeautifulSoup(f"<h2>Widget</h2><table>{club_row(1, 'A', 2019)}{club_row(2, 'B', 2019)}</table>", "html.parser")
        self.assertIsNone(ils.best_table(ils.describe_tables(soup)))


class SeasonEvidenceTests(unittest.TestCase):
    def test_reads_title_heading_and_the_selected_option(self):
        ev = ils.season_evidence(BeautifulSoup(league_page(SERIE_A_2019, 2019), "html.parser"))
        self.assertEqual(ev["title"], "Serie A 2019/20 | Transfermarkt")
        self.assertEqual(ev["h1"], "Serie A")
        self.assertEqual(ev["selected"], [("saison_id", "2019", "2019/20")])      # not the unselected 18/19

    def test_no_dropdown_is_reported_as_none(self):
        self.assertEqual(ils.season_evidence(BeautifulSoup("<html><body>x</body></html>", "html.parser"))["selected"], [])


class ReportTests(unittest.TestCase):
    def test_right_count_ok_and_known_buyers_are_tagged(self):
        text = ils.report(league_page(SERIE_A_2019, 2019), "IT1", 2019, KNOWN, "http://x")
        self.assertIn("20 clubs, expected 20 for IT1 2019: OK", text)
        self.assertIn("<- buyer club: Juventus", text)
        self.assertIn("known buyer clubs in this table: 10 of 12", text)         # Chelsea and Bayern are not in Serie A
        self.assertNotIn("Chelsea", text.split("--- known buyer clubs")[1].split("\n")[1])

    def test_wrong_count_is_flagged(self):
        text = ils.report(league_page(SERIE_A_2019[:19], 2019), "IT1", 2019, KNOWN, "http://x")
        self.assertIn("19 clubs, expected 20 for IT1 2019: MISMATCH (expected 20)", text)

    def test_sidebar_clubs_are_reported_as_outside_the_table(self):
        text = ils.report(league_page(SERIE_A_2019, 2019), "IT1", 2019, KNOWN, "http://x")
        self.assertIn("NOT in that table: 2", text)
        self.assertIn("9001  Sidebar FC", text)

    def test_an_ignored_season_parameter_is_visible_in_the_evidence(self):
        # asked for 2012 but the page served 2025: the selected option and title say so
        page = league_page(SERIE_A_2019, 2025, selected_season=2025)
        text = ils.report(page, "IT1", 2012, KNOWN, "http://x")
        self.assertIn("'2025', '2025/26'", text)
        self.assertIn("should name the 2012/13 season", text)

    def test_ligue_1_2023_expects_18(self):
        clubs = [(8000 + i, f"Club {i}") for i in range(18)]
        self.assertIn("18 clubs, expected 18 for FR1 2023: OK", ils.report(league_page(clubs, 2023), "FR1", 2023, {}, "x"))

    def test_missing_known_file_skips_the_overlap_check(self):
        self.assertIn("overlap check skipped", ils.report(league_page(SERIE_A_2019, 2019), "IT1", 2019, {}, "x"))

    def test_a_challenge_page_says_no_participants_table(self):
        text = ils.report("<html><head><title>Just a moment...</title></head><body></body></html>", "IT1", 2019, KNOWN, "x")
        self.assertIn("NO participants table found", text)


class MainTests(unittest.TestCase):
    def _run(self, argv, html=None, error=None):
        buf = io.StringIO()
        patches = [mock.patch.object(sys, "argv", ["inspect_league_season.py", *argv])]
        patches.append(mock.patch.object(ils, "fetch_html", side_effect=error) if error
                       else mock.patch.object(ils, "fetch_html", return_value=html))
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(buf):
            fh = stack.enter_context(patches[1])
            stack.enter_context(patches[0])
            try:
                ils.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, buf.getvalue(), fh

    def test_full_path_builds_the_url_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            known = Path(d) / "k.csv"
            known.write_text("counterparty_club_id,counterparty_club_name\n506,Juventus\n")
            code, out, fh = self._run(["--league", "IT1", "--season", "2019", "--known", str(known)],
                                      html=league_page(SERIE_A_2019, 2019))
        self.assertEqual(code, 0)
        fh.assert_called_once_with("https://www.transfermarkt.com/serie-a/startseite/wettbewerb/IT1?saison_id=2019")
        self.assertIn("OK", out)
        self.assertIn("known buyer clubs in this table: 1 of 1", out)

    def test_url_override_is_used_verbatim(self):
        code, out, fh = self._run(["--url", "https://example.test/page"], html=league_page(SERIE_A_2019, 2019))
        fh.assert_called_once_with("https://example.test/page")

    def test_a_blocked_fetch_exits_with_a_readable_message(self):
        code, out, _ = self._run([], error=ils.ScrapeError("HTTP 403 (blocked)"))
        self.assertIn("FAILED: HTTP 403", str(code))


# ---- the real page shape (as seen by inspect_league_season.py on 2026-10-05) --------------

def real_page(clubs, season, league_name="Serie A", title_season=None, selected_season=None,
              heading_season=None, items_class="items", corroborate=True, corroborating_clubs=None,
              foreign=((10004, ""), (618, ""), (11273, ""))):
    def lab(y):
        return f"{y % 100:02d}/{(y + 1) % 100:02d}"
    title_season = season if title_season is None else title_season
    selected_season = season if selected_season is None else selected_season
    heading_season = season if heading_season is None else heading_season
    members = "".join(club_row(cid, n, season) for cid, n in clubs)
    corr = clubs if corroborating_clubs is None else corroborating_clubs
    simple = lambda cs: "".join(f'<tr><td><a href="/c/verein/{cid}">{n}</a></td></tr>' for cid, n in cs)
    html = (f"<html><head><title>{league_name} {lab(title_season)} | Transfermarkt</title></head><body>"
            f"<h1>{league_name}</h1>"
            f"<select name='saison_id'><option value='{selected_season}' selected='selected'>{lab(selected_season)}</option></select>"
            f"<h2>Clubs - {league_name} {lab(heading_season)}</h2>"
            f"<table class='{items_class}'><tr><th>Club</th><th></th><th>Squad</th></tr>{members}</table>")
    if corroborate:
        html += f"<table class='livescore'>{simple(corr)}</table><table class='items'>{simple(list(reversed(corr)))}</table>"
    html += f"<h2>Top goalscorers</h2><table class='items'>{simple(clubs[:5])}</table>"
    if foreign:
        html += f"<h2>Subsequent competitions</h2><table>{simple(foreign)}</table>"
    return html + "</body></html>"


class SeasonLabelTests(unittest.TestCase):
    def test_labels_including_the_century_boundary(self):
        self.assertEqual(sls.season_label(2019), "19/20")
        self.assertEqual(sls.season_label(2009), "09/10")
        self.assertEqual(sls.season_label(1999), "99/00")


class ParseLeagueSeasonTests(unittest.TestCase):
    def parse(self, html, code="IT1", season=2019):
        return sls.parse_league_season(html, code, season)

    def test_good_page_returns_the_members_in_order_without_the_foreign_clubs(self):
        clubs = self.parse(real_page(SERIE_A_2019, 2019))
        self.assertEqual(len(clubs), 20)
        self.assertEqual(clubs[0], {"club_id": 506, "club_name": "Juventus"})
        self.assertEqual([c["club_id"] for c in clubs], [cid for cid, _ in SERIE_A_2019])
        self.assertTrue({10004, 618, 11273}.isdisjoint(c["club_id"] for c in clubs))    # Ligue 1 2023's real contaminants

    def test_title_naming_another_season_is_rejected(self):
        with self.assertRaises(sls.LeagueSeasonError) as cm:
            self.parse(real_page(SERIE_A_2019, 2019, title_season=2025))
        self.assertIn("does not name season 19/20", str(cm.exception))

    def test_season_selector_showing_another_season_is_rejected(self):
        with self.assertRaises(sls.LeagueSeasonError) as cm:
            self.parse(real_page(SERIE_A_2019, 2019, selected_season=2025))
        self.assertIn("season selector shows '2025'", str(cm.exception))

    def test_participants_heading_naming_another_season_is_rejected(self):
        with self.assertRaises(sls.LeagueSeasonError) as cm:
            self.parse(real_page(SERIE_A_2019, 2019, heading_season=2018))
        self.assertIn("different season", str(cm.exception))

    def test_no_items_table_under_a_clubs_heading_is_rejected(self):
        with self.assertRaises(sls.LeagueSeasonError) as cm:
            # no corroborating tables either: on the real page the standings table is ALSO an 'items'
            # table under the same 'Clubs - ...' heading, so it would (correctly) stand in
            self.parse(real_page(SERIE_A_2019, 2019, items_class="livescore", corroborate=False))
        self.assertIn("no class='items' table", str(cm.exception))

    def test_the_standings_table_stands_in_when_the_main_table_has_another_class(self):
        clubs = self.parse(real_page(SERIE_A_2019, 2019, items_class="livescore"))
        self.assertEqual(len(clubs), 20)

    def test_wrong_club_count_is_rejected(self):
        with self.assertRaises(sls.LeagueSeasonError) as cm:
            self.parse(real_page(SERIE_A_2019[:19], 2019, corroborating_clubs=SERIE_A_2019[:19]))
        self.assertIn("19 clubs found, expected 20", str(cm.exception))

    def test_ligue_1_expects_18_from_2023_and_20_before(self):
        eighteen = [(8000 + i, f"C{i}") for i in range(18)]
        self.assertEqual(len(self.parse(real_page(eighteen, 2023, "Ligue 1"), "FR1", 2023)), 18)
        with self.assertRaises(sls.LeagueSeasonError):
            self.parse(real_page(SERIE_A_2019, 2023, "Ligue 1"), "FR1", 2023)             # 20 clubs in 2023
        self.assertEqual(len(self.parse(real_page(SERIE_A_2019, 2022, "Ligue 1"), "FR1", 2022)), 20)

    def test_a_member_list_no_other_table_corroborates_is_rejected(self):
        with self.assertRaises(sls.LeagueSeasonError) as cm:
            self.parse(real_page(SERIE_A_2019, 2019, corroborate=False))
        self.assertIn("uncorroborated", str(cm.exception))

    def test_corroboration_needs_the_exact_same_set_not_a_near_match(self):
        near = SERIE_A_2019[:19] + [(9999, "Impostor")]                                 # 19 of 20 the same
        with self.assertRaises(sls.LeagueSeasonError):
            self.parse(real_page(SERIE_A_2019, 2019, corroborating_clubs=near))


class LeagueScrapeLoopTests(unittest.TestCase):
    def _run(self, out_dir, argv, scrape_one):
        with mock.patch.object(sys, "argv", ["scrape_league_seasons.py", *argv]), \
             mock.patch.object(sls, "OUT_DIR", out_dir), \
             mock.patch.object(sls, "scrape_one", side_effect=scrape_one) as so, \
             mock.patch.object(sls.time, "sleep"):
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
                sls.main()
        return cm.exception.code, so

    @staticmethod
    def _ok(code, season):
        n = ils.expected_club_count(code, season)
        return ("u", [{"club_id": 100 * ord(code[0]) + i, "club_name": f"C{i}"} for i in range(n)])

    def test_default_range_is_every_big5_league_for_2010_to_2025(self):
        with tempfile.TemporaryDirectory() as d:
            code, so = self._run(Path(d) / "L", [], self._ok)
        self.assertEqual((code, so.call_count), (0, 80))

    def test_failure_writes_nothing_for_that_page_and_exits_nonzero_but_the_rest_continue(self):
        def flaky(code, season):
            if (code, season) == ("IT1", 2019):
                raise sls.LeagueSeasonError("wrong season")
            return self._ok(code, season)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "L"
            code, _ = self._run(out, ["--league", "IT1", "--from-season", "2018", "--to-season", "2020"], flaky)
            names = sorted(p.name for p in out.glob("*.json"))
        self.assertEqual(code, 1)
        self.assertEqual(names, ["IT1_2018.json", "IT1_2020.json"])

    def test_existing_files_are_skipped_unless_force(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "L"; out.mkdir()
            (out / "IT1_2019.json").write_text("[]")
            _, so = self._run(out, ["--league", "IT1", "--from-season", "2019", "--to-season", "2019"], self._ok)
            self.assertEqual(so.call_count, 0)
            _, so = self._run(out, ["--league", "IT1", "--from-season", "2019", "--to-season", "2019", "--force"], self._ok)
            self.assertEqual(so.call_count, 1)

    def test_saved_json_carries_league_season_and_clubs(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "L"
            self._run(out, ["--league", "GB1", "--from-season", "2012", "--to-season", "2012"], self._ok)
            saved = json.loads((out / "GB1_2012.json").read_text())
        self.assertEqual(len(saved), 20)
        self.assertEqual({(r["league_code"], r["season_id"]) for r in saved}, {("GB1", 2012)})
        self.assertEqual(set(saved[0]), {"league_code", "season_id", "club_id", "club_name"})


def league_records(code, season, n=None, offset=0):
    n = ils.expected_club_count(code, season) if n is None else n
    return [{"league_code": code, "season_id": season, "club_id": offset + i, "club_name": f"C{i}"} for i in range(n)]


class LeagueLoaderTests(unittest.TestCase):
    def test_filename_parsing(self):
        self.assertEqual(lls.parse_filename(Path("GB1_2012.json")), ("GB1", 2012))
        self.assertEqual(lls.parse_filename(Path("L1_2019.json")), ("L1", 2019))
        self.assertIsNone(lls.parse_filename(Path("XX9_2019.json")))
        self.assertIsNone(lls.parse_filename(Path("notes.json")))

    def test_good_records_become_tuples_in_insert_order(self):
        rows = lls.build_rows("IT1", 2019, league_records("IT1", 2019))
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0], ("IT1", 2019, 0, "C0"))

    def test_wrong_count_duplicate_ids_and_mislabeled_records_are_rejected(self):
        with self.assertRaises(lls.BadLeagueFile):
            lls.build_rows("IT1", 2019, league_records("IT1", 2019, n=19))
        dup = league_records("IT1", 2019); dup[1]["club_id"] = dup[0]["club_id"]
        with self.assertRaises(lls.BadLeagueFile):
            lls.build_rows("IT1", 2019, dup)
        with self.assertRaises(lls.BadLeagueFile):
            lls.build_rows("IT1", 2019, league_records("GB1", 2019))
        with self.assertRaises(lls.BadLeagueFile):
            lls.build_rows("IT1", 2019, league_records("IT1", 2018))

    def _main(self, files):
        conn = FakeConn()
        with tempfile.TemporaryDirectory() as d:
            for name, records in files.items():
                (Path(d) / name).write_text(json.dumps(records))
            with mock.patch.object(lls, "LEAGUE_DIR", Path(d)), \
                 mock.patch.object(lls, "get_connection", return_value=conn), \
                 mock.patch.object(lls, "execute_values") as ev, \
                 contextlib.redirect_stdout(io.StringIO()):
                try:
                    lls.main()
                    err = None
                except Exception as e:      # noqa: BLE001
                    err = e
        return conn, ev, err

    def test_delete_then_insert_then_commit_per_league_season(self):
        conn, ev, err = self._main({"IT1_2019.json": league_records("IT1", 2019)})
        self.assertIsNone(err)
        self.assertEqual([e[0] for e in conn.log], ["execute", "commit"])
        self.assertIn("DELETE FROM league_season_clubs", conn.log[0][1])
        self.assertEqual(conn.log[0][2], ("IT1", 2019))
        self.assertEqual(len(ev.call_args.args[2]), 20)
        self.assertTrue(conn.closed)

    def test_a_bad_file_is_rejected_before_the_database_is_touched(self):
        conn, ev, err = self._main({"IT1_2019.json": league_records("IT1", 2019, n=19)})
        self.assertIsInstance(err, lls.BadLeagueFile)
        self.assertEqual(conn.log, [])
        ev.assert_not_called()

    def test_insert_failure_rolls_back_and_reraises(self):
        conn = FakeConn()
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "IT1_2019.json").write_text(json.dumps(league_records("IT1", 2019)))
            with mock.patch.object(lls, "LEAGUE_DIR", Path(d)), \
                 mock.patch.object(lls, "get_connection", return_value=conn), \
                 mock.patch.object(lls, "execute_values", side_effect=RuntimeError("db down")), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError):
                    lls.main()
        self.assertIn("rollback", [e[0] for e in conn.log])
        self.assertNotIn("commit", [e[0] for e in conn.log])
        self.assertTrue(conn.closed)


if __name__ == "__main__":
    unittest.main(verbosity=1)
