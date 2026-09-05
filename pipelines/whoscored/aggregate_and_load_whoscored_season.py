"""
Reads every per-match JSON file for EVERY confirmed-working WhoScored
season (data/whoscored/{season}/*.json), aggregates each player's stats
across all their matches within each season, and loads the result into
eredivisie_whoscored_player_season_stats -- one season at a time, in a
loop, rather than the single hardcoded season this originally handled.

FIXED (2026-09-02): now keys by (player, team), not player alone --
matches the fix in derive_*.py/scrape_all_whoscored_matches.py that
added team capture. Also updated to parse the new JSON shape: each
category is now a LIST of records (each a dict with "player"/"team"
plus stats), not a dict keyed by player name -- required since a JSON
object key can't hold a (player, team) tuple.

UPDATED: now also carries WhoScored's own native player_id through into
eredivisie_whoscored_player_season_stats.whoscored_player_id. This is
NOT the same ID namespace as Transfermarkt's player_id -- do not join
the two directly without going through the entity-resolution crosswalk
table. player_id is captured once per (player, team) since it's a
constant identity attribute, not summed like the stat fields. If two
records for the same (player, team) within a season disagree on
player_id, the first value seen is kept and a warning is printed --
this should not happen for a real person and is worth investigating if
it fires, not silencing.

Percentage fields (passes_pct, take_ons_won_pct) are RECOMPUTED from the
summed numerator/denominator across all matches, never averaged across
per-match percentages -- averaging percentages from matches with very
different attempt counts would be wrong (a 100% day on 2 attempts
shouldn't count the same as 75% on 40 attempts).

A player who genuinely transferred between two Eredivisie clubs
mid-season now correctly gets two separate rows (one per club).
"""

import json
from collections import defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

SEASONS = [
    "2013-14", "2014-15", "2015-16", "2016-17", "2017-18", "2018-19",
    "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
    "2025-26",
]  # every confirmed-working season (per v1_roadmap.md, 2026-09-02)
DATA_ROOT = Path("data/whoscored")

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


def season_to_id(season):
    """'2013-14' -> 2013 -- matches the season_id convention used
    throughout this project's other tables."""
    return int(season.split("-")[0])


def aggregate_season(data_dir):
    totals = defaultdict(lambda: defaultdict(int))
    matches_seen = defaultdict(set)
    player_ids = {}  # (player, team) -> whoscored player_id, since it's
                      # constant per player/team, not additive like the
                      # stat fields -- captured once, not summed

    files = list(data_dir.glob("*.json"))

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

                # Capture player_id once per (player, team) -- if it's
                # present on this record and we haven't seen it yet for
                # this key, or if a later record disagrees with an
                # earlier one, flag the conflict rather than silently
                # overwriting -- same discipline as the player_id
                # consistency check in parse_raw_whoscored_events.py.
                record_player_id = record.get("player_id")
                if record_player_id is not None:
                    existing = player_ids.get(key)
                    if existing is not None and existing != record_player_id:
                        print(f"  WARNING: conflicting player_id for {key} -- "
                              f"had {existing}, saw {record_player_id} in "
                              f"match {match_id}. Keeping first value.")
                    else:
                        player_ids[key] = record_player_id

                for field in ADDITIVE_FIELDS[category]:
                    value = record.get(field)
                    if value is not None:
                        totals[key][field] += value

    return totals, matches_seen, player_ids, len(files)


def build_rows(totals, matches_seen, player_ids, season_id):
    rows = []
    for (player, team), stats in totals.items():
        passes = stats.get("passes", 0)
        passes_completed = stats.get("passes_completed", 0)
        passes_pct = round((passes_completed / passes) * 100, 1) if passes else None

        take_ons = stats.get("take_ons", 0)
        take_ons_won = stats.get("take_ons_won", 0)
        take_ons_won_pct = round((take_ons_won / take_ons) * 100, 1) if take_ons else None

        rows.append((
            player, team, season_id, len(matches_seen[(player, team)]),
            player_ids.get((player, team)),
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


INSERT_SQL = """
    INSERT INTO eredivisie_whoscored_player_season_stats
        (player_name, team, season_id, matches_with_data, whoscored_player_id,
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
    ON CONFLICT (player_name, team, season_id) DO UPDATE SET
        matches_with_data = EXCLUDED.matches_with_data,
        whoscored_player_id = EXCLUDED.whoscored_player_id,
        passes = EXCLUDED.passes,
        passes_completed = EXCLUDED.passes_completed,
        passes_pct = EXCLUDED.passes_pct,
        touches = EXCLUDED.touches,
        touches_def_3rd = EXCLUDED.touches_def_3rd,
        touches_mid_3rd = EXCLUDED.touches_mid_3rd,
        touches_att_3rd = EXCLUDED.touches_att_3rd,
        touches_def_pen_area = EXCLUDED.touches_def_pen_area,
        touches_att_pen_area = EXCLUDED.touches_att_pen_area,
        take_ons = EXCLUDED.take_ons,
        take_ons_won = EXCLUDED.take_ons_won,
        take_ons_won_pct = EXCLUDED.take_ons_won_pct,
        dispossessed = EXCLUDED.dispossessed,
        tackles = EXCLUDED.tackles,
        tackles_won = EXCLUDED.tackles_won,
        tackles_def_3rd = EXCLUDED.tackles_def_3rd,
        tackles_mid_3rd = EXCLUDED.tackles_mid_3rd,
        tackles_att_3rd = EXCLUDED.tackles_att_3rd,
        interceptions = EXCLUDED.interceptions,
        interceptions_def_3rd = EXCLUDED.interceptions_def_3rd,
        interceptions_mid_3rd = EXCLUDED.interceptions_mid_3rd,
        interceptions_att_3rd = EXCLUDED.interceptions_att_3rd,
        clearances = EXCLUDED.clearances,
        dribbled_past = EXCLUDED.dribbled_past,
        errors = EXCLUDED.errors,
        final_third_entries = EXCLUDED.final_third_entries,
        pen_area_entries = EXCLUDED.pen_area_entries
"""


def main():
    conn = get_connection()
    total_rows_inserted = 0

    with conn.cursor() as cur:
        for season in SEASONS:
            data_dir = DATA_ROOT / season
            if not data_dir.exists():
                print(f"{season}: no data folder found at {data_dir} -- skipping")
                continue

            season_id = season_to_id(season)
            totals, matches_seen, player_ids, file_count = aggregate_season(data_dir)
            rows = build_rows(totals, matches_seen, player_ids, season_id)

            if rows:
                execute_values(cur, INSERT_SQL, rows)
                inserted = cur.rowcount
            else:
                inserted = 0

            conn.commit()
            total_rows_inserted += inserted
            print(f"{season}: {file_count} match files, "
                  f"{len(totals)} (player, team) pairs aggregated, "
                  f"{inserted} rows inserted")

    conn.close()
    print(f"\nTotal rows inserted across all seasons: {total_rows_inserted}")


if __name__ == "__main__":
    main()
