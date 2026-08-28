"""
Exploration script: pulls team-season stats across every FBref stat category
soccerdata exposes, for Eredivisie 2026-27. Prints columns + a sample row for
each so we can see real field names before designing the Postgres schema.

Also flags, per stat_type, whether expected-goals-family columns (xG/npxG/xA)
are present -- useful now since we already know these aren't backfilled to
FBref's earliest seasons, so future multi-year pulls need to expect NULLs
before whatever season they were introduced (StatsBomb-sourced, ~2017-18
for most leagues -- worth reconfirming the Eredivisie-specific cutoff
directly once we're pulling historical seasons, since it can vary by league).
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
        print(f"stat_type = '{stat_type}'")
        print("=" * 60)
        try:
            df = fbref.read_team_season_stats(stat_type=stat_type)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            continue

        print(f"  Shape: {df.shape}")

        # Flatten multi-level columns if present, for readable printing
        if isinstance(df.columns, type(df.columns)) and df.columns.nlevels > 1:
            flat_cols = ["_".join([str(x) for x in col if x]) for col in df.columns]
        else:
            flat_cols = df.columns.tolist()

        print(f"  Columns ({len(flat_cols)}): {flat_cols}")

        xg_related = [c for c in flat_cols if any(k in c.lower() for k in XG_FAMILY_KEYWORDS)]
        if xg_related:
            print(f"  Expected-goals-family columns found: {xg_related}")
        else:
            print("  No expected-goals-family columns in this stat_type.")

        if not df.empty:
            print(f"  Sample row:\n{df.head(1)}")


if __name__ == "__main__":
    main()
