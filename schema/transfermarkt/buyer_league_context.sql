-- buyer_league_context.sql
-- For every paid transfer out of the Eredivisie, which league was the BUYING
-- club in that season, and in the season before? This is what lets the model
-- learn "Big-5 clubs pay X for archetype Y" instead of per-club facts.
--
-- Built on buyer_spend_context (so the grain is identical: one row per paid
-- Eredivisie sale) plus league_season_clubs (Big-5 membership by season) and
-- eredivisie_club_status (Eredivisie membership by season).
--
-- LEAGUE VALUES: 'GB1' Premier League, 'ES1' La Liga, 'IT1' Serie A, 'L1'
-- Bundesliga, 'FR1' Ligue 1, 'NL1' Eredivisie, 'OTHER' anything else (other
-- countries' top flights, lower divisions, a domestic buyer that was not in the
-- Eredivisie that season). NULL means unknown, never 'OTHER'.
--
-- THAT SEASON vs PREVIOUS SEASON: transfer_season is the season the transfer
-- belongs to (summer and winter windows together). A club promoted or relegated
-- the summer before signs as a club of the NEW league, but decided the signing
-- as a club of the OLD one, so both are given and the model can use either.
-- The previous-season columns are NULL for 2010, which has no season before it
-- in this data, rather than reading as 'OTHER'.
--
-- NO FAN-OUT BY CONSTRUCTION: league_season_clubs is UNIQUE (season_id, club_id)
-- and eredivisie_club_status is keyed on (club_id, season_id), so each join
-- below returns at most one row per sale. Check 1 still proves the grain, and
-- check 2 recomputes every value with a differently shaped query.
--
-- A buyer with no club id (none today) gets NULL, not 'OTHER'.

CREATE OR REPLACE VIEW buyer_league_context AS
SELECT s.transfer_id, s.player_id, s.player_name,
       s.buyer_club_id, s.buyer_club_name, s.season_id, s.fee_amount,
       CASE WHEN s.buyer_club_id IS NULL THEN NULL
            ELSE COALESCE(l.league_code,
                          CASE WHEN n.club_id IS NOT NULL THEN 'NL1' END,
                          'OTHER')
       END AS buyer_league_that_season,
       CASE WHEN s.buyer_club_id IS NULL
              OR s.season_id - 1 < (SELECT MIN(season_id) FROM league_season_clubs) THEN NULL
            ELSE COALESCE(lp.league_code,
                          CASE WHEN np.club_id IS NOT NULL THEN 'NL1' END,
                          'OTHER')
       END AS buyer_league_prev_season,
       CASE WHEN s.buyer_club_id IS NULL THEN NULL
            ELSE (l.league_code IS NOT NULL) END AS buyer_in_big5_that_season,
       CASE WHEN s.buyer_club_id IS NULL
              OR s.season_id - 1 < (SELECT MIN(season_id) FROM league_season_clubs) THEN NULL
            ELSE (lp.league_code IS NOT NULL) END AS buyer_in_big5_prev_season
FROM buyer_spend_context s
LEFT JOIN league_season_clubs l
  ON l.club_id = s.buyer_club_id AND l.season_id = s.season_id
LEFT JOIN league_season_clubs lp
  ON lp.club_id = s.buyer_club_id AND lp.season_id = s.season_id - 1
LEFT JOIN eredivisie_club_status n
  ON n.club_id = s.buyer_club_id AND n.season_id = s.season_id AND n.was_eredivisie
LEFT JOIN eredivisie_club_status np
  ON np.club_id = s.buyer_club_id AND np.season_id = s.season_id - 1 AND np.was_eredivisie;

-- =====================================================================
-- CHECKS -- run after creating or refreshing the view. Read-only.
-- =====================================================================

-- 1. Grain. The three numbers must be IDENTICAL: every paid Eredivisie sale
--    appears exactly once, matching buyer_spend_context.
SELECT (SELECT COUNT(*) FROM buyer_league_context)                 AS view_rows,
       (SELECT COUNT(DISTINCT transfer_id) FROM buyer_league_context) AS distinct_sales,
       (SELECT COUNT(*) FROM buyer_spend_context)                  AS source_rows;

-- 2. Independent cross-check. Recomputes both league columns for every row
--    with EXISTS subqueries (a different shape from the view's joins) and
--    returns any row where they disagree. MUST return zero rows.
SELECT v.transfer_id, v.player_name, v.season_id,
       v.buyer_league_that_season, d.that_league,
       v.buyer_league_prev_season, d.prev_league
FROM buyer_league_context v
JOIN LATERAL (
    SELECT
      CASE WHEN v.buyer_club_id IS NULL THEN NULL
           WHEN EXISTS (SELECT 1 FROM league_season_clubs x WHERE x.club_id = v.buyer_club_id AND x.season_id = v.season_id)
                THEN (SELECT x.league_code FROM league_season_clubs x WHERE x.club_id = v.buyer_club_id AND x.season_id = v.season_id)
           WHEN EXISTS (SELECT 1 FROM eredivisie_club_status n WHERE n.club_id = v.buyer_club_id AND n.season_id = v.season_id AND n.was_eredivisie)
                THEN 'NL1'
           ELSE 'OTHER' END AS that_league,
      CASE WHEN v.buyer_club_id IS NULL OR v.season_id - 1 < (SELECT MIN(season_id) FROM league_season_clubs) THEN NULL
           WHEN EXISTS (SELECT 1 FROM league_season_clubs x WHERE x.club_id = v.buyer_club_id AND x.season_id = v.season_id - 1)
                THEN (SELECT x.league_code FROM league_season_clubs x WHERE x.club_id = v.buyer_club_id AND x.season_id = v.season_id - 1)
           WHEN EXISTS (SELECT 1 FROM eredivisie_club_status n WHERE n.club_id = v.buyer_club_id AND n.season_id = v.season_id - 1 AND n.was_eredivisie)
                THEN 'NL1'
           ELSE 'OTHER' END AS prev_league
) d ON TRUE
WHERE v.buyer_league_that_season IS DISTINCT FROM d.that_league
   OR v.buyer_league_prev_season IS DISTINCT FROM d.prev_league;

-- 3. The two membership sources must not contradict each other. A club in a
--    Big-5 league and in the Eredivisie in the SAME season means a bad club id
--    somewhere. MUST return zero rows.
SELECT l.club_id, l.season_id, l.league_code, n.club_name
FROM league_season_clubs l
JOIN eredivisie_club_status n
  ON n.club_id = l.club_id AND n.season_id = l.season_id AND n.was_eredivisie;

-- 4. Human check. What the league labels look like across all paid sales: how
--    many sales and how much fee value land in each. 'OTHER' is the lumped
--    bucket (other countries' top flights, lower divisions, a domestic buyer
--    outside the Eredivisie that season).
SELECT buyer_league_that_season AS league,
       COUNT(*)                 AS sales,
       ROUND(SUM(fee_amount), 1) AS fee_value_m,
       ROUND(MAX(fee_amount), 1) AS biggest_sale_m
FROM buyer_league_context
GROUP BY buyer_league_that_season
ORDER BY SUM(fee_amount) DESC;

-- 5. Human check. How often the two columns DISAGREE: the summer after a
--    promotion or relegation (or a move between Big-5 and not). These are the
--    sales where "which league" is genuinely ambiguous.
SELECT buyer_league_prev_season AS prev_season_league,
       buyer_league_that_season AS that_season_league,
       COUNT(*)                 AS sales,
       ROUND(SUM(fee_amount), 1) AS fee_value_m
FROM buyer_league_context
WHERE buyer_league_prev_season IS NOT NULL
  AND buyer_league_prev_season IS DISTINCT FROM buyer_league_that_season
GROUP BY buyer_league_prev_season, buyer_league_that_season
ORDER BY COUNT(*) DESC;

-- 6. Spot-check one real transfer by name.
SELECT player_name, buyer_club_name, season_id, fee_amount,
       buyer_league_that_season, buyer_league_prev_season
FROM buyer_league_context
WHERE player_name ILIKE '%ligt%';
