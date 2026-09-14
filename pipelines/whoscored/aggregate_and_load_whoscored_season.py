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

UPDATED (2026-09-04): now also carries WhoScored's own native player_id
through into eredivisie_whoscored_player_season_stats.whoscored_player_id.
This is NOT the same ID namespace as Transfermarkt's player_id -- do not
join the two directly without going through the entity-resolution
crosswalk table. player_id is captured once per (player, team) since
it's a constant identity attribute, not summed like the stat fields. If
two records for the same (player, team) within a season disagree on
player_id, the first value seen is kept and a warning is printed --
this should not happen for a real person and is worth investigating if
it fires, not silencing.

UPDATED (2026-09-05): normalizes WhoScored's team names against the
other two sources' convention before they're used as part of the
(player, team) key. Confirmed mismatch: WhoScored uses "PSV Eindhoven"
where soccerdata/Transfermarkt both use "PSV". Add any further confirmed
mismatches to TEAM_NAME_NORMALIZATION below -- check for others via:
    SELECT DISTINCT team FROM eredivisie_whoscored_player_season_stats
    ORDER BY team;
compared against soccerdata's and Transfermarkt's own distinct team/
club_name lists. This matters because team is part of the blocking key
entity resolution will use -- a silent naming mismatch here would break
matching for any affected club.

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
    "final_third_entries", "aerials",
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
    "aerials": ["aerials", "aerials_won"],
    "dispossessed": ["dispossessed"],
    "clearances": ["clearances"],
    "dribbled_past": ["dribbled_past"],
    "errors": ["errors"],
}

# WhoScored team-name spellings that need to be normalized to match
# soccerdata's and Transfermarkt's convention -- see module docstring.
TEAM_NAME_NORMALIZATION = {
    "PSV Eindhoven": "PSV",
    # add any other confirmed mismatches here
}


def get_connection():
    return psycopg2.connect(dbname="postgres", host="localhost")


def season_to_id(season):
    """'2013-14' -> 2013 -- matches the season_id convention used
    throughout this project's other tables."""
    return int(season.split("-")[0])


def aggregate_season(data_dir):
    """
    UPDATED (2026-09-14): keys aggregation by (identity_key, team),
    where identity_key is the record's player_id if present, falling
    back to the player name string only if player_id is ever missing.
    This fixes a REAL, RECURRING bug: keying by (player, team) alone
    let Eric Botteghin's 2019 Feyenoord season split into two separate
    rows every time this script ran, since WhoScored used two
    different spellings within that one season and the old key treated
    them as two different identities. A one-off SQL fix
    (fix_eric_botteghin_2019_season_split.sql) patched the DATA once,
    but every subsequent rerun of this script silently regenerated the
    same split from scratch, since the script's own logic was never
    fixed -- confirmed the hard way (2026-09-14) when the aerial-stats
    re-run recreated the exact same 2019 duplication.

    Since whoscored_player_id is WhoScored's own stable native ID, key
    on that instead -- both of Eric Botteghin's spellings share the
    same ID (24260), so they now correctly aggregate into ONE row
    regardless of which spelling WhoScored used in a given match.
    Tracks every name spelling seen per identity_key so the most
    common one can be used for the final player_name (see build_rows).
    """
    totals = defaultdict(lambda: defaultdict(int))
    matches_seen = defaultdict(set)
    player_ids = {}  # (identity_key, team) -> whoscored player_id
    name_counts = defaultdict(lambda: defaultdict(int))  # (identity_key, team) -> {name: count}

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

                # Defensive guard against a real, previously-seen bug:
                # some records carry a numeric-looking value (e.g.
                # 298844.0) instead of a real name string -- confirmed
                # months ago as a genuine data artifact (not this
                # project's own bug at the time, root cause never fully
                # identified), previously cleaned up with a one-off
                # DELETE after the fact. Recurred here (2026-09-14)
                # because the 13-season re-run regenerated all per-match
                # JSON from scratch, recreating whatever produces it.
                # Skip defensively rather than crash or silently load
                # garbage -- same check as find_numeric_player_names.py.
                try:
                    float(str(player))
                    print(f"  WARNING: skipping numeric-looking player "
                          f"name {player!r} in match {f.stem}, category "
                          f"{category} -- known data artifact, not a "
                          f"real player.")
                    continue
                except ValueError:
                    pass  # not numeric -- a real name, proceed normally

                team = TEAM_NAME_NORMALIZATION.get(team, team)

                record_player_id = record.get("player_id")
                identity_key = record_player_id if record_player_id is not None else player
                key = (identity_key, team)

                matches_seen[key].add(match_id)
                name_counts[key][player] += 1

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

    return totals, matches_seen, player_ids, name_counts, len(files)


def build_rows(totals, matches_seen, player_ids, name_counts, season_id):
    rows = []
    for (identity_key, team), stats in totals.items():
        display_name = max(name_counts[(identity_key, team)].items(), key=lambda item: item[1])[0]

        passes = stats.get("passes", 0)
        passes_completed = stats.get("passes_completed", 0)
        passes_pct = round((passes_completed / passes) * 100, 1) if passes else None

        take_ons = stats.get("take_ons", 0)
        take_ons_won = stats.get("take_ons_won", 0)
        take_ons_won_pct = round((take_ons_won / take_ons) * 100, 1) if take_ons else None

        aerials = stats.get("aerials", 0)
        aerials_won = stats.get("aerials_won", 0)
        aerials_won_pct = round((aerials_won / aerials) * 100, 1) if aerials else None

        rows.append((
            display_name, team, season_id, len(matches_seen[(identity_key, team)]),
            player_ids.get((identity_key, team)),
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
            aerials, aerials_won, aerials_won_pct,
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
         final_third_entries, pen_area_entries,
         aerials, aerials_won, aerials_won_pct)
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
        pen_area_entries = EXCLUDED.pen_area_entries,
        aerials = EXCLUDED.aerials,
        aerials_won = EXCLUDED.aerials_won,
        aerials_won_pct = EXCLUDED.aerials_won_pct
"""


CLEANUP_ORPHAN_SQL = """
    DELETE FROM eredivisie_whoscored_player_season_stats
    WHERE whoscored_player_id = %s AND team = %s AND season_id = %s AND player_name != %s
"""


def main():
    conn = get_connection()
    total_rows_inserted = 0
    total_orphans_removed = 0

    with conn.cursor() as cur:
        for season in SEASONS:
            data_dir = DATA_ROOT / season
            if not data_dir.exists():
                print(f"{season}: no data folder found at {data_dir} -- skipping")
                continue

            season_id = season_to_id(season)
            totals, matches_seen, player_ids, name_counts, file_count = aggregate_season(data_dir)
            rows = build_rows(totals, matches_seen, player_ids, name_counts, season_id)

            orphans_this_season = 0
            if rows:
                # BEFORE loading: remove any stale row sharing the same
                # whoscored_player_id/team/season but a DIFFERENT
                # player_name -- a real, confirmed leftover from before
                # this script keyed by whoscored_player_id (2026-09-14).
                # ON CONFLICT (player_name, team, season_id) can only
                # ever update the row matching the CURRENT run's chosen
                # display_name -- it has no way to know an old row
                # under a different spelling for the same real person
                # is now obsolete. Skipped for rows with no
                # whoscored_player_id (nothing to identify an orphan by
                # in that case).
                for row in rows:
                    display_name, team, row_season_id = row[0], row[1], row[2]
                    whoscored_player_id = row[4]
                    if whoscored_player_id is not None:
                        cur.execute(CLEANUP_ORPHAN_SQL,
                                    (whoscored_player_id, team, row_season_id, display_name))
                        orphans_this_season += cur.rowcount

                execute_values(cur, INSERT_SQL, rows)
                inserted = len(rows)  # cur.rowcount under-reports with
                                       # execute_values' internal paging --
                                       # see docs/patch_list.md
            else:
                inserted = 0

            conn.commit()
            total_rows_inserted += inserted
            total_orphans_removed += orphans_this_season
            print(f"{season}: {file_count} match files, "
                  f"{len(totals)} (player, team) pairs aggregated, "
                  f"{inserted} rows inserted/updated, "
                  f"{orphans_this_season} orphaned rows removed")

    conn.close()
    print(f"\nTotal rows inserted/updated across all seasons: {total_rows_inserted}")
    print(f"Total orphaned rows removed: {total_orphans_removed}")


if __name__ == "__main__":
    main()
