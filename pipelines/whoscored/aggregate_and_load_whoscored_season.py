"""
Reads every per-match JSON file for one WhoScored season
(data/whoscored/{season}/*.json), aggregates each player's stats across
all their matches that season, and loads the result into
eredivisie_whoscored_player_season_stats.

FIXED (2026-09-02): now keys by (player, team), not player alone --
matches the fix in derive_*.py/scrape_all_whoscored_matches.py that
added team capture. Also updated to parse the new JSON shape: each
category is now a LIST of records (each a dict with "player"/"team"
plus stats), not a dict keyed by player name -- required since a JSON
object key can't hold a (player, team) tuple. Re-run
scrape_all_whoscored_matches.py first to regenerate the season's JSON
files in the new format before running this against old-format files.

Percentage fields (passes_pct, take_ons_won_pct) are RECOMPUTED from the
summed numerator/denominator across all matches, never averaged across
per-match percentages -- averaging percentages from matches with very
different attempt counts would be wrong (a 100% day on 2 attempts
shouldn't count the same as 75% on 40 attempts).

A player who genuinely transferred between two Eredivisie clubs
mid-season now correctly gets two separate rows (one per club) --
previously (before the team fix) they'd have been silently merged.
"""

import json
from collections import defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

SEASON = "2025-26"
SEASON_ID = 2025
DATA_DIR = Path("data/whoscored") / SEASON

MULTI_STAT_CATEGORIES = [
    "passing", "touches", "take_ons", "tackles", "interceptions",
    "final_third_entries",
]
SINGLE_STAT_CATEGORIES = ["dispossessed", "clearances", "dribbled_past", "errors"]

ADDITIVE_FIELDS = {
    "passing": ["passes", "passes_completed"],
    "touches": ["touches", "touches_def_3rd", "touches_mid_3rd", "touches_att_3rd",
                "touches_def_pen_area", "touches_att_pen_area"],
    "take_ons": ["take_ons", "take_ons_won"],
    "tackles": ["tackles", "tackles_won", "tackles_def_3rd", "tackles_mid_3rd", "tackles_att_3rd"],
    "interceptions": ["interceptions", "interceptions_def_3rd", "interceptions_mid_3rd",
                       "interceptions_att_3rd"],
    "final_third_entries": ["final_third_entries", "pen_area_entries"],
    "dispossessed": ["dispossessed"],
    "clearances": ["clearances"],
    "dribbled_past": ["dribbled_past"],
    "errors": ["errors"],
}


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def aggregate_season(data_dir):
    totals = defaultdict(lambda: defaultdict(int))
    matches_seen = defaultdict(set)

    files = list(data_dir.glob("*.json"))
    print(f"Found {len(files)} match files in {data_dir}")

    for f in files:
        match_id = f.stem
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        all_categories = MULTI_STAT_CATEGORIES + SINGLE_STAT_CATEGORIES
        for category in all_categories:
            records = data.get(category, [])
            for record in records:
                player = record.get("player")
                team = record.get("team")
                if player is None or team is None:
                    continue  # e.g. a 'Start' event with no player -- skip
                key = (player, team)
                matches_seen[key].add(match_id)
                for field in ADDITIVE_FIELDS[category]:
                    value = record.get(field)
                    if value is not None:
                        totals[key][field] += value

    return totals, matches_seen


def build_rows(totals, matches_seen):
    rows = []
    for (player, team), stats in totals.items():
        passes = stats.get("passes", 0)
        passes_completed = stats.get("passes_completed", 0)
        passes_pct = round((passes_completed / passes) * 100, 1) if passes else None

        take_ons = stats.get("take_ons", 0)
        take_ons_won = stats.get("take_ons_won", 0)
        take_ons_won_pct = round((take_ons_won / take_ons) * 100, 1) if take_ons else None

        rows.append((
            player, team, SEASON_ID, len(matches_seen[(player, team)]),
            passes, passes_completed, passes_pct,
            stats.get("touches", 0), stats.get("touches_def_3rd", 0),
            stats.get("touches_mid_3rd", 0), stats.get("touches_att_3rd", 0),
            stats.get("touches_def_pen_area", 0), stats.get("touches_att_pen_area", 0),
            take_ons, take_ons_won, take_ons_won_pct,
            stats.get("dispossessed", 0),
            stats.get("tackles", 0), stats.get("tackles_won", 0),
            stats.get("tackles_def_3rd", 0), stats.get("tackles_mid_3rd", 0),
            stats.get("tackles_att_3rd", 0),
            stats.get("interceptions", 0), stats.get("interceptions_def_3rd", 0),
            stats.get("interceptions_mid_3rd", 0), stats.get("interceptions_att_3rd", 0),
            stats.get("clearances", 0), stats.get("dribbled_past", 0), stats.get("errors", 0),
            stats.get("final_third_entries", 0), stats.get("pen_area_entries", 0),
        ))
    return rows


def main():
    totals, matches_seen = aggregate_season(DATA_DIR)
    print(f"Aggregated {len(totals)} distinct (player, team) pairs.")

    rows = build_rows(totals, matches_seen)

    conn = get_connection()
    insert_sql = """
        INSERT INTO eredivisie_whoscored_player_season_stats
            (player_name, team, season_id, matches_with_data,
             passes, passes_completed, passes_pct,
             touches, touches_def_3rd, touches_mid_3rd, touches_att_3rd,
             touches_def_pen_area, touches_att_pen_area,
             take_ons, take_ons_won, take_ons_won_pct,
             dispossessed,
             tackles, tackles_won, tackles_def_3rd, tackles_mid_3rd, tackles_att_3rd,
             interceptions, interceptions_def_3rd, interceptions_mid_3rd, interceptions_att_3rd,
             clearances, dribbled_past, errors,
             final_third_entries, pen_area_entries)
        VALUES %s
        ON CONFLICT (player_name, team, season_id) DO NOTHING
    """
    with conn.cursor() as cur:
        execute_values(cur, insert_sql, rows)
        print(f"Rows inserted: {cur.rowcount}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
