"""
Confirms (or refutes) the assumption flagged as unverified in
docs/whoscored_qualifier_taxonomy.md: that Aerial events carry their
own win/loss outcome directly on the same event type, unlike Challenge
(which is always a loss, with the win showing up as the opponent's
TakeOn instead -- a real, already-confirmed exception to the "same
event type has its own outcome" pattern).

Run this BEFORE writing derive_aerial_stats.py. Same test match used
throughout this project's other derive_*.py checks
(game_id=1982244, Cambuur-Excelsior).

What this checks:
1. What outcome_type values actually appear on real Aerial events --
   confirms whether there's a clean win/loss split at all (e.g.
   'Successful'/'Unsuccessful') or something else entirely.
2. Whether Aerial events come in pairs -- for a real aerial duel, two
   opposing players should have an Aerial event at (or very near) the
   same x/y/minute/second, one Successful and one Unsuccessful. If
   pairing doesn't hold up, that's a sign this isn't a clean
   self-contained duel record the way Tackle is.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, same test match as other derive_*.py checks


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID, force_cache=True)

    aerials = events[events["type"] == "Aerial"].copy()
    print(f"Total Aerial events found: {len(aerials)}")

    print("\n--- outcome_type value counts on Aerial events ---")
    print(aerials["outcome_type"].value_counts(dropna=False))

    print("\n--- Checking for paired aerials (opposing players, same moment) ---")
    paired = 0
    unpaired = 0
    checked = set()

    for idx, row in aerials.iterrows():
        if idx in checked:
            continue
        candidates = aerials[
            (aerials["minute"] == row["minute"])
            & (aerials["second"] == row["second"])
            & (aerials["team"] != row["team"])
            & (~aerials.index.isin(checked))
        ]
        if len(candidates) > 0:
            partner = candidates.iloc[0]
            checked.add(idx)
            checked.add(partner.name)
            paired += 1
            if paired <= 5:
                print(f"  Paired: {row['player']} ({row['team']}, {row['outcome_type']}) "
                      f"vs {partner['player']} ({partner['team']}, {partner['outcome_type']}) "
                      f"at {row['minute']}:{row['second']}")
        else:
            unpaired += 1

    print(f"\nTotal paired: {paired}, unpaired (no opposing-team match at same moment): {unpaired}")
    print("\nIf outcome_type cleanly splits into two values AND most events pair up with "
          "an opposing player showing the opposite outcome, Aerial safely carries its own "
          "win/loss outcome -- build derive_aerial_stats.py using outcome_type directly. "
          "If pairing mostly fails, this needs the same cross-referencing treatment as "
          "Challenge/TakeOn, not a simple outcome_type read.")


if __name__ == "__main__":
    main()
