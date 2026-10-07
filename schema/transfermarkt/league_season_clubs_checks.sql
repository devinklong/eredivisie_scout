-- league_season_clubs_checks.sql
-- Run AFTER load_league_season_clubs.py. Read-only. Each check says what good
-- and bad look like.

-- 1. Every one of the 80 league-seasons (5 leagues x 2010-2025) has exactly the
--    right number of clubs: 20, or 18 for the Bundesliga and for Ligue 1 from
--    2023. Returns the league-seasons that are WRONG or MISSING. MUST return
--    zero rows. A missing league-season shows up here with clubs = 0.
WITH expected AS (
    SELECT l.league_code, s.season_id,
           CASE WHEN l.league_code = 'L1' THEN 18
                WHEN l.league_code = 'FR1' AND s.season_id >= 2023 THEN 18
                ELSE 20 END AS expected_clubs
    FROM (VALUES ('GB1'), ('ES1'), ('IT1'), ('L1'), ('FR1')) AS l(league_code)
    CROSS JOIN generate_series(2010, 2025) AS s(season_id)
),
actual AS (
    SELECT league_code, season_id, COUNT(*) AS clubs
    FROM league_season_clubs GROUP BY league_code, season_id
)
SELECT e.league_code, e.season_id, e.expected_clubs, COALESCE(a.clubs, 0) AS clubs
FROM expected e
LEFT JOIN actual a USING (league_code, season_id)
WHERE COALESCE(a.clubs, 0) <> e.expected_clubs
ORDER BY e.league_code, e.season_id;

-- 1b. What check 1 covered. Expect 80 league-seasons. Zero rows from check 1
--     means nothing unless this shows the table is actually populated.
SELECT COUNT(DISTINCT (league_code, season_id)) AS league_seasons,
       COUNT(*) AS club_rows,
       COUNT(DISTINCT club_id) AS distinct_clubs
FROM league_season_clubs;

-- 2. Season-to-season continuity. A season parameter that silently failed would
--    return the same table for different seasons. Real leagues always change
--    some members each year (promotion and relegation), so a league-season
--    sharing ALL its clubs with the season before has not changed, and one that
--    replaced most of them is implausible. new_clubs is how many clubs were
--    not in that league the season before. The 1 to 6 window is a heuristic,
--    not a rule: a row here is something to look at. MUST return zero rows.
WITH sizes AS (
    SELECT league_code, season_id, COUNT(*) AS clubs
    FROM league_season_clubs GROUP BY league_code, season_id
),
retained AS (
    SELECT c.league_code, c.season_id, COUNT(p.club_id) AS retained
    FROM league_season_clubs c
    LEFT JOIN league_season_clubs p
           ON p.league_code = c.league_code AND p.club_id = c.club_id AND p.season_id = c.season_id - 1
    WHERE c.season_id > 2010
    GROUP BY c.league_code, c.season_id
)
SELECT r.league_code, r.season_id, s.clubs, r.retained, s.clubs - r.retained AS new_clubs
FROM retained r
JOIN sizes s USING (league_code, season_id)
WHERE s.clubs - r.retained NOT BETWEEN 1 AND 6
ORDER BY r.league_code, r.season_id;

-- 3. Human check, not pass/fail. For each of the 69 buyer clubs, how many
--    seasons it spent in each Big-5 league. Eyeball a few you know: Sunderland
--    in the Premier League for 2010 to 2016 and then out, Juventus in Serie A
--    for all 16 seasons, Man Utd in the Premier League for all 16. A buyer club
--    that appears for none of the five leagues is read as 'other' by the model.
SELECT b.own_club_name, l.league_code,
       COUNT(*) AS seasons, MIN(l.season_id) AS first_season, MAX(l.season_id) AS last_season
FROM (SELECT DISTINCT own_club_id, own_club_name FROM buyer_club_transfers) b
JOIN league_season_clubs l ON l.club_id = b.own_club_id
GROUP BY b.own_club_name, l.league_code
ORDER BY b.own_club_name, l.league_code;
