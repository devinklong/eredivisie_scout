"""
Loads the scraped Big-5 league-season membership (data/transfermarkt/leagues/
{CODE}_{season}.json, written by scrape_league_seasons.py) into
league_season_clubs (schema/transfermarkt/league_season_clubs.sql, run that
first).

Idempotent per league-season: its existing rows are deleted and reinserted in
ONE transaction, so a re-run never duplicates and a failure mid-file leaves
that league-season exactly as it was. A file is checked BEFORE anything touches
the database: the club count must be the league's size that season, and every
record must agree with the file name, so a mislabeled or truncated file cannot
be loaded.

Afterwards run schema/transfermarkt/league_season_clubs_checks.sql.
"""

import json
import re
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from inspect_league_season import BIG5, expected_club_count

LEAGUE_DIR = Path("data/transfermarkt/leagues")
INSERT_SQL = """
    INSERT INTO league_season_clubs (league_code, season_id, club_id, club_name)
    VALUES %s
"""


class BadLeagueFile(Exception):
    pass


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def parse_filename(path):
    m = re.fullmatch(r"([A-Z0-9]+)_(\d{4})\.json", path.name)
    if not m or m.group(1) not in BIG5:
        return None
    return m.group(1), int(m.group(2))


def build_rows(code, season, records):
    """Pure function: validates one file's records, returns insert tuples.
    Raises BadLeagueFile rather than letting a wrong file reach the table."""
    want = expected_club_count(code, season)
    if len(records) != want:
        raise BadLeagueFile(f"{code} {season}: {len(records)} clubs, expected {want}")
    ids = [r["club_id"] for r in records]
    if len(set(ids)) != len(ids):
        raise BadLeagueFile(f"{code} {season}: duplicate club ids")
    for r in records:
        if r["league_code"] != code or r["season_id"] != season:
            raise BadLeagueFile(f"{code} {season}: record says {r['league_code']} {r['season_id']}")
    return [(code, season, r["club_id"], r["club_name"]) for r in records]


def main():
    files = sorted(p for p in LEAGUE_DIR.glob("*.json") if parse_filename(p))
    if not files:
        print(f"No league files in {LEAGUE_DIR} -- run scrape_league_seasons.py first.")
        return
    conn = get_connection()
    loaded = clubs = 0
    try:
        with conn.cursor() as cur:
            for path in files:
                code, season = parse_filename(path)
                rows = build_rows(code, season, json.loads(path.read_text(encoding="utf-8")))
                try:
                    cur.execute("DELETE FROM league_season_clubs WHERE league_code = %s AND season_id = %s",
                                (code, season))
                    replaced = cur.rowcount
                    execute_values(cur, INSERT_SQL, rows)
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                loaded += 1
                clubs += len(rows)
                print(f"{code} {season}: {len(rows)} clubs (replaced {replaced})")
    except psycopg2.errors.UndefinedTable:
        print("\nleague_season_clubs doesn't exist -- run schema/transfermarkt/league_season_clubs.sql first.")
        raise
    finally:
        conn.close()
    print(f"\nLeague-seasons loaded: {loaded}   Club rows: {clubs}")
    print("Next: run schema/transfermarkt/league_season_clubs_checks.sql")


if __name__ == "__main__":
    main()
