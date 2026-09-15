"""
Validates derive_shots_stats.py's definition at SEASON scale, not just
one match -- sums shots/shots_on_target across every match in a known-
good season (2019-20, confirmed NOT affected by the 2016-17/2017-18
FBref gap) for every player, then prints the totals so they can be
compared directly against eredivisie_soccerdata_player_season_stats'
real, correct FBref numbers for the same players.

Reuses the same fallback pattern as scrape_all_whoscored_matches.py --
some matches hit the confirmed soccerdata casting bug regardless of
season.
"""

import soccerdata as sd
from collections import defaultdict

from derive_shots_stats import derive_shot_stats
from parse_raw_whoscored_events import get_events_for_match as get_events_raw_fallback

LEAGUE = "NED-Eredivisie"
SEASON = "2019-20"


def get_events_with_fallback(ws, league, season, match_id):
    try:
        return ws.read_events(match_id=match_id, force_cache=True), False
    except TypeError as e:
        if "cannot safely cast non-equivalent object to int64" not in str(e):
            raise
        return get_events_raw_fallback(league, season, match_id), True


def main():
    ws = sd.WhoScored(LEAGUE, SEASON)
    schedule = ws.read_schedule(force_cache=True)
    match_ids = schedule["game_id"].tolist()
    print(f"Validating across {len(match_ids)} matches in {SEASON}...")

    totals = defaultdict(lambda: defaultdict(int))
    used_fallback_count = 0
    failed = []

    for i, match_id in enumerate(match_ids, start=1):
        try:
            events, used_fallback = get_events_with_fallback(ws, LEAGUE, SEASON, match_id)
            if used_fallback:
                used_fallback_count += 1
            if events is None or len(events) == 0 or "type" not in events.columns:
                failed.append(match_id)
                continue

            match_shots = derive_shot_stats(events, verbose=False)
            for _, row in match_shots.iterrows():
                key = (row["player"], row["team"])
                totals[key]["shots"] += row["shots"]
                totals[key]["shots_on_target"] += row["shots_on_target"]
        except Exception as e:
            print(f"  match {match_id} FAILED: {type(e).__name__}: {e}")
            failed.append(match_id)

        if i % 25 == 0:
            print(f"  ...{i}/{len(match_ids)} matches processed")

    print(f"\nDone. {used_fallback_count} matches used the raw fallback parser, "
          f"{len(failed)} matches failed entirely.")

    print("\n--- Season shot totals (top 30 by shots) ---")
    sorted_totals = sorted(totals.items(), key=lambda kv: kv[1]["shots"], reverse=True)
    for (player, team), stats in sorted_totals[:30]:
        print(f"{player:25} {team:20} shots={stats['shots']:3}  "
              f"on_target={stats['shots_on_target']:3}")

    print("\nCross-check these against real FBref numbers via:")
    print("SELECT player_name, team, shots, shots_on_target FROM "
          "eredivisie_soccerdata_player_season_stats WHERE season_id = 2019 "
          "ORDER BY shots DESC LIMIT 30;")


if __name__ == "__main__":
    main()
