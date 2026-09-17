"""
Checks whether BlockedPass events attribute the blocking player
anywhere -- via related_player_id or a qualifier -- per
whoscored_qualifier_taxonomy.md's "Still unmapped / not yet checked"
note: "flagged as unconfirmed in derive_defense_stats.py's docstring,
not yet resolved."

Uses the same match/fallback pattern as the other one-off qualifier
checks in this project.
"""

import pandas as pd
import soccerdata as sd

from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07 -- same match used for the rest of the qualifier taxonomy


def get_events_with_fallback(ws, league, season, match_id):
    try:
        return ws.read_events(match_id=match_id, force_cache=True)
    except TypeError as e:
        if "cannot safely cast non-equivalent object to int64" not in str(e):
            raise
        return get_events_raw_fallback(league, season, match_id)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = get_events_with_fallback(ws, LEAGUE, SEASON, MATCH_ID)

    blocked_passes = events[events["type"] == "BlockedPass"]
    print(f"Found {len(blocked_passes)} BlockedPass events in this match.\n")

    related_populated = blocked_passes["related_player_id"].notna().sum()
    print(f"related_player_id populated on {related_populated}/{len(blocked_passes)} events.\n")

    print("--- Sample rows ---")
    for idx, row in blocked_passes.head(10).iterrows():
        print(f"Player: {row.get('player', '?')}, team: {row.get('team', '?')}, "
              f"minute: {row.get('minute', '?')}")
        print(f"  related_player_id: {row.get('related_player_id', '?')}")
        print(f"  Raw qualifiers: {row.get('qualifiers', '?')}")
        print()

    print("If related_player_id or a qualifier consistently identifies a second, "
          "different player (the blocker), attribution is possible. If both are "
          "empty/NULL across the sample, confirms the doc's 'not yet resolved' note.")

    # Every sampled BlockedPass event carries an OppositeRelatedEvent qualifier
    # with a numeric value -- likely an event id pointing to the original Pass
    # event that got blocked, which would carry the ATTACKING player (distinct
    # from the defender named on the BlockedPass row itself). Check directly.
    print("\n--- Checking OppositeRelatedEvent qualifier as a cross-reference ---")
    print(f"events columns: {events.columns.tolist()}\n")

    id_col = None
    for candidate in ("id", "event_id", "eventId"):
        if candidate in events.columns:
            id_col = candidate
            break

    if id_col is None:
        print("No obvious event-id column found (checked id/event_id/eventId) -- "
              "inspect events.columns above and adjust id_col manually.")
        return

    print(f"Using '{id_col}' as the event-id column.\n")

    # The OppositeRelatedEvent lookup gave mixed results (4/7 looked right --
    # opposing team, same minute, type=Pass -- but 3/7 were wrong: same team,
    # minutes off, wrong event type, one even pointing back to the SAME
    # player as the blocker). A plain int lookup being sometimes right and
    # sometimes wrong usually means the key isn't unique. Check that first.
    print("--- Checking whether event_id is actually unique in this match ---")
    dupe_counts = events[id_col].value_counts()
    dupes = dupe_counts[dupe_counts > 1]
    print(f"{len(dupes)} duplicate {id_col} value(s) out of {len(events)} events.")
    if len(dupes) > 0:
        print("Sample duplicate ids and their rows:")
        for dup_id in dupes.index[:5]:
            dup_rows = events[events[id_col] == dup_id]
            print(f"\n  {id_col}={dup_id}:")
            print(dup_rows[["period", "minute", "type", "player", "team"]].to_string(index=False))
    print()

    for idx, row in blocked_passes.iterrows():
        qualifiers = row.get("qualifiers")
        related_event_id = None
        if isinstance(qualifiers, list):
            for q in qualifiers:
                if q.get("type", {}).get("displayName") == "OppositeRelatedEvent":
                    related_event_id = q.get("value")
                    break

        if related_event_id is None:
            continue

        match = events[events[id_col] == int(related_event_id)]
        print(f"BlockedPass by {row.get('player', '?')} ({row.get('team', '?')}, "
              f"min {row.get('minute', '?')}) -> OppositeRelatedEvent id={related_event_id}")
        if len(match) == 0:
            print(f"  No event found with {id_col}={related_event_id}")
        else:
            m = match.iloc[0]
            print(f"  -> type={m.get('type', '?')}, player={m.get('player', '?')}, "
                  f"team={m.get('team', '?')}, minute={m.get('minute', '?')}")
        print()

    # The events table also has a dedicated related_event_id column, separate
    # from anything parsed out of qualifiers. The OppositeRelatedEvent-based
    # lookup above gave inconsistent results (4/7 looked correct -- opposing
    # team, same minute, type=Pass -- but 3/7 were clearly wrong: same team as
    # the blocker, several minutes off, wrong event type). Check whether
    # related_event_id is the more reliable field instead.
    print("\n--- Cross-check against the dedicated related_event_id column ---\n")
    for idx, row in blocked_passes.iterrows():
        rel_id = row.get("related_event_id")
        print(f"BlockedPass by {row.get('player', '?')} ({row.get('team', '?')}, "
              f"min {row.get('minute', '?')}) -> related_event_id={rel_id}")
        if pd.isna(rel_id):
            print("  related_event_id is NaN/empty")
        else:
            match = events[events[id_col] == int(rel_id)]
            if len(match) == 0:
                print(f"  No event found with {id_col}={rel_id}")
            else:
                m = match.iloc[0]
                print(f"  -> type={m.get('type', '?')}, player={m.get('player', '?')}, "
                      f"team={m.get('team', '?')}, minute={m.get('minute', '?')}")
        print()


if __name__ == "__main__":
    main()
