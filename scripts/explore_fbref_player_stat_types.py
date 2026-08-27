"""
Follow-up exploration: read_team_season_stats() only supports 5 stat_types
(standard, keeper, shooting, playing_time, misc) -- passing, possession,
defense, and goal/shot creation aren't available through that method.
Checking whether read_player_season_stats() exposes a broader set, since
FBref's site structure puts those categories primarily at the player level.

Also checking whether xG/xA columns show up here, and whether the early-season
all-NA-column-drop (flagged by the pandas FutureWarning in the last run) is
the reason they were missing from every team-season pull.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASON = "2026-27"

STAT_TYPES = [
    "standard",
    "shooting",
    "passing",
    "passing_types",
    "goal_shot_creation",
    "defense",
    "possession",
    "playing_time",
    "misc",
    "keeper",
    "keeper_adv",
]

XG_FAMILY_KEYWORDS = ["xg", "npxg", "xa"]


def main():
    fbref = sd.FBref(LEAGUE, SEASON)

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

        if df.columns.nlevels > 1:
            flat_cols = ["_".join([str(x) for x in col if x]) for col in df.columns]
        else:
            flat_cols = df.columns.tolist()

        print(f"  Columns ({len(flat_cols)}): {flat_cols}")

        xg_related = [c for c in flat_cols if any(k in c.lower() for k in XG_FAMILY_KEYWORDS)]
        if xg_related:
            print(f"  Expected-goals-family columns found: {xg_related}")
        else:
            print("  No expected-goals-family columns in this stat_type.")


if __name__ == "__main__":
    main()
