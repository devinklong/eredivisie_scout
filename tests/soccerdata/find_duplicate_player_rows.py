"""
Diagnostic: re-fetches all 16 seasons (should read from soccerdata's
local cache, not re-scrape, given the same seasons were just pulled) and
checks each season's combined player DataFrame for duplicate
(team, player) index entries -- the exact collision that would trigger
eredivisie_player_season_stats' ON CONFLICT DO NOTHING and explain the
9231-vs-9229 discrepancy from the real load run (2026-08-30).
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"
SEASONS = [f"{y}-{str(y + 1)[-2:]}" for y in range(2010, 2026)]


def flatten_columns(df):
    df.columns = ["_".join([str(x) for x in col if x]) if isinstance(col, tuple) else col
                   for col in df.columns]
    return df


def main():
    total_combined_duplicates = 0

    for season in SEASONS:
        try:
            fbref = sd.FBref(LEAGUE, season)
            standard = flatten_columns(fbref.read_player_season_stats(stat_type="standard"))
            shooting = flatten_columns(fbref.read_player_season_stats(stat_type="shooting"))
            playing_time = flatten_columns(fbref.read_player_season_stats(stat_type="playing_time"))
            misc = flatten_columns(fbref.read_player_season_stats(stat_type="misc"))
        except Exception as e:
            print(f"{season}: FAILED -- {type(e).__name__}: {e}")
            continue

        # Check each individual category's own index.
        for label, df in [("standard", standard), ("shooting", shooting),
                           ("playing_time", playing_time), ("misc", misc)]:
            dupes = df.index[df.index.duplicated(keep=False)]
            if len(dupes) > 0:
                print(f"\n{season} [{label}]: {len(dupes)} duplicate index rows:")
                for d in dupes:
                    print(f"  {d}")

        # Check the actual combined/joined result -- this is what
        # build_player_rows() iterates over in the real load script.
        combined = standard.join(
            shooting, how="outer", lsuffix="_std", rsuffix="_sht"
        ).join(
            playing_time, how="outer", rsuffix="_pt"
        ).join(
            misc, how="outer", rsuffix="_misc"
        )
        combined_dupes = combined.index[combined.index.duplicated(keep=False)]
        if len(combined_dupes) > 0:
            print(f"\n{season} [COMBINED]: {len(combined_dupes)} duplicate index rows "
                  f"(this is the real cause -- these produce 2 output rows with the "
                  f"same player_name/team/season_id):")
            for d in combined_dupes:
                print(f"  {d}")
            total_combined_duplicates += len(combined_dupes)

    print(f"\nTotal duplicate index entries in COMBINED data across all seasons: "
          f"{total_combined_duplicates}")


if __name__ == "__main__":
    main()
