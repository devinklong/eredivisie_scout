"""
Checks whether fbrefdata (a fork of soccerdata focused solely on FBref)
covers the stat_type categories soccerdata is missing: passing,
passing_types, gca (goal/shot creation), possession, defense, keeper_adv.

fbrefdata explicitly lists Netherlands: Eredivisie as a supported league
and states its whole purpose is fixing soccerdata's limited advanced-stats
coverage -- this test confirms whether that holds in practice.

Requires: pip install fbrefdata
"""

import fbrefdata as fd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-2019"  # placeholder, corrected below

# fbrefdata's season format matches its own README example ('2018-2019'),
# not necessarily soccerdata's ('2026-27') -- try the current season in that
# longer format first.
SEASON = "2026-2027"

STAT_TYPES = [
    "standard",
    "shooting",
    "passing",
    "passing_types",
    "gca",
    "defense",
    "possession",
    "playing_time",
    "misc",
    "keeper",
    "keeper_adv",
]


def main():
    print(f"Creating FBref (fbrefdata) scraper for {LEAGUE}, {SEASON}...")
    try:
        fbref = fd.FBref(LEAGUE, SEASON)
    except Exception as e:
        print(f"Failed to create scraper instance: {type(e).__name__}: {e}")
        return

    for stat_type in STAT_TYPES:
        print(f"\n{'=' * 60}")
        print(f"read_player_season_stats(stat_type='{stat_type}')")
        print("=" * 60)
        try:
            df = fbref.read_player_season_stats(stat_type=stat_type)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            continue

        print(f"  Shape: {df.shape}")
        cols = df.columns.tolist()
        print(f"  Columns ({len(cols)}): {cols}")


if __name__ == "__main__":
    main()
