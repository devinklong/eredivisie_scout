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
    header = "<tr><th>Player</th><th></th><th>Club</th><th>Fee</th></tr>"
    return f"<table>{header}{''.join(rows)}</table>"


def page(*tables, title="Some Club - Transfer history"):
    return f"<html><head><title>{title}</title></head><body>{''.join(tables)}</body></html>"


GOOD_PAGE = page(
    table(  # index 0 -> 'in'
        row(1, "Player One", 383, "PSV", 2019, "€15.00m"),
        row(2, "Player Two", 610, "Ajax", 2018, "free transfer"),
    ),
    table(  # index 1 -> 'out'
        row(3, "Player Three", 1090, "AZ", 2017, "loan transfer"),
        row(6, "Player Six", 8817, "Ajax U21", 2019, "-"),
    ),
    table(row(4, "Player Four", 200, "Utrecht", 2016, "End of loan")),  # 2 -> 'in'
    table(row(5, "Player Five", 403, "Willem II", 2015, "?")),          # 3 -> 'out'
)


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


# ---- parsing ---------------------------------------------------------------

class ParseTests(unittest.TestCase):
    def setUp(self):
        self.transfers = scraper.parse_transfer_page(GOOD_PAGE)

    def test_row_count_and_direction_by_table_parity(self):
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
        self.assertEqual(scraper.parse_transfer_page(page()), [])


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


# ---- the failure guard: empty result must never look like success ----------

class ScrapeClubTests(unittest.TestCase):
    def test_good_page_returns_transfers_and_title(self):
        with mock.patch.object(scraper, "fetch_html", return_value=GOOD_PAGE):
            url, title, transfers = scraper.scrape_club(985)
        self.assertIn("/-/alletransfers/verein/985", url)
        self.assertEqual(title, "Some Club - Transfer history")
        self.assertEqual(len(transfers), 6)

    def test_zero_transfers_from_a_200_is_a_failure_not_a_success(self):
        challenge = page(title="Just a moment...")
        with mock.patch.object(scraper, "fetch_html", return_value=challenge):
            with self.assertRaises(scraper.ScrapeError) as cm:
                scraper.scrape_club(985)
        self.assertIn("0 transfers parsed", str(cm.exception))
        self.assertIn("Just a moment", str(cm.exception))


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

    def test_failure_does_not_write_file_or_stop_other_clubs_and_exits_nonzero(self):
        def fake_scrape(club_id, slug=None):
            if club_id == 985:
                raise scraper.ScrapeError("blocked")
            return ("u", "t", scraper.parse_transfer_page(GOOD_PAGE))
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
            fake = mock.Mock(return_value=("u", "t", scraper.parse_transfer_page(GOOD_PAGE)))
            with mock.patch.object(scraper, "scrape_club", fake):
                self._run_main(out, self._csv(d), ["--only", "985"])
            fake.assert_not_called()
            with mock.patch.object(scraper, "scrape_club", fake):
                self._run_main(out, self._csv(d), ["--only", "985", "--force"])
            fake.assert_called_once()

    def test_only_limits_to_requested_club(self):
        fake = mock.Mock(return_value=("u", "t", scraper.parse_transfer_page(GOOD_PAGE)))
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(scraper, "scrape_club", fake):
                code = self._run_main(Path(d) / "buyers", self._csv(d), ["--only", "27"])
        self.assertEqual(code, 0)
        self.assertEqual(fake.call_args.args[0], 27)
        self.assertEqual(fake.call_count, 1)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
