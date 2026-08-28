"""
Test script: confirms whether WhoScored actually has populated player-level
event data (shots, passes, touches with x/y coordinates) for a real
Eredivisie match -- as opposed to just the team-level schedule/box-score
data confirmed working yesterday.

Uses a real game_id pulled from yesterday's read_schedule() output
(Cambuur-Excelsior, 2026-08-07).
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)

    print(f"Attempting to read events for match_id={MATCH_ID}...")
    try:
        events = ws.read_events(match_id=MATCH_ID)
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return

    print(f"Success. Events shape: {events.shape}")

    if events.empty:
        print("Events DataFrame is EMPTY -- table/method works, but no "
              "real event data exists for this match.")
        return

    print(f"\nColumns: {events.columns.tolist()}")

    # Specifically check whether shot events with real coordinates exist --
    # this is the actual data needed to build an in-house xG model.
    if "is_shot" in events.columns:
        shots = events[events["is_shot"] == True]
        print(f"\nTotal shot events found: {len(shots)}")
        if not shots.empty:
            print("Sample shot event:")
            print(shots.iloc[0])
    else:
        print("\nNo 'is_shot' column found -- checking raw column list "
              "above for the real field names in this data.")


if __name__ == "__main__":
    main()
