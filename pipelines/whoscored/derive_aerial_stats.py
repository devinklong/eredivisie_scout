"""
Derives aerial duel stats (aerials, aerials_won, aerials_won_pct) from
WhoScored raw event data. Same match/pattern as the other derive_*.py
scripts (game_id=1982244, Cambuur-Excelsior).

CONFIRMED via check_aerial_outcome.py (2026-09-13), NOT assumed: Aerial
events carry their own win/loss outcome directly on the same event
type, same as Tackle -- unlike Challenge, which is always a loss with
the win showing up as the opponent's TakeOn instead (a real, already-
confirmed exception this project hit before). Real data: 56 Aerial
events, outcome_type split exactly 28 Successful / 28 Unsuccessful --
a clean 50/50 split, the expected signature of a properly paired
win/loss event type. This was flagged as unverified in
docs/whoscored_qualifier_taxonomy.md's cross-event relationships
table -- now confirmed, not assumed.

Includes player_id in the groupby, matching the convention already
applied to every other derive_*.py file in this project.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"
MATCH_ID = 1982244  # Cambuur-Excelsior, 2026-08-07


def derive_aerial_stats(events):
    """Aerial duels attempted/won, from the Aerial event type directly."""
    aerials = events[events["type"] == "Aerial"].copy()
    print(f"Total Aerial events found: {len(aerials)}")

    aerials["is_won"] = aerials["outcome_type"] == "Successful"

    grouped = aerials.groupby(["player", "team", "player_id"]).agg(
        aerials=("type", "count"),
        aerials_won=("is_won", "sum"),
    ).reset_index()
    grouped["aerials_won_pct"] = (
        (grouped["aerials_won"] / grouped["aerials"]) * 100
    ).round(1)
    return grouped.sort_values("aerials", ascending=False)


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    events = ws.read_events(match_id=MATCH_ID, force_cache=True)

    print("\n--- Aerial duels (top 10) ---")
    aerial_stats = derive_aerial_stats(events)
    print(aerial_stats.head(10))


if __name__ == "__main__":
    main()
