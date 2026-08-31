"""
Follow-up check: are Ricardo Ippel's (Willem II, 2014-15) and Bilal
Bayazit's (Vitesse, 2017-18) two duplicate playing_time rows truly
identical, or do they hold different stat values (e.g. two separate
stints within the same season)? Determines whether ON CONFLICT DO
NOTHING correctly deduplicated redundant data, or silently dropped real,
different information.
"""

import soccerdata as sd

LEAGUE = "NED-Eredivisie"


def flatten_columns(df):
    df.columns = ["_".join([str(x) for x in col if x]) if isinstance(col, tuple) else col
                   for col in df.columns]
    return df


def check(season, team, player):
    fbref = sd.FBref(LEAGUE, season)
    playing_time = flatten_columns(fbref.read_player_season_stats(stat_type="playing_time"))

    matches = playing_time[
        (playing_time.index.get_level_values("team") == team)
        & (playing_time.index.get_level_values("player") == player)
    ]

    print(f"\n{player} ({team}, {season}) -- {len(matches)} rows found:")
    print(matches)

    if len(matches) == 2:
        row1, row2 = matches.iloc[0], matches.iloc[1]
        identical = row1.equals(row2)
        print(f"\nAre the two rows identical? {identical}")
        if not identical:
            print("DIFFERENCES:")
            diff = row1.compare(row2)
            print(diff)


def main():
    check("2014-15", "Willem II", "Ricardo Ippel")
    check("2017-18", "Vitesse", "Bilal Bayazit")


if __name__ == "__main__":
    main()
