"""
Offline tests for scrape_buyer_clubs.py and load_buyer_club_transfers.py.

Covers everything that can be checked WITHOUT the live site or a database:
parsing against synthetic Transfermarkt-shaped pages, retry/block/zero-row
handling with a faked network, resume/failure behavior of the scrape loop,
row building, and the loader's transaction behavior against a fake
connection.

What this CANNOT show, and only a real run can: that Transfermarkt serves
these pages to plain requests, that a '-' placeholder slug resolves for
club pages, and that the extractor's table-parity direction rule holds on
every buyer page (use buyer_club_transfers_checks.sql check 2 for that).

Run from the repo root:
    python tests/transfermarkt/test_buyer_club_pipeline.py
"""

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipelines" / "transfermarkt"))

import load_buyer_club_transfers as loader   # noqa: E402
import scrape_buyer_clubs as scraper         # noqa: E402
import select_buyer_clubs as selector        # noqa: E402
import inspect_transfer_tables as inspector  # noqa: E402
import extract_transfermarkt_transfer_history as extractor  # noqa: E402


# ---- synthetic page helpers ------------------------------------------------

def row(player_id, name, club_id, club_name, season, fee):
    slug = name.lower().replace(" ", "-")
    return (
        f'<tr>'
        f'<td class="hauptlink"><a href="/{slug}/profil/spieler/{player_id}">{name}</a></td>'
        f'<td class="no-border-rechts zentriert"><a href="/c/startseite/verein/{club_id}/saison_id/{season}"><img src="x.png"></a></td>'
        f'<td class="no-border-links"><a href="/c/startseite/verein/{club_id}/saison_id/{season}">{club_name}</a></td>'
        f'<td class="rechts">{fee}</td>'
        f'</tr>'
    )


def table(*rows):
    # the real pages use the same header row on every table
    header = "<tr><th>Players</th><th>Club</th><th>Transfer sum</th></tr>"
    return f"<table>{header}{''.join(rows)}</table>"


def section(heading, *rows):
    """A heading directly above its table, the way the real pages are laid out."""
    return f"<h2>{heading}</h2>{table(*rows)}"


def page(*sections, title="Some Club - Transfer history"):
    return f"<html><head><title>{title}</title></head><body>{''.join(sections)}</body></html>"


GOOD_PAGE = page(
    section("Arrivals 19/20",
            row(1, "Player One", 383, "PSV", 2019, "€15.00m"),
            row(2, "Player Two", 610, "Ajax", 2019, "free transfer")),
    section("Departures 19/20",
            row(3, "Player Three", 1090, "AZ", 2019, "loan transfer"),
            row(6, "Player Six", 8817, "Ajax U21", 2019, "-")),
    section("Arrivals 16/17", row(4, "Player Four", 200, "Utrecht", 2016, "End of loan")),
    section("Departures 15/16", row(5, "Player Five", 403, "Willem II", 2015, "?")),
)

# Every season a full Arrivals/Departures pair: position parity and headings agree everywhere.
CLEAN_PAIRS_PAGE = page(
    section("Arrivals 19/20", row(1, "A", 10, "X", 2019, "€5.00m")),
    section("Departures 19/20", row(2, "B", 11, "Y", 2019, "€1.00m")),
    section("Arrivals 18/19", row(3, "C", 12, "Z", 2018, "€2.00m")),
    section("Departures 18/19", row(4, "D", 13, "W", 2018, "-")),
)

# Atalanta's real shape: a LONE future-dated "Departures 27/28" table at the top.
# Position parity labels it 'in' and then every table below it backwards.
LONE_TOP_DEPARTURES_PAGE = page(
    section("Departures 27/28", row(9, "Future Leaver", 20, "Q", 2027, "-")),
    section("Arrivals 26/27", row(1, "A", 10, "X", 2026, "€5.00m"), row(2, "B", 11, "Y", 2026, "€2.00m")),
    section("Departures 26/27", row(3, "C", 12, "Z", 2026, "€1.00m")),
    section("Arrivals 25/26", row(4, "D", 13, "W", 2025, "free transfer")),
    section("Departures 25/26", row(5, "E", 14, "V", 2025, "€3.00m")),
)

# Anzhi's real shape: correct pairs, then a lone "Departures 22/23" mid-page,
# which inverts everything OLDER than it.
LONE_MID_PAGE = page(
    section("Arrivals 24/25", row(1, "A", 10, "X", 2024, "€1.00m")),
    section("Departures 24/25", row(2, "B", 11, "Y", 2024, "€2.00m")),
    section("Departures 22/23", row(3, "C", 12, "Z", 2022, "€3.00m")),   # lone: no Arrivals 22/23
    section("Arrivals 21/22", row(4, "D", 13, "W", 2021, "€4.00m")),
    section("Departures 21/22", row(5, "E", 14, "V", 2021, "€5.00m")),
)


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def parsed(html):
    return scraper.parse_transfer_page(html)


GOOD_INFO = parsed(GOOD_PAGE)[1]


# ---- parsing ---------------------------------------------------------------

class ParseTests(unittest.TestCase):
    def setUp(self):
        self.transfers, self.info = parsed(GOOD_PAGE)

    def test_row_count_and_direction_from_headings(self):
        self.assertEqual(len(self.transfers), 6)
        self.assertEqual([t["direction"] for t in self.transfers],
                         ["in", "in", "out", "out", "in", "out"])

    def test_fields_extracted(self):
        t = self.transfers[0]
        self.assertEqual(t["player_id"], 1)
        self.assertEqual(t["name"], "Player One")
        self.assertEqual(t["counterparty_club_id"], 383)
        self.assertEqual(t["counterparty_club_name"], "PSV")
        self.assertEqual(t["season_id"], 2019)
        self.assertEqual(t["fee"], {"amount": 15.0, "type": "permanent_transfer"})

    def test_fee_types(self):
        types = [t["fee"]["type"] for t in self.transfers]
        self.assertEqual(types, ["permanent_transfer", "free_transfer", "unpaid_loan",
                                 "unknown", "loan_ended", "unknown_historical"])

    def test_internal_promotion_flag_only_for_u_suffix_sides(self):
        flags = {t["counterparty_club_name"]: t["is_internal_promotion"] for t in self.transfers}
        self.assertTrue(flags["Ajax U21"])
        self.assertFalse(flags["PSV"])

    def test_summarize(self):
        s = scraper.summarize(self.transfers)
        self.assertEqual((s["rows"], s["in"], s["out"]), (6, 3, 3))
        self.assertEqual((s["first_season"], s["last_season"]), (2015, 2019))
        self.assertEqual(s["unrecognized_fees"], 0)

    def test_empty_page_parses_to_nothing(self):
        transfers, info = parsed(page())
        self.assertEqual(transfers, [])
        self.assertEqual(info["tables"], 0)

    def test_a_clean_page_needs_no_direction_correction(self):
        self.assertEqual(self.info["parity_wrong_tables"], 0)
        self.assertEqual(self.info["unresolved"], [])


# ---- url / csv -------------------------------------------------------------

class UrlAndCsvTests(unittest.TestCase):
    def test_build_url_default_and_slug(self):
        self.assertEqual(scraper.build_url(985),
                         "https://www.transfermarkt.com/-/alletransfers/verein/985")
        self.assertEqual(scraper.build_url(985, "manchester-united"),
                         "https://www.transfermarkt.com/manchester-united/alletransfers/verein/985")

    def test_read_club_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "clubs.csv"
            p.write_text(
                "counterparty_club_id,counterparty_club_name,slug\n"
                "985,Manchester Utd,manchester-united\n"
                ",No Id Club,\n"
                "27,Bayern Munich,\n", encoding="utf-8")
            clubs = scraper.read_club_list(p)
        self.assertEqual(clubs, [
            {"club_id": 985, "name": "Manchester Utd", "slug": "manchester-united"},
            {"club_id": 27, "name": "Bayern Munich", "slug": None},
        ])

    def test_read_club_list_without_slug_column(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "clubs.csv"
            p.write_text("counterparty_club_id,counterparty_club_name\n27,Bayern Munich\n", encoding="utf-8")
            self.assertEqual(scraper.read_club_list(p)[0]["slug"], None)


# ---- network handling ------------------------------------------------------

class FetchTests(unittest.TestCase):
    def test_403_fails_immediately_without_retry(self):
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(403)) as get, \
             mock.patch.object(scraper.time, "sleep") as sleep:
            with self.assertRaises(scraper.ScrapeError) as cm:
                scraper.fetch_html("http://x")
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()
        self.assertIn("blocked", str(cm.exception))

    def test_405_also_treated_as_blocked(self):
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(405)) as get, \
             mock.patch.object(scraper.time, "sleep"):
            with self.assertRaises(scraper.ScrapeError):
                scraper.fetch_html("http://x")
        self.assertEqual(get.call_count, 1)

    def test_429_retries_with_backoff_then_succeeds(self):
        responses = [FakeResponse(429), FakeResponse(429), FakeResponse(200, "<html>ok</html>")]
        with mock.patch.object(scraper.requests, "get", side_effect=responses) as get, \
             mock.patch.object(scraper.time, "sleep") as sleep:
            html = scraper.fetch_html("http://x")
        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(get.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 15])

    def test_persistent_500_gives_up_and_does_not_sleep_after_last_attempt(self):
        with mock.patch.object(scraper.requests, "get", return_value=FakeResponse(500)) as get, \
             mock.patch.object(scraper.time, "sleep") as sleep:
            with self.assertRaises(scraper.ScrapeError) as cm:
                scraper.fetch_html("http://x")
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("HTTP 500", str(cm.exception))

    def test_network_error_retries(self):
        side = [scraper.requests.ConnectionError("boom"), FakeResponse(200, "<html/>")]
        with mock.patch.object(scraper.requests, "get", side_effect=side) as get, \
             mock.patch.object(scraper.time, "sleep"):
            self.assertEqual(scraper.fetch_html("http://x"), "<html/>")
        self.assertEqual(get.call_count, 2)


# ---- the failure guard: empty or direction-uncertain results must never look like success

class ScrapeClubTests(unittest.TestCase):
    def test_good_page_returns_transfers_title_and_info(self):
        with mock.patch.object(scraper, "fetch_html", return_value=GOOD_PAGE):
            url, title, transfers, info = scraper.scrape_club(985)
        self.assertIn("/-/alletransfers/verein/985", url)
        self.assertEqual(title, "Some Club - Transfer history")
        self.assertEqual(len(transfers), 6)
        self.assertEqual(info["parity_wrong_tables"], 0)

    def test_zero_transfers_from_a_200_is_a_failure_not_a_success(self):
        challenge = page(title="Just a moment...")
        with mock.patch.object(scraper, "fetch_html", return_value=challenge):
            with self.assertRaises(scraper.ScrapeError) as cm:
                scraper.scrape_club(985)
        self.assertIn("0 transfers parsed", str(cm.exception))
        self.assertIn("Just a moment", str(cm.exception))

    def test_a_relevant_table_with_no_trustworthy_direction_fails_the_club(self):
        headless = page(table(row(1, "A", 10, "X", 2019, "€5.00m")))   # a 2019 table with no heading at all
        with mock.patch.object(scraper, "fetch_html", return_value=headless):
            with self.assertRaises(scraper.ScrapeError) as cm:
                scraper.scrape_club(985)
        self.assertIn("no trustworthy direction", str(cm.exception))
        self.assertIn("NOT saved", str(cm.exception))

    def test_a_lone_future_table_is_handled_not_failed(self):
        with mock.patch.object(scraper, "fetch_html", return_value=LONE_TOP_DEPARTURES_PAGE):
            _, _, transfers, info = scraper.scrape_club(800)
        self.assertEqual(len(transfers), 6)
        self.assertEqual(info["parity_wrong_tables"], 5)


# ---- scrape loop: resume, failure isolation, exit code ---------------------

class ScrapeMainTests(unittest.TestCase):
    def _run_main(self, out_dir, csv_path, argv_extra=()):
        argv = ["scrape_buyer_clubs.py", "--input", str(csv_path), *argv_extra]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(scraper, "OUT_DIR", out_dir), \
             mock.patch.object(scraper.time, "sleep"):
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(io.StringIO()):
                scraper.main()
        return cm.exception.code

    def _csv(self, d):
        p = Path(d) / "clubs.csv"
        p.write_text("counterparty_club_id,counterparty_club_name\n"
                     "985,Man Utd\n27,Bayern\n", encoding="utf-8")
        return p

    @staticmethod
    def _good(club_id, slug=None):
        transfers, info = parsed(GOOD_PAGE)
        return ("u", "t", transfers, info)

    def test_failure_does_not_write_file_or_stop_other_clubs_and_exits_nonzero(self):
        def fake_scrape(club_id, slug=None):
            if club_id == 985:
                raise scraper.ScrapeError("blocked")
            return self._good(club_id)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "buyers"
            with mock.patch.object(scraper, "scrape_club", side_effect=fake_scrape):
                code = self._run_main(out, self._csv(d))
            self.assertEqual(code, 1)
            self.assertFalse((out / "985_transfers.json").exists())
            self.assertTrue((out / "27_transfers.json").exists())

    def test_existing_json_is_skipped_unless_force(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "buyers"
            out.mkdir()
            (out / "985_transfers.json").write_text("[]")
            fake = mock.Mock(side_effect=self._good)
            with mock.patch.object(scraper, "scrape_club", fake):
                self._run_main(out, self._csv(d), ["--only", "985"])
            fake.assert_not_called()
            with mock.patch.object(scraper, "scrape_club", fake):
                self._run_main(out, self._csv(d), ["--only", "985", "--force"])
            fake.assert_called_once()

    def test_only_limits_to_requested_club(self):
        fake = mock.Mock(side_effect=self._good)
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(scraper, "scrape_club", fake):
                code = self._run_main(Path(d) / "buyers", self._csv(d), ["--only", "27"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.call_args.args[0], 27)
        self.assertEqual(fake.call_count, 1)

    def test_saved_json_carries_the_corrected_directions(self):
        def lone_top(club_id, slug=None):
            transfers, info = parsed(LONE_TOP_DEPARTURES_PAGE)
            return ("u", "t", transfers, info)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "buyers"
            with mock.patch.object(scraper, "scrape_club", side_effect=lone_top):
                self._run_main(out, self._csv(d), ["--only", "985"])
            saved = json.loads((out / "985_transfers.json").read_text())
        # Future Leaver (the lone 2027 departure), then A, B (arrivals), C (departure), D (arrival), E (departure)
        self.assertEqual([t["direction"] for t in saved], ["out", "in", "in", "out", "in", "out"])


# ---- loader: row building --------------------------------------------------

def t(season, direction="in", fee_amount=1.5, fee_type="permanent_transfer", **kw):
    base = {"player_id": 7, "name": "P", "direction": direction,
            "counterparty_club_id": 99, "counterparty_club_name": "X",
            "season_id": season, "fee": {"amount": fee_amount, "type": fee_type},
            "is_internal_promotion": False}
    base.update(kw)
    return base


class BuildRowsTests(unittest.TestCase):
    def test_skips_no_season_and_pre_min_season_and_counts_them(self):
        rows, no_season, too_old = loader.build_rows(
            27, "Bayern", [t(2019), t(None), t(1999), t(2000), t(1985)])
        self.assertEqual(len(rows), 2)            # 2019 and 2000 (boundary is inclusive)
        self.assertEqual((no_season, too_old), (1, 2))

    def test_min_season_none_loads_everything_with_a_season(self):
        rows, _, too_old = loader.build_rows(27, "B", [t(1955), t(2019)], min_season=None)
        self.assertEqual((len(rows), too_old), (2, 0))

    def test_tuple_matches_insert_columns_in_order(self):
        cols_sql = re.search(r"\((.*?)\)\s*VALUES", loader.INSERT_SQL, re.S).group(1)
        cols = [c.strip() for c in cols_sql.split(",")]
        rows, _, _ = loader.build_rows(27, "Bayern", [t(2019, direction="out", fee_amount=42.0,
                                                          fee_type="paid_loan",
                                                          is_internal_promotion=True)])
        self.assertEqual(len(rows[0]), len(cols))
        got = dict(zip(cols, rows[0]))
        self.assertEqual(got, {
            "player_id": 7, "player_name": "P", "own_club_id": 27, "own_club_name": "Bayern",
            "direction": "out", "counterparty_club_id": 99, "counterparty_club_name": "X",
            "season_id": 2019, "fee_amount": 42.0, "fee_type": "paid_loan",
            "is_internal_promotion": True,
        })

    def test_club_id_from_filename(self):
        self.assertEqual(loader.club_id_from_filename(Path("985_transfers.json")), 985)
        self.assertIsNone(loader.club_id_from_filename(Path("notes.json")))
        self.assertIsNone(loader.club_id_from_filename(Path("985_transfers.json.bak")))


# ---- loader: transaction behavior against a fake connection ----------------

class FakeCursor:
    def __init__(self, log):
        self.log, self.rowcount = log, 3
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


class LoaderMainTests(unittest.TestCase):
    def _setup(self, d):
        buyers = Path(d) / "buyers"
        buyers.mkdir()
        (buyers / "27_transfers.json").write_text(json.dumps([t(2019), t(1990)]))
        clubs = Path(d) / "clubs.csv"
        clubs.write_text("counterparty_club_id,counterparty_club_name\n27,Bayern Munich\n")
        return buyers, clubs

    def test_delete_then_insert_then_commit_per_club(self):
        conn = FakeConn()
        with tempfile.TemporaryDirectory() as d:
            buyers, clubs = self._setup(d)
            with mock.patch.object(loader, "BUYERS_DIR", buyers), \
                 mock.patch.object(loader, "CLUB_LIST", clubs), \
                 mock.patch.object(loader, "get_connection", return_value=conn), \
                 mock.patch.object(loader, "execute_values") as ev, \
                 contextlib.redirect_stdout(io.StringIO()):
                loader.main()
        kinds = [e[0] for e in conn.log]
        self.assertEqual(kinds, ["execute", "commit"])
        self.assertIn("DELETE FROM buyer_club_transfers WHERE own_club_id", conn.log[0][1])
        self.assertEqual(conn.log[0][2], (27,))
        rows = ev.call_args.args[2]
        self.assertEqual(len(rows), 1)                 # the 1990 row is before MIN_SEASON
        self.assertEqual(rows[0][3], "Bayern Munich")  # own_club_name resolved from the CSV
        self.assertTrue(conn.closed)

    def test_insert_failure_rolls_back_and_reraises_and_closes(self):
        conn = FakeConn()
        with tempfile.TemporaryDirectory() as d:
            buyers, clubs = self._setup(d)
            with mock.patch.object(loader, "BUYERS_DIR", buyers), \
                 mock.patch.object(loader, "CLUB_LIST", clubs), \
                 mock.patch.object(loader, "get_connection", return_value=conn), \
                 mock.patch.object(loader, "execute_values", side_effect=RuntimeError("db down")):
                with self.assertRaises(RuntimeError), contextlib.redirect_stdout(io.StringIO()):
                    loader.main()
        kinds = [e[0] for e in conn.log]
        self.assertIn("rollback", kinds)
        self.assertNotIn("commit", kinds)
        self.assertTrue(conn.closed)

    def test_no_files_exits_cleanly_without_touching_the_database(self):
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "buyers"
            empty.mkdir()
            with mock.patch.object(loader, "BUYERS_DIR", empty), \
                 mock.patch.object(loader, "get_connection") as gc, \
                 contextlib.redirect_stdout(io.StringIO()):
                loader.main()
            gc.assert_not_called()


# ---- club selection ---------------------------------------------------------

def ranked(club_id, name, total):
    return {"counterparty_club_id": str(club_id), "counterparty_club_name": name,
            "num_transfers": "3", "total_paid_to_eredivisie_clubs": str(total),
            "first_season": "2012", "last_season": "2024"}


class SelectClubsTests(unittest.TestCase):
    EREDIVISIE = {383, 610}

    def _select(self, rows):
        selected, dropped = selector.select_clubs(rows, self.EREDIVISIE)
        return [r["counterparty_club_name"] for r in selected], \
               [(r["counterparty_club_name"], why) for r, why in dropped]

    def test_each_filter_and_the_inclusive_cutoff(self):
        sel, dropped = self._select([
            ranked(985, "Man Utd", 262.87),
            ranked(383, "PSV", 113.33),            # Eredivisie, even though it is far above the cutoff
            ranked(583, "PSG", 10.0),              # exactly on the cutoff -> kept (inclusive)
            ranked(111, "Small Buyer", 9.99),      # just under -> dropped
            ranked(8817, "Ajax U21", 10.14),       # reserve side above the cutoff -> dropped
            ranked(2464, "Barcelona B", 3.25),     # reserve side AND under the cutoff -> counted as under_cutoff
        ])
        self.assertEqual(sel, ["Man Utd", "PSG"])
        self.assertEqual(dict(dropped), {"PSV": "eredivisie", "Small Buyer": "under_cutoff",
                                         "Ajax U21": "reserve_side", "Barcelona B": "under_cutoff"})

    def test_eredivisie_check_wins_over_every_other_reason(self):
        _, dropped = self._select([ranked(610, "Ajax II", 0.5)])   # Eredivisie id AND reserve-looking AND tiny
        self.assertEqual(dropped, [("Ajax II", "eredivisie")])

    def test_reserve_side_patterns(self):
        rows = [ranked(i, n, 50.0) for i, n in enumerate(
            ["Din. Zagreb II", "Sporting CP B", "Jong Ajax", "Chelsea U23", "Club Brugge", "Real Madrid"], start=1)]
        sel, dropped = self._select(rows)
        self.assertEqual(sel, ["Club Brugge", "Real Madrid"])
        self.assertEqual({n for n, _ in dropped}, {"Din. Zagreb II", "Sporting CP B", "Jong Ajax", "Chelsea U23"})

    def test_ranking_order_is_preserved(self):
        sel, _ = self._select([ranked(1, "First", 90), ranked(2, "Second", 50), ranked(3, "Third", 20)])
        self.assertEqual(sel, ["First", "Second", "Third"])

    def test_empty_eredivisie_table_refuses_to_run(self):
        class Cur:
            def execute(self, *a): pass
            def fetchall(self): return []
            def __enter__(self): return self
            def __exit__(self, *a): return False
        class Conn:
            def cursor(self): return Cur()
            def close(self): pass
        with mock.patch.object(selector, "get_connection", return_value=Conn()):
            with self.assertRaises(SystemExit) as cm:
                selector.read_eredivisie_ids()
        self.assertIn("refusing to run", str(cm.exception))

    def test_missing_ranked_file_is_a_readable_exit(self):
        with self.assertRaises(SystemExit) as cm:
            selector.read_ranked(Path("/nonexistent/ranked.csv"))
        self.assertIn("list_buyer_clubs.py", str(cm.exception))


class MissingInputTests(unittest.TestCase):
    def test_scraper_missing_input_file_exits_with_instructions_not_a_traceback(self):
        argv = ["scrape_buyer_clubs.py", "--input", "/nonexistent/clubs.csv"]
        with mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as cm:
                scraper.main()
        msg = str(cm.exception)
        self.assertIn("not found", msg)
        self.assertIn("select_buyer_clubs.py", msg)


# ---- page-layout inspector --------------------------------------------------

class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.tables = inspector.describe_tables(LONE_TOP_DEPARTURES_PAGE)

    def test_describes_heading_direction_next_to_the_old_position_rule(self):
        self.assertEqual([t["parity"] for t in self.tables], ["in", "out", "in", "out", "in"])
        self.assertEqual([t["heading_direction"] for t in self.tables], ["out", "in", "out", "in", "out"])
        self.assertEqual(self.tables[0]["heading"], "Departures 27/28")
        self.assertEqual(self.tables[0]["seasons"], [2027])
        self.assertEqual(self.tables[1]["header"], ("Players", "Club", "Transfer sum"))

    def test_season_blocks_expose_the_table_that_breaks_pair_parity(self):
        blocks = inspector.season_blocks(self.tables)
        self.assertEqual(blocks, [(2027, [0]), (2026, [1, 2]), (2025, [3, 4])])

    def test_report_counts_where_the_position_rule_was_wrong(self):
        text = inspector.report(self.tables)
        self.assertIn("the position rule would be WRONG on 5 of them", text)
        self.assertIn("first wrong at table index 0", text)
        self.assertIn("season=2027  table indexes=[0]", text)

    def test_mid_page_break_reports_the_first_wrong_table(self):
        text = inspector.report(inspector.describe_tables(LONE_MID_PAGE))
        self.assertIn("the position rule would be WRONG on 3 of them", text)
        self.assertIn("first wrong at table index 2", text)

    def test_clean_page_reports_no_disagreement_and_every_block_a_pair(self):
        text = inspector.report(inspector.describe_tables(CLEAN_PAIRS_PAGE))
        self.assertIn("every block is a pair", text)
        self.assertIn("the position rule would be WRONG on 0 of them", text)

    def test_tables_with_no_heading_and_shared_headings_are_reported(self):
        shared = ("<html><body><h2>Arrivals 19/20</h2>"
                  + table(row(1, "A", 10, "X", 2019, "€1.00m"))
                  + table(row(2, "B", 11, "Y", 2019, "€2.00m"))        # second table under the SAME heading
                  + table(row(3, "C", 12, "Z", 2018, "€3.00m")) + "</body></html>")
        text = inspector.report(inspector.describe_tables(shared))
        self.assertIn("headings shared by more than one table (treated as unresolved): 1", text)
        headless = "<html><body>" + table(row(1, "A", 10, "X", 2019, "€1.00m")) + "</body></html>"
        self.assertIn("tables with no Arrivals/Departures heading: 1",
                      inspector.report(inspector.describe_tables(headless)))

    def test_empty_tables_are_reported_and_ignored_by_blocks(self):
        page_ = ("<html><body><h2>Arrivals 19/20</h2>" + table()
                 + "<h2>Departures 19/20</h2>" + table(row(2, "B", 11, "Y", 2019, "€1.00m")) + "</body></html>")
        tables = inspector.describe_tables(page_)
        self.assertEqual(tables[0]["rows"], 0)
        text = inspector.report(tables)
        self.assertIn("empty tables: 1", text)
        self.assertNotIn("season=None", text)     # the empty table must not form a block of its own
        self.assertIn("1 blocks.", text)


# ---- the shared extractor: direction from headings ---------------------------

class HeadingDirectionTests(unittest.TestCase):
    def test_heading_text_to_direction(self):
        self.assertEqual(extractor.heading_direction("Arrivals 26/27"), "in")
        self.assertEqual(extractor.heading_direction("Departures 27/28"), "out")
        self.assertEqual(extractor.heading_direction("  arrivals 90/91"), "in")
        self.assertIsNone(extractor.heading_direction("Squad"))
        self.assertIsNone(extractor.heading_direction("Arrivalsx 26/27"))
        self.assertIsNone(extractor.heading_direction(None))

    def test_heading_start_year_is_century_agnostic(self):
        self.assertEqual(extractor.heading_start_yy("Arrivals 26/27"), 26)
        self.assertEqual(extractor.heading_start_yy("Departures 99/00"), 99)
        self.assertIsNone(extractor.heading_start_yy("Arrivals"))


class ExtractorParseTests(unittest.TestCase):
    def test_lone_top_departures_table_no_longer_inverts_the_page(self):
        """Atalanta's real failure: the position rule labeled everything backwards."""
        transfers, info = extractor.parse_transfer_page_html(LONE_TOP_DEPARTURES_PAGE)
        self.assertEqual([(t["name"], t["direction"]) for t in transfers],
                         [("Future Leaver", "out"), ("A", "in"), ("B", "in"), ("C", "out"),
                          ("D", "in"), ("E", "out")])
        self.assertEqual(info["parity_wrong_tables"], 5)
        self.assertEqual(info["parity_wrong_rows_relevant"], 6)
        self.assertEqual(info["first_parity_wrong_index"], 0)

    def test_lone_mid_page_table_only_inverts_what_is_below_it(self):
        """Anzhi's real failure: tables above the break were right, below it were backwards."""
        transfers, info = extractor.parse_transfer_page_html(LONE_MID_PAGE)
        self.assertEqual([(t["name"], t["direction"]) for t in transfers],
                         [("A", "in"), ("B", "out"), ("C", "out"), ("D", "in"), ("E", "out")])
        self.assertEqual(info["first_parity_wrong_index"], 2)
        self.assertEqual(info["parity_wrong_tables"], 3)

    def test_undated_or_old_table_with_no_heading_is_skipped_not_fatal(self):
        old = page(section("Arrivals 19/20", row(1, "A", 10, "X", 2019, "€1.00m")),
                   table(row(2, "Old", 11, "Y", 1950, "€5")))       # 1950, no heading of its own
        transfers, info = extractor.parse_transfer_page_html(old)
        # the headless 1950 table inherits the previous heading element, which table 0 already claimed
        self.assertEqual([t["name"] for t in transfers], ["A"])
        self.assertEqual(len(info["unresolved"]), 1)
        self.assertEqual(info["unresolved"][0]["rows_relevant"], 0)
        extractor.require_resolved_directions(info)        # tolerated: nothing from 2000 on is affected

    def test_relevant_unresolved_table_raises(self):
        headless = page(table(row(1, "A", 10, "X", 2019, "€1.00m")))
        _, info = extractor.parse_transfer_page_html(headless)
        self.assertEqual(info["unresolved"][0]["rows_relevant"], 1)
        with self.assertRaises(extractor.DirectionError) as cm:
            extractor.require_resolved_directions(info)
        self.assertIn("no trustworthy direction", str(cm.exception))

    def test_a_heading_shared_by_two_tables_is_unresolved_for_the_second(self):
        shared = ("<html><body><h2>Arrivals 19/20</h2>"
                  + table(row(1, "A", 10, "X", 2019, "€1.00m"))
                  + table(row(2, "B", 11, "Y", 2019, "€2.00m")) + "</body></html>")
        transfers, info = extractor.parse_transfer_page_html(shared)
        self.assertEqual([t["name"] for t in transfers], ["A"])
        self.assertIn("already used by table 0", info["unresolved"][0]["problem"])

    def test_heading_season_must_match_its_own_rows(self):
        mismatch = page(section("Arrivals 19/20", row(1, "A", 10, "X", 2015, "€1.00m")))
        transfers, info = extractor.parse_transfer_page_html(mismatch)
        self.assertEqual(transfers, [])
        self.assertIn("heading season 19", info["unresolved"][0]["problem"])

    def test_relevance_boundary_is_inclusive_of_the_cutoff_season(self):
        on = page(table(row(1, "A", 10, "X", extractor.RELEVANT_FROM_SEASON, "€1.00m")))
        below = page(table(row(1, "A", 10, "X", extractor.RELEVANT_FROM_SEASON - 1, "€1.00m")))
        self.assertEqual(extractor.parse_transfer_page_html(on)[1]["unresolved"][0]["rows_relevant"], 1)
        self.assertEqual(extractor.parse_transfer_page_html(below)[1]["unresolved"][0]["rows_relevant"], 0)

    def test_extract_all_transfers_keeps_its_signature_and_uses_headings(self):
        resp = mock.Mock(text=LONE_TOP_DEPARTURES_PAGE)
        with mock.patch.object(extractor.requests, "get", return_value=resp):
            transfers = extractor.extract_all_transfers("http://x")
        self.assertIsInstance(transfers, list)
        self.assertEqual(transfers[0]["direction"], "out")

    def test_extract_all_transfers_raises_instead_of_guessing(self):
        resp = mock.Mock(text=page(table(row(1, "A", 10, "X", 2019, "€1.00m"))))
        with mock.patch.object(extractor.requests, "get", return_value=resp):
            with self.assertRaises(extractor.DirectionError):
                extractor.extract_all_transfers("http://x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
