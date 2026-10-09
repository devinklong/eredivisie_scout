"""
Logical validation of the dataset: pass/fail invariants that must hold if the data makes sense.

The other audits answer "how much is there?" (coverage, NULLs, constant columns, outliers).
This one answers "is what is there consistent with itself?". Each check is a query that returns
the VIOLATING rows; a check passes when it returns no more rows than it is allowed. Examples:
completed passes can never exceed passes, goals must equal non-penalty goals plus penalty
goals, the zone touches must add up to total touches, a percentage must match the counts it
comes from, every season has exactly 18 clubs, a team's player minutes must add up to roughly
34 matches x 11 players x 90 minutes (a missing player shows up here), and a player has one
birth year.

SEVERITY: 'error' = the data is wrong or a join is broken (exit code 1). 'warn' = suspicious,
printed and counted but does not fail the run (rounding, source disagreement, rare real events).
`allowed` is a known number of violations that is documented in `note`; if the count goes UP the
check fails, so a known issue cannot silently grow.

A check whose table is missing is reported as SKIPPED, loudly, never as a pass.

Usage:
    python data_audit/validate_dataset.py                 # print a report, exit 1 on any failed error
    python data_audit/validate_dataset.py --samples 10    # show more offending rows
    python data_audit/validate_dataset.py --only goals_identity ws_touch_zones_sum
"""

import argparse
import sys
from dataclasses import dataclass
from typing import Callable, Optional, Union

M = "master_player_season_stats"
KEY = "canonical_name, player_id, team, season_id"

# Eredivisie: 18 clubs, 34 matches, 11 players on the pitch, 90 minutes.
CLUBS_PER_SEASON = 18
MATCHES_PER_SEASON = 34
# Seasons that were not played in full. 2019 (2019-20) was abandoned by COVID after 26 rounds; the real
# data confirms it (every club sits near 26 x 990 = 25,740 minutes).
SHORT_SEASONS = {2019: 26}
MINUTES_PER_MATCH = 11 * 90                 # 990 player-minutes on the pitch per club per match
TEAM_MINUTES_LOW, TEAM_MINUTES_HIGH = 0.85, 1.10   # play-off matches push it above 1.0

COUNT_COLUMNS = [
    "fbref_matches_played", "fbref_minutes", "fbref_starts", "fbref_goals", "fbref_assists",
    "fbref_goals_plus_assists", "fbref_non_penalty_goals", "fbref_penalty_goals", "fbref_penalty_attempts",
    "fbref_shots", "fbref_shots_on_target", "fbref_yellow_cards", "fbref_red_cards",
    "fbref_second_yellow_cards", "fbref_fouls_committed", "fbref_fouls_drawn", "fbref_offsides",
    "fbref_crosses", "fbref_interceptions", "fbref_tackles_won", "fbref_own_goals",
    "gk_goals_against", "gk_shots_on_target_against", "gk_saves", "gk_wins", "gk_draws", "gk_losses",
    "gk_clean_sheets", "gk_penalty_kicks_faced", "gk_penalty_kicks_allowed", "gk_penalty_kicks_saved",
    "ws_matches_with_data", "ws_passes", "ws_passes_completed", "ws_touches", "ws_touches_def_3rd",
    "ws_touches_mid_3rd", "ws_touches_att_3rd", "ws_touches_def_pen_area", "ws_touches_att_pen_area",
    "ws_take_ons", "ws_take_ons_won", "ws_dispossessed", "ws_tackles", "ws_tackles_won",
    "ws_tackles_def_3rd", "ws_tackles_mid_3rd", "ws_tackles_att_3rd", "ws_interceptions",
    "ws_interceptions_def_3rd", "ws_interceptions_mid_3rd", "ws_interceptions_att_3rd", "ws_clearances",
    "ws_dribbled_past", "ws_errors", "ws_final_third_entries", "ws_pen_area_entries", "ws_aerials", "ws_aerials_won",
]
PERCENT_COLUMNS = [
    "fbref_minutes_pct", "fbref_shots_on_target_pct", "gk_save_pct", "gk_clean_sheet_pct",
    "gk_penalty_kick_save_pct", "ws_passes_pct", "ws_take_ons_won_pct", "ws_aerial_duel_win_pct",
    "ws_ground_duel_win_pct",
]
PER90_PAIRS = [("ws_passes", "ws_passes_per90"), ("ws_touches", "ws_touches_per90"),
               ("ws_tackles", "ws_tackles_per90"), ("ws_aerials", "ws_aerials_per90"),
               ("ws_take_ons", "ws_take_ons_per90"), ("ws_clearances", "ws_clearances_per90")]


EXPECTED_MINUTES_SQL = ("(CASE season_id " + " ".join(f"WHEN {k} THEN {v}" for k, v in SHORT_SEASONS.items())
                        + f" ELSE {MATCHES_PER_SEASON} END * {MINUTES_PER_MATCH})")


@dataclass
class Check:
    name: str
    severity: str                      # 'error' or 'warn'
    description: str
    table: str
    rows_sql: Union[str, Callable]     # SQL (or callable(conn) -> SQL) returning the violating rows
    allowed: int = 0
    note: str = ""


def where_check(name, severity, description, where, cols=None, table=M, allowed=0, note=""):
    cols = cols or KEY
    return Check(name, severity, description, table, f"SELECT {cols} FROM {table} WHERE {where}", allowed, note)


def any_of(columns, template):
    return " OR ".join(template.format(c=c) for c in columns)


def percentile_range_sql(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT attname FROM pg_attribute
                       WHERE attrelid = to_regclass('player_season_style_percentiles')
                         AND attnum > 0 AND NOT attisdropped AND attname LIKE 'pct\\_%' ORDER BY 1""")
        cols = sorted({r[0] for r in cur.fetchall()})
    if not cols:
        return "SELECT player_id, season_id FROM player_season_style_percentiles WHERE FALSE"
    cond = " OR ".join(f"{c} < 0 OR {c} > 100" for c in cols)
    return f"SELECT player_id, season_id FROM player_season_style_percentiles WHERE {cond}"


CHECKS = [
    # ----- grain and identity -----
    Check("duplicate_player_season_team", "error", "one row per canonical player, season and team", M,
          f"SELECT player_id, season_id, team, COUNT(*) AS n FROM {M} WHERE player_id IS NOT NULL "
          "GROUP BY player_id, season_id, team HAVING COUNT(*) > 1"),
    Check("one_birth_year_per_player", "warn", "a canonical player has one FBref birth year across seasons", M,
          f"SELECT player_id, COUNT(DISTINCT fbref_born) AS birth_years FROM {M} WHERE player_id IS NOT NULL "
          "GROUP BY player_id HAVING COUNT(DISTINCT fbref_born) > 1"),
    where_check("born_plausible", "error", "birth year between 1960 and 14 years before the season",
                "fbref_born IS NOT NULL AND (fbref_born < 1960 OR fbref_born > season_id - 14)", KEY + ", fbref_born", allowed=2,
                note="Michael Uchebo (unlinked, player_id NULL), 2010 and 2011, born 1900 = a source placeholder; fix or null at the source"),
    Check("clubs_per_season", "error", f"exactly {CLUBS_PER_SEASON} distinct clubs in every season (a team-name variant shows as 19+)", M,
          f"SELECT season_id, COUNT(DISTINCT team) AS clubs FROM {M} GROUP BY season_id "
          f"HAVING COUNT(DISTINCT team) <> {CLUBS_PER_SEASON}"),
    Check("team_season_minutes", "warn",
          "a club's player minutes add up to matches x 11 x 90 (34 matches, 26 in 2019-20); low = missing players, high = double counting", M,
          f"SELECT team, season_id, SUM(fbref_minutes) AS minutes, {EXPECTED_MINUTES_SQL} AS expected FROM {M} GROUP BY team, season_id "
          f"HAVING SUM(fbref_minutes) NOT BETWEEN {TEAM_MINUTES_LOW} * {EXPECTED_MINUTES_SQL} "
          f"AND {TEAM_MINUTES_HIGH} * {EXPECTED_MINUTES_SQL}"),
    # ----- time and appearances -----
    where_check("nineties_match_minutes", "error", "nineties x 90 equals minutes (to rounding)",
                "fbref_nineties IS NOT NULL AND fbref_minutes IS NOT NULL AND ABS(fbref_nineties * 90 - fbref_minutes) > 5",
                KEY + ", fbref_nineties, fbref_minutes"),
    where_check("starts_le_matches", "error", "starts cannot exceed matches played", "fbref_starts > fbref_matches_played",
                KEY + ", fbref_starts, fbref_matches_played"),
    where_check("minutes_le_matches_cap", "error", "minutes cannot exceed 120 per match played",
                "fbref_minutes > fbref_matches_played * 120", KEY + ", fbref_minutes, fbref_matches_played"),
    where_check("cards_le_matches", "error", "yellow or red cards cannot exceed matches played",
                "fbref_yellow_cards > fbref_matches_played OR fbref_red_cards > fbref_matches_played",
                KEY + ", fbref_yellow_cards, fbref_red_cards, fbref_matches_played", allowed=1,
                note="Willem Huizing, Heerenveen 2016: 2 red cards in 1 match, a source error"),
    where_check("second_yellow_le_red", "warn", "a second yellow is also a red card",
                "fbref_second_yellow_cards > fbref_red_cards", KEY + ", fbref_second_yellow_cards, fbref_red_cards"),
    where_check("non_negative_counts", "error", "no count is negative", any_of(COUNT_COLUMNS, "{c} < 0")),
    where_check("percent_columns_in_range", "error", "every percentage is between 0 and 100",
                any_of(PERCENT_COLUMNS, "({c} < 0 OR {c} > 100)")),
    where_check("points_per_match_range", "error", "points per match between 0 and 3",
                "fbref_points_per_match < 0 OR fbref_points_per_match > 3", KEY + ", fbref_points_per_match"),
    # ----- scoring identities -----
    where_check("goals_identity", "error", "goals = non-penalty goals + penalty goals",
                "fbref_goals IS NOT NULL AND fbref_non_penalty_goals IS NOT NULL AND fbref_penalty_goals IS NOT NULL "
                "AND fbref_goals <> fbref_non_penalty_goals + fbref_penalty_goals",
                KEY + ", fbref_goals, fbref_non_penalty_goals, fbref_penalty_goals"),
    where_check("goals_plus_assists_identity", "error", "goals + assists = goals_plus_assists",
                "fbref_goals_plus_assists IS NOT NULL AND fbref_goals_plus_assists <> fbref_goals + fbref_assists",
                KEY + ", fbref_goals, fbref_assists, fbref_goals_plus_assists"),
    where_check("penalty_goals_le_attempts", "error", "penalty goals cannot exceed penalty attempts",
                "fbref_penalty_goals > fbref_penalty_attempts", KEY + ", fbref_penalty_goals, fbref_penalty_attempts"),
    where_check("shots_on_target_le_shots", "error", "shots on target cannot exceed shots",
                "fbref_shots_on_target > fbref_shots", KEY + ", fbref_shots, fbref_shots_on_target"),
    where_check("goals_le_shots", "warn", "goals cannot exceed shots (goals and shots come from different sources after the shots fix)",
                "fbref_goals - fbref_penalty_goals > fbref_shots", KEY + ", fbref_goals, fbref_penalty_goals, fbref_shots"),
    where_check("np_goals_per90_matches_count", "warn", "non-penalty goals per 90 matches goals / nineties (5+ nineties)",
                "fbref_nineties >= 5 AND fbref_non_penalty_goals_per90 IS NOT NULL AND fbref_non_penalty_goals IS NOT NULL "
                "AND ABS(fbref_non_penalty_goals_per90 - fbref_non_penalty_goals / fbref_nineties) > 0.03",
                KEY + ", fbref_nineties, fbref_non_penalty_goals, fbref_non_penalty_goals_per90"),
    # ----- WhoScored: a part never exceeds the whole -----
    where_check("ws_passes_completed_le_passes", "error", "completed passes cannot exceed passes",
                "ws_passes_completed > ws_passes", KEY + ", ws_passes, ws_passes_completed"),
    where_check("ws_take_ons_won_le_take_ons", "error", "take-ons won cannot exceed take-ons",
                "ws_take_ons_won > ws_take_ons", KEY + ", ws_take_ons, ws_take_ons_won"),
    where_check("ws_tackles_won_le_tackles", "error", "tackles won cannot exceed tackles",
                "ws_tackles_won > ws_tackles", KEY + ", ws_tackles, ws_tackles_won"),
    where_check("ws_aerials_won_le_aerials", "error", "aerials won cannot exceed aerials",
                "ws_aerials_won > ws_aerials", KEY + ", ws_aerials, ws_aerials_won"),
    where_check("ws_touch_zones_sum", "error", "defensive + middle + attacking third touches add up to touches",
                "ws_touches_def_3rd IS NOT NULL AND ws_touches_mid_3rd IS NOT NULL AND ws_touches_att_3rd IS NOT NULL "
                "AND ws_touches IS NOT NULL AND ABS(ws_touches_def_3rd + ws_touches_mid_3rd + ws_touches_att_3rd - ws_touches) "
                "> GREATEST(2, 0.02 * ws_touches)",
                KEY + ", ws_touches, ws_touches_def_3rd, ws_touches_mid_3rd, ws_touches_att_3rd"),
    where_check("ws_penalty_area_touches_le_touches", "error", "penalty-area touches cannot exceed touches",
                "ws_touches_def_pen_area + ws_touches_att_pen_area > ws_touches",
                KEY + ", ws_touches, ws_touches_def_pen_area, ws_touches_att_pen_area"),
    where_check("ws_tackle_zones_le_tackles", "error", "tackles by zone cannot exceed tackles",
                "ws_tackles_def_3rd + ws_tackles_mid_3rd + ws_tackles_att_3rd > ws_tackles",
                KEY + ", ws_tackles, ws_tackles_def_3rd, ws_tackles_mid_3rd, ws_tackles_att_3rd"),
    where_check("ws_interception_zones_le_interceptions", "error", "interceptions by zone cannot exceed interceptions",
                "ws_interceptions_def_3rd + ws_interceptions_mid_3rd + ws_interceptions_att_3rd > ws_interceptions",
                KEY + ", ws_interceptions, ws_interceptions_def_3rd, ws_interceptions_mid_3rd, ws_interceptions_att_3rd"),
    where_check("ws_passes_pct_matches_counts", "error", "pass completion % matches completed / passes",
                "ws_passes > 0 AND ws_passes_pct IS NOT NULL AND ABS(ws_passes_pct - 100.0 * ws_passes_completed / ws_passes) > 0.2",
                KEY + ", ws_passes, ws_passes_completed, ws_passes_pct"),
    where_check("ws_take_ons_pct_matches_counts", "error", "take-on success % matches won / take-ons",
                "ws_take_ons > 0 AND ws_take_ons_won_pct IS NOT NULL AND ABS(ws_take_ons_won_pct - 100.0 * ws_take_ons_won / ws_take_ons) > 0.2",
                KEY + ", ws_take_ons, ws_take_ons_won, ws_take_ons_won_pct"),
    where_check("ws_aerial_pct_matches_counts", "error", "aerial win % matches won / aerials",
                "ws_aerials > 0 AND ws_aerial_duel_win_pct IS NOT NULL AND ABS(ws_aerial_duel_win_pct - 100.0 * ws_aerials_won / ws_aerials) > 0.2",
                KEY + ", ws_aerials, ws_aerials_won, ws_aerial_duel_win_pct"),
    where_check("ws_per90_sign_consistent", "error", "a per-90 rate is zero exactly when its count is zero",
                " OR ".join(f"(({c} = 0 AND {r} > 0) OR ({c} > 0 AND {r} = 0))" for c, r in PER90_PAIRS)),
    where_check("ws_matches_le_fbref_matches", "warn", "WhoScored matches with data should not exceed FBref matches played by more than 2 (a wrong player link shows here; "
                "also fires when WhoScored counts matches outside the league, such as play-offs)",
                "ws_matches_with_data > fbref_matches_played + 2", KEY + ", ws_matches_with_data, fbref_matches_played"),
    # ----- goalkeepers -----
    where_check("gk_saves_le_shots_faced", "error", "saves cannot exceed shots on target against",
                "gk_saves > gk_shots_on_target_against", KEY + ", gk_saves, gk_shots_on_target_against"),
    where_check("gk_clean_sheets_le_matches", "error", "clean sheets cannot exceed matches played",
                "gk_clean_sheets > fbref_matches_played", KEY + ", gk_clean_sheets, fbref_matches_played"),
    where_check("gk_results_le_matches", "error", "wins + draws + losses cannot exceed matches played",
                "gk_wins + gk_draws + gk_losses > fbref_matches_played", KEY + ", gk_wins, gk_draws, gk_losses, fbref_matches_played"),
    where_check("gk_penalties_saved_le_faced", "error", "penalties saved cannot exceed penalties faced",
                "gk_penalty_kicks_saved > gk_penalty_kicks_faced", KEY + ", gk_penalty_kicks_saved, gk_penalty_kicks_faced"),
    where_check("outfielders_with_keeper_stats", "warn", "keeper stats should sit on goalkeepers (an outfielder in goal for a match is real, a pattern is a bad link)",
                "split_part(fbref_position, ',', 1) <> 'GK' AND fbref_position <> '' AND gk_goals_against IS NOT NULL",
                KEY + ", fbref_position, gk_goals_against"),
    # ----- bio -----
    where_check("height_range", "error", "height between 150 and 215 cm",
                "tm_height_cm IS NOT NULL AND (tm_height_cm < 150 OR tm_height_cm > 215)", KEY + ", tm_height_cm",
                allowed=2, note="two known rows with height 875 (player_ids 101810, 128168), to be fixed at the source"),
    # ----- downstream tables -----
    Check("percentile_columns_in_range", "error", "every style percentile is between 0 and 100", "player_season_style_percentiles",
          percentile_range_sql),
    Check("percentiles_unique_key", "error", "one percentile row per player and season", "player_season_style_percentiles",
          "SELECT player_id, season_id, COUNT(*) AS n FROM player_season_style_percentiles GROUP BY 1, 2 HAVING COUNT(*) > 1"),
    Check("percentiles_have_stats", "error", "every percentile row comes from a stats row", "player_season_style_percentiles",
          f"SELECT p.player_id, p.season_id FROM player_season_style_percentiles p "
          f"WHERE NOT EXISTS (SELECT 1 FROM {M} m WHERE m.player_id = p.player_id AND m.season_id = p.season_id)"),
    Check("archetypes_have_percentiles", "error", "every archetype row comes from a percentile row", "player_season_archetypes",
          "SELECT a.player_id, a.season_id FROM player_season_archetypes a "
          "WHERE NOT EXISTS (SELECT 1 FROM player_season_style_percentiles p WHERE p.player_id = a.player_id AND p.season_id = a.season_id)"),
    Check("centroids_complete", "error", "every archetype has one centroid value per clustering feature (23)", "archetype_centroids",
          "SELECT archetype_id, COUNT(*) AS features FROM archetype_centroids GROUP BY 1 HAVING COUNT(*) <> 23"),
    Check("transfer_fee_range", "error", "transfer fees between 0 and 150 (millions of euros)", "eredivisie_transfers",
          "SELECT transfer_id, player_name, season_id, fee_amount FROM eredivisie_transfers "
          "WHERE fee_amount IS NOT NULL AND (fee_amount < 0 OR fee_amount > 150)"),
    Check("transfer_season_range", "error", "transfer seasons between 1990 and 2027", "eredivisie_transfers",
          "SELECT transfer_id, player_name, season_id FROM eredivisie_transfers "
          "WHERE season_id IS NOT NULL AND season_id NOT BETWEEN 1990 AND 2027"),
]
CHECK_NAMES = [c.name for c in CHECKS]


def table_exists(conn, table):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
        return cur.fetchone()[0]


def resolve_sql(check, conn):
    return check.rows_sql(conn) if callable(check.rows_sql) else check.rows_sql


def run_check(conn, check, samples=5):
    """Return a result dict: status in PASS / KNOWN / FAIL / WARN / SKIPPED / ERROR."""
    res = _run_check(conn, check, samples)
    res.update(description=check.description, allowed=check.allowed, note=check.note)
    return res


def _run_check(conn, check, samples=5):
    if not table_exists(conn, check.table):
        return {"name": check.name, "severity": check.severity, "status": "SKIPPED", "violations": None,
                "sample": [], "columns": [], "detail": f"table {check.table} does not exist"}
    try:
        sql = resolve_sql(check, conn)
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM ({sql}) v")
            n = cur.fetchone()[0]
            sample, cols = [], []
            if n > check.allowed:
                cur.execute(f"SELECT * FROM ({sql}) v LIMIT %s", (samples,))
                cols = [d[0] for d in cur.description]
                sample = cur.fetchall()
    except Exception as e:                     # a broken check must never read as a pass
        conn.rollback()
        return {"name": check.name, "severity": check.severity, "status": "ERROR", "violations": None,
                "sample": [], "columns": [], "detail": f"{type(e).__name__}: {str(e).strip().splitlines()[0]}"}
    if n == 0:
        status = "PASS"
    elif n <= check.allowed:
        status = "KNOWN"
    else:
        status = "FAIL" if check.severity == "error" else "WARN"
    return {"name": check.name, "severity": check.severity, "status": status, "violations": n,
            "sample": sample, "columns": cols, "detail": ""}


def run_all(conn, only=None, samples=5):
    checks = [c for c in CHECKS if not only or c.name in only]
    return [run_check(conn, c, samples) for c in checks]


def exit_code(results):
    return 1 if any(r["status"] in ("FAIL", "ERROR") for r in results) else 0


def format_report(results):
    lines = [f"{'status':<8} {'severity':<8} {'violations':>10}  check"]
    for r in results:
        v = "" if r["violations"] is None else str(r["violations"])
        lines.append(f"{r['status']:<8} {r['severity']:<8} {v:>10}  {r['name']}")
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines.append("")
    lines.append("Summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for r in results:
        if r["status"] in ("FAIL", "WARN", "ERROR", "SKIPPED"):
            lines.append(f"\n[{r['status']}] {r['name']}: {r['description']}")
            if r["detail"]:
                lines.append(f"  {r['detail']}")
            if r["allowed"]:
                lines.append(f"  allowed {r['allowed']} known violation(s): {r['note']}")
            if r["sample"]:
                lines.append("  " + " | ".join(r["columns"]))
                for row in r["sample"]:
                    lines.append("  " + " | ".join(str(x) for x in row))
    if any(r["status"] == "SKIPPED" for r in results):
        lines.append("\nNOTE: skipped checks are NOT passes; their tables do not exist yet.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--only", nargs="+", default=None)
    args = ap.parse_args(argv)
    unknown = set(args.only or []) - set(CHECK_NAMES)
    if unknown:
        sys.exit(f"unknown check name(s): {sorted(unknown)}")
    sys.path.insert(0, "pipelines/modeling")
    from build_style_percentiles import get_connection
    conn = get_connection()
    try:
        results = run_all(conn, args.only, args.samples)
    finally:
        conn.close()
    print(format_report(results))
    sys.exit(exit_code(results))


if __name__ == "__main__":
    main()
