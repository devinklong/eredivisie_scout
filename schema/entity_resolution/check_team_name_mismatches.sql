-- check_team_name_mismatches.sql
--
-- Audits team-name mismatches between eredivisie_soccerdata_player_season_stats
-- (FBref) and eredivisie_whoscored_player_season_stats (WhoScored) for the
-- 2016-17/2017-18 seasons, which used the fallback parser
-- (parse_raw_whoscored_events.py) instead of the standard soccerdata
-- extraction path. Found via fix_shots_with_whoscored_derivation.sql's
-- sanity check 3 turning up 129 rows with a confirmed player match but no
-- team match -- e.g. "Groningen" (FBref) vs "FC Groningen" (WhoScored).

--
-- Run in order -- query 3 is the most useful starting point.

-- 1. Full pairwise audit -- catches near-matches (substring pairs) like the
-- confirmed Groningen/FC Groningen case. May include some false-positive
-- substring matches between unrelated clubs -- eyeball the results.
SELECT DISTINCT ws.team AS whoscored_team, fbref.team AS fbref_team
FROM eredivisie_whoscored_player_season_stats ws
JOIN eredivisie_soccerdata_player_season_stats fbref
  ON fbref.season_id = ws.season_id
WHERE ws.season_id IN (2016, 2017)
  AND ws.team <> fbref.team
  AND (LOWER(ws.team) LIKE '%' || LOWER(fbref.team) || '%' OR LOWER(fbref.team) LIKE '%' || LOWER(ws.team) || '%');

-- 2. Side-by-side: every distinct team name in each table for those seasons.
-- Useful if a mismatch isn't a simple substring/prefix variant (e.g. an
-- abbreviation vs. a full name) and query 1 misses it.
SELECT DISTINCT team, 'fbref' AS source, season_id
FROM eredivisie_soccerdata_player_season_stats
WHERE season_id IN (2016, 2017)
UNION ALL
SELECT DISTINCT team, 'whoscored' AS source, season_id
FROM eredivisie_whoscored_player_season_stats
WHERE season_id IN (2016, 2017)
ORDER BY season_id, team;

-- 3. Targeted: team names present in one table but not the other for the
-- same season. Cleanest signal -- a genuinely matching name is excluded
-- entirely, leaving only the mismatched pairs to sort out manually.
SELECT team, season_id, 'whoscored only' AS note
FROM eredivisie_whoscored_player_season_stats
WHERE season_id IN (2016, 2017)
  AND team NOT IN (SELECT team FROM eredivisie_soccerdata_player_season_stats WHERE season_id IN (2016, 2017))

UNION ALL

SELECT team, season_id, 'fbref only' AS note
FROM eredivisie_soccerdata_player_season_stats
WHERE season_id IN (2016, 2017)
  AND team NOT IN (SELECT team FROM eredivisie_whoscored_player_season_stats WHERE season_id IN (2016, 2017))

ORDER BY season_id, team;

-- 4. VERIFICATION: applies the confirmed team-name mapping (7 pairs, found
-- via queries 1 and 3 across both 2016 and 2017) and re-checks for any
-- team names still unmatched between the two tables. Should return ZERO
-- rows if the mapping is complete -- this is the sweep to screenshot.
SELECT team, season_id, 'whoscored only' AS note
FROM (
    SELECT
        CASE team
            WHEN 'FC Groningen' THEN 'Groningen'
            WHEN 'FC Utrecht' THEN 'Utrecht'
            WHEN 'PEC Zwolle' THEN 'Zwolle'
            WHEN 'SC Heerenveen' THEN 'Heerenveen'
            WHEN 'Heracles' THEN 'Heracles Almelo'
            WHEN 'Roda' THEN 'Roda JC'
            WHEN 'Sparta Rotterdam' THEN 'Sparta R.'
            ELSE team
        END AS team,
        season_id
    FROM eredivisie_whoscored_player_season_stats
    WHERE season_id IN (2016, 2017)
) ws
WHERE ws.team NOT IN (SELECT team FROM eredivisie_soccerdata_player_season_stats WHERE season_id IN (2016, 2017))

UNION ALL

SELECT team, season_id, 'fbref only' AS note
FROM eredivisie_soccerdata_player_season_stats
WHERE season_id IN (2016, 2017)
  AND team NOT IN (
    SELECT
        CASE team
            WHEN 'FC Groningen' THEN 'Groningen'
            WHEN 'FC Utrecht' THEN 'Utrecht'
            WHEN 'PEC Zwolle' THEN 'Zwolle'
            WHEN 'SC Heerenveen' THEN 'Heerenveen'
            WHEN 'Heracles' THEN 'Heracles Almelo'
            WHEN 'Roda' THEN 'Roda JC'
            WHEN 'Sparta Rotterdam' THEN 'Sparta R.'
            ELSE team
        END
    FROM eredivisie_whoscored_player_season_stats
    WHERE season_id IN (2016, 2017)
  )

ORDER BY season_id, team;
