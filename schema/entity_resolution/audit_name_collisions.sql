-- audit_name_collisions.sql
-- Scans for other canonical players potentially affected by the same
-- bug that caused the Marcus Pedersen merge: load_exact_matches()'s
-- dedup-by-name-string can't tell "one real person across many
-- seasons" apart from "two different real people who happen to share
-- a name." Two independent checks, since each catches a different
-- flavor of the same underlying problem -- run both.
--
-- Already-resolved players (canonical_born or
-- canonical_whoscored_player_id already set) will still surface here,
-- since the underlying name-string ambiguity in the raw source data
-- never goes away -- only the VIEW's join is fixed for those. Use the
-- canonical_born / canonical_whoscored_player_id columns in the
-- output to tell "already fixed" apart from "needs the same
-- treatment."

UPDATE eredivisie_soccerdata_player_season_stats
SET born = 1990
WHERE player_name = 'Ricardo Ippel';

-- CHECK 1 (FBref side): any crosswalk entry whose source_name matches
-- MULTIPLE DISTINCT birth years in the raw FBref data is almost
-- certainly two different real people -- a single real person cannot
-- have two different birth years. High-confidence signal wherever
-- born is populated; cannot catch a collision where born is missing
-- for the differing rows.
SELECT
    psc.player_id,
    psc.source_name,
    COUNT(DISTINCT s.born) AS distinct_born_years,
    array_agg(DISTINCT s.born ORDER BY s.born) AS born_years,
    p.canonical_born AS already_resolved_as
FROM player_source_crosswalk psc
JOIN players p ON p.player_id = psc.player_id
JOIN eredivisie_soccerdata_player_season_stats s
    ON psc.source = 'fbref' AND psc.source_name = s.player_name
WHERE s.born IS NOT NULL
GROUP BY psc.player_id, psc.source_name, p.canonical_born
HAVING COUNT(DISTINCT s.born) > 1
ORDER BY psc.player_id;

-- CHECK 2 (WhoScored side): same idea, using whoscored_player_id
-- (WhoScored's own native ID) as the disambiguator instead of birth
-- year, since WhoScored has no birth-year column at all. Any
-- crosswalk entry whose source_name matches multiple DISTINCT
-- whoscored_player_id values is almost certainly two different real
-- people, independent of whatever the FBref-side check finds.
SELECT
    psc.player_id,
    psc.source_name,
    COUNT(DISTINCT w.whoscored_player_id) AS distinct_whoscored_ids,
    array_agg(DISTINCT w.whoscored_player_id ORDER BY w.whoscored_player_id) AS whoscored_ids,
    p.canonical_whoscored_player_id AS already_resolved_as
FROM player_source_crosswalk psc
JOIN players p ON p.player_id = psc.player_id
JOIN eredivisie_whoscored_player_season_stats w
    ON psc.source = 'whoscored' AND psc.source_name = w.player_name
WHERE w.whoscored_player_id IS NOT NULL
GROUP BY psc.player_id, psc.source_name, p.canonical_whoscored_player_id
HAVING COUNT(DISTINCT w.whoscored_player_id) > 1
ORDER BY psc.player_id;

