"""
Lightweight converter: turns WhoScored's raw event JSON (output_fmt="raw",
confirmed working for older seasons where soccerdata's own "events"
format crashes with 'TypeError: cannot safely cast non-equivalent object
to int64') into a DataFrame matching the column names/shapes the
existing derive_*.py functions expect -- WITHOUT soccerdata's fragile
strict Int64 casting step.

Deliberately does NOT try to replicate every column soccerdata's normal
"events" output has (goal_mouth_y/z, blocked_x/y, card_type, etc.) --
only what the four derive_*.py functions actually use: type, outcome_type,
player, team, x, y, end_x, end_y, is_touch, qualifiers. Add more columns
here later if a derive function needs one this doesn't provide.
"""

import pandas as pd
import soccerdata as sd

LEAGUE = "NED-Eredivisie"

# WhoScored raw JSON key -> the column name derive_*.py functions expect
RENAME_MAP = {
    "type": "type",  # raw 'type' is a dict like {'displayName': 'Pass', ...} -- extracted below
    "outcomeType": "outcome_type",  # same, dict -- extracted below
    "playerId": "player_id",
    "teamId": "team_id",
    "x": "x",
    "y": "y",
    "endX": "end_x",
    "endY": "end_y",
    "isTouch": "is_touch",
    "isGoal": "is_goal",
    "isShot": "is_shot",
    "qualifiers": "qualifiers",
    "minute": "minute",
    "second": "second",
}


def parse_raw_events(raw_event_list, player_names=None, team_names=None):
    """Converts a raw WhoScored event list (from output_fmt='raw') into
    a DataFrame shaped like soccerdata's normal 'events' output, minus
    the strict Int64 casting that breaks on older seasons."""
    rows = []
    for e in raw_event_list:
        row = {}
        for raw_key, out_key in RENAME_MAP.items():
            value = e.get(raw_key)
            # 'type' and 'outcomeType' are nested dicts with a
            # displayName -- same unwrapping soccerdata's normal
            # pipeline does, just done manually here.
            if raw_key in ("type", "outcomeType") and isinstance(value, dict):
                value = value.get("displayName")
            row[out_key] = value
        rows.append(row)

    df = pd.DataFrame(rows)

    # player/team name lookups, if provided (mirrors soccerdata's own
    # player_names/team_names dict substitution) -- optional, only
    # needed if player_id -> real name mapping isn't already present.
    if player_names and "player_id" in df.columns:
        df["player"] = df["player_id"].map(player_names)
    if team_names and "team_id" in df.columns:
        df["team"] = df["team_id"].map(team_names)

    return df


def season_to_compact_code(season):
    """'2015-16' -> '1516' -- soccerdata's cache folders use this compact
    numeric code, not the human-readable season string. Confirmed via
    tests/whoscored/check_cache_file_path.py: the real cache path was
    events/NED-Eredivisie_1516/956891.json, not
    events/NED-Eredivisie_2015-16/956891.json."""
    start, end = season.split("-")
    return start[-2:] + end


def get_events_for_match(league, season, match_id):
    """Fetches one match's raw events and returns the parsed DataFrame,
    plus the player/team name dictionaries needed to resolve IDs to
    names (soccerdata's raw output doesn't include names directly --
    they come from separate dicts in the same JSON response)."""
    ws = sd.WhoScored(league, season)
    raw = ws.read_events(match_id=match_id, force_cache=True, output_fmt="raw")

    if raw is None or match_id not in raw:
        return None

    # Re-fetch the same match's full JSON to get player/team name dicts
    # -- output_fmt="raw" only returns the events list itself, not the
    # surrounding playerIdNameDictionary/team info soccerdata's normal
    # path also extracts. Cheap since it's cached.
    import json
    season_code = season_to_compact_code(season)
    filepath = ws.data_dir / "events" / f"{league}_{season_code}" / f"{match_id}.json"
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            full_json = json.load(f)
        player_names = {int(k): v for k, v in full_json.get("playerIdNameDictionary", {}).items()}
        team_names = {
            int(full_json[side]["teamId"]): full_json[side]["name"]
            for side in ["home", "away"] if side in full_json
        }
    else:
        print(f"  WARNING: cache file not found at {filepath} -- "
              f"player/team names will be missing.")
        player_names, team_names = {}, {}

    return parse_raw_events(raw[match_id], player_names, team_names)


if __name__ == "__main__":
    # Quick test against one of the confirmed-real-data older matches.
    df = get_events_for_match(LEAGUE, "2015-16", 956891)
    if df is not None:
        print(f"Parsed {len(df)} events.")
        print(f"Columns: {df.columns.tolist()}")
        print(df.head(3))
    else:
        print("No data returned.")

def check_player_id_consistency(df):
    """Sanity check: confirms each player_id maps to exactly one player
    name within this match, and flags any player_id with no resolved
    name at all (a sign player_names lookup failed for that ID).

    This doesn't catch every possible error -- e.g. a genuinely wrong
    playerIdNameDictionary entry from WhoScored itself would still pass
    this check, since both player_id and player would agree with each
    other while both being wrong. It only catches the mechanical
    failure mode: player_id and player becoming inconsistent with each
    other during this script's own processing."""
    issues = []

    id_to_names = df.groupby("player_id")["player"].unique()
    for player_id, names in id_to_names.items():
        real_names = [n for n in names if pd.notna(n)]
        if len(set(real_names)) > 1:
            issues.append(
                f"player_id={player_id} maps to multiple names: {real_names}"
            )

    unresolved = df[df["player_id"].notna() & df["player"].isna()]
    if len(unresolved) > 0:
        unresolved_ids = unresolved["player_id"].unique().tolist()
        issues.append(
            f"{len(unresolved)} events have a player_id but no resolved "
            f"name -- unresolved player_ids: {unresolved_ids}"
        )

    if issues:
        print(f"\n  PLAYER_ID CONSISTENCY CHECK: {len(issues)} issue(s) found:")
        for issue in issues:
            print(f"    - {issue}")
    else:
        print(f"\n  PLAYER_ID CONSISTENCY CHECK: passed -- every player_id "
              f"maps to exactly one name, no unresolved IDs.")

    return issues


if __name__ == "__main__":
    # Quick test against one of the confirmed-real-data older matches.
    df = get_events_for_match(LEAGUE, "2015-16", 956891)
    if df is not None:
        print(f"Parsed {len(df)} events.")
        print(f"Columns: {df.columns.tolist()}")
        print(df.head(3))
        check_player_id_consistency(df)
    else:
        print("No data returned.")