-- compare_fbref_whoscored_defensive_stats.sql
-- Checks how much FBref's tackles_won/interceptions (Opta-sourced,
-- undocumented methodology) actually agree with WhoScored's own
-- versions (this project's own derive_defense_stats.py, fully
-- documented in docs/whoscored_qualifier_taxonomy.md) -- run BEFORE
-- deciding whether to drop one, average them, or keep both as
-- separate model features. Only compares rows where BOTH sources have
-- real data for the same player-team-season (excludes pre-2013-14
-- seasons entirely, since WhoScored has nothing there at all).

-- Overall agreement summary
SELECT
    COUNT(*) AS rows_with_both_sources,

    ROUND(AVG(fbref_tackles_won - ws_tackles_won), 2) AS avg_diff_tackles_won,
    ROUND(AVG(ABS(fbref_tackles_won - ws_tackles_won)), 2) AS avg_abs_diff_tackles_won,
    ROUND(CORR(fbref_tackles_won, ws_tackles_won)::numeric, 3) AS correlation_tackles_won,
    COUNT(*) FILTER (WHERE fbref_tackles_won = ws_tackles_won) AS exact_match_tackles_won,

    ROUND(AVG(fbref_interceptions - ws_interceptions), 2) AS avg_diff_interceptions,
    ROUND(AVG(ABS(fbref_interceptions - ws_interceptions)), 2) AS avg_abs_diff_interceptions,
    ROUND(CORR(fbref_interceptions, ws_interceptions)::numeric, 3) AS correlation_interceptions,
    COUNT(*) FILTER (WHERE fbref_interceptions = ws_interceptions) AS exact_match_interceptions

FROM master_player_season_stats
WHERE fbref_tackles_won IS NOT NULL AND ws_tackles_won IS NOT NULL
  AND fbref_interceptions IS NOT NULL AND ws_interceptions IS NOT NULL;

-- Distribution of how far apart they are, for tackles_won -- gives a
-- sense of whether disagreement is small/systematic (e.g. always off
-- by 1-2, maybe a definitional difference) or large/random (the two
-- sources aren't really measuring the same thing at all).
SELECT
    ABS(fbref_tackles_won - ws_tackles_won) AS abs_diff,
    COUNT(*) AS num_rows
FROM master_player_season_stats
WHERE fbref_tackles_won IS NOT NULL AND ws_tackles_won IS NOT NULL
GROUP BY abs_diff
ORDER BY abs_diff;

-- Same distribution for interceptions
SELECT
    ABS(fbref_interceptions - ws_interceptions) AS abs_diff,
    COUNT(*) AS num_rows
FROM master_player_season_stats
WHERE fbref_interceptions IS NOT NULL AND ws_interceptions IS NOT NULL
GROUP BY abs_diff
ORDER BY abs_diff;

-- Worst individual disagreements worth eyeballing by hand -- if these
-- look like genuinely different real events being counted (not just
-- rounding/edge-case differences), that's evidence the two sources
-- aren't interchangeable.
SELECT canonical_name, team, season_id,
       fbref_tackles_won, ws_tackles_won,
       ABS(fbref_tackles_won - ws_tackles_won) AS abs_diff
FROM master_player_season_stats
WHERE fbref_tackles_won IS NOT NULL AND ws_tackles_won IS NOT NULL
ORDER BY abs_diff DESC
LIMIT 15;
