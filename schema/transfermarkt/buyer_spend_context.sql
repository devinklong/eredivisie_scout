-- buyer_spend_context.sql
-- For every PAID transfer out of the Eredivisie, how big a bet was it for the
-- BUYING club? The fee as a share of everything that club paid for arrivals
-- in the same season, and in its trailing five seasons. A EUR85M signing is a
-- different bet for a club that spends EUR150M a season than for one that
-- spends EUR300M.
--
-- Built on buyer_club_transfers (the full transfer history of the 69 external
-- clubs that paid >= EUR10M for Eredivisie players -- see
-- pipelines/transfermarkt/select_buyer_clubs.py). Its direction labels were
-- verified against the Eredivisie side's own records (checks 2 and 4 in
-- buyer_club_transfers_checks.sql), so direction = 'in' really is spend.
--
-- GRAIN: exactly one row per paid 'out' row in eredivisie_transfers, whether
-- or not buyer data exists for that buyer. Sales to a buyer outside the 69
-- (or to another Eredivisie club, whose spend lives in transfer_spend_context)
-- keep their row with NULL context and buyer_context_available = FALSE. That
-- follows this project's rule of leaving missing data NULL instead of dropping
-- rows. Check 1 below proves the grain.
--
-- WHICH FEE: pct_* use the BUYER page's fee for the transfer as the numerator.
-- It is part of the denominator by construction, so a share can never exceed
-- 100. fee_amount (the Eredivisie page's fee, the one used everywhere else in
-- this project) is exposed beside it as buyer_page_fee. The two pages agree on
-- 236 of 238 sales. The other two (2025) differ by EUR0.4M and EUR2.0M.
--
-- WHICH WINDOW: Transfermarkt's season_id covers a season's summer AND winter
-- windows together, so "that window" is the whole season. The trailing window
-- is the sale's season and the four before it. It ends AT the sale's season,
-- so the announced-future (2026/2027) rows in buyer_club_transfers can never
-- enter. Only 'permanent_transfer' and 'paid_loan' rows with a fee count, same
-- definition as transfer_spend_context.sql.
--
-- FLOORS: pct_of_buyer_5yr_spend is NULL when the trailing window holds fewer
-- than 3 paid arrivals (same floor and reasoning as transfer_spend_context:
-- a thin denominator inflates the share). pct_of_buyer_season_spend is NOT
-- floored: 100% legitimately means "this one signing was the club's entire
-- season of spending", and season_paid_count is exposed so a consumer can
-- decide for itself.
--
-- THE CLUB-SEASONS CTE IS LOAD-BEARING. Joining the paid-arrivals set to
-- itself directly fans out (every fee counted once per arrival that season),
-- which inflated PSV's trailing spend 8x in transfer_spend_context before it
-- was caught. Collapsing to one row per club-season first prevents it, and
-- check 2 would catch it if it came back.

CREATE OR REPLACE VIEW buyer_spend_context AS
WITH buyer_paid_in AS (
    SELECT own_club_id, season_id, fee_amount
    FROM buyer_club_transfers
    WHERE direction = 'in'
      AND fee_type IN ('permanent_transfer', 'paid_loan')
      AND fee_amount IS NOT NULL
),
club_seasons AS (
    SELECT DISTINCT own_club_id, season_id FROM buyer_paid_in
),
buyer_windows AS (
    SELECT cs.own_club_id, cs.season_id,
           SUM(b.fee_amount)   FILTER (WHERE b.season_id = cs.season_id) AS season_paid_total,
           COUNT(b.fee_amount) FILTER (WHERE b.season_id = cs.season_id) AS season_paid_count,
           SUM(b.fee_amount)   AS trailing_5yr_paid_total,
           COUNT(b.fee_amount) AS trailing_5yr_paid_count
    FROM club_seasons cs
    JOIN buyer_paid_in b
      ON b.own_club_id = cs.own_club_id
     AND b.season_id BETWEEN cs.season_id - 4 AND cs.season_id
    GROUP BY cs.own_club_id, cs.season_id
),
sales AS (
    SELECT transfer_id, player_id, player_name,
           own_club_id AS seller_club_id,
           counterparty_club_id AS buyer_club_id,
           counterparty_club_name AS buyer_club_name,
           season_id, fee_amount, fee_type
    FROM eredivisie_transfers
    WHERE direction = 'out'
      AND fee_type IN ('permanent_transfer', 'paid_loan')
      AND fee_amount IS NOT NULL
)
SELECT s.transfer_id, s.player_id, s.player_name,
       s.seller_club_id, s.buyer_club_id, s.buyer_club_name, s.season_id,
       s.fee_amount,
       m.buyer_page_fee,
       w.season_paid_total, w.season_paid_count,
       w.trailing_5yr_paid_total, w.trailing_5yr_paid_count,
       (m.buyer_page_fee IS NOT NULL AND w.own_club_id IS NOT NULL) AS buyer_context_available,
       ROUND(100.0 * m.buyer_page_fee / NULLIF(w.season_paid_total, 0), 1) AS pct_of_buyer_season_spend,
       CASE WHEN w.trailing_5yr_paid_count >= 3
            THEN ROUND(100.0 * m.buyer_page_fee / NULLIF(w.trailing_5yr_paid_total, 0), 1)
       END AS pct_of_buyer_5yr_spend
FROM sales s
LEFT JOIN LATERAL (
    -- The same transfer on the buyer's own page. LIMIT 1 keeps the grain at
    -- one row per sale even if the buyer page lists the player twice for the
    -- season (a permanent move plus a loan fee, say). An exact fee match wins.
    SELECT b.fee_amount AS buyer_page_fee
    FROM buyer_club_transfers b
    WHERE b.own_club_id = s.buyer_club_id
      AND b.counterparty_club_id = s.seller_club_id
      AND b.player_id = s.player_id
      AND b.season_id = s.season_id
      AND b.direction = 'in'
      AND b.fee_type IN ('permanent_transfer', 'paid_loan')
      AND b.fee_amount IS NOT NULL
    ORDER BY (b.fee_amount = s.fee_amount) DESC, b.transfer_id
    LIMIT 1
) m ON TRUE
LEFT JOIN buyer_windows w
  ON w.own_club_id = s.buyer_club_id AND w.season_id = s.season_id;

-- =====================================================================
-- CHECKS -- run after creating or refreshing the view. Read-only.
-- =====================================================================

-- 1. Grain. The three numbers must be IDENTICAL: every paid Eredivisie sale
--    appears exactly once. view_rows above source_rows means a join fanned
--    out and duplicated sales. Below means sales were dropped.
SELECT (SELECT COUNT(*) FROM buyer_spend_context) AS view_rows,
       (SELECT COUNT(DISTINCT transfer_id) FROM buyer_spend_context) AS distinct_sales,
       (SELECT COUNT(*) FROM eredivisie_transfers
         WHERE direction = 'out' AND fee_type IN ('permanent_transfer', 'paid_loan')
           AND fee_amount IS NOT NULL) AS source_rows;

-- 2. Independent denominator cross-check: recomputes every row's season and
--    trailing totals and counts with a plain direct SUM (a different query
--    shape from the view's CTEs) and returns any row where they disagree.
--    MUST return zero rows. Not vacuous only if check 2b shows a healthy
--    number of rows with context, so read the two together.
SELECT v.transfer_id, v.player_name, v.season_id,
       v.season_paid_total, d.season_direct,
       v.trailing_5yr_paid_total, d.trailing_direct,
       v.season_paid_count, d.season_count_direct,
       v.trailing_5yr_paid_count, d.trailing_count_direct
FROM buyer_spend_context v
JOIN LATERAL (
    SELECT COALESCE(SUM(b.fee_amount) FILTER (WHERE b.season_id = v.season_id), 0)   AS season_direct,
           COALESCE(SUM(b.fee_amount), 0)                                            AS trailing_direct,
           COUNT(b.fee_amount) FILTER (WHERE b.season_id = v.season_id)              AS season_count_direct,
           COUNT(b.fee_amount)                                                       AS trailing_count_direct
    FROM buyer_club_transfers b
    WHERE b.own_club_id = v.buyer_club_id
      AND b.direction = 'in'
      AND b.fee_type IN ('permanent_transfer', 'paid_loan')
      AND b.fee_amount IS NOT NULL
      AND b.season_id BETWEEN v.season_id - 4 AND v.season_id
) d ON TRUE
WHERE v.season_paid_total IS NOT NULL
  AND (ABS(v.season_paid_total - d.season_direct) > 0.01
    OR ABS(v.trailing_5yr_paid_total - d.trailing_direct) > 0.01
    OR v.season_paid_count <> d.season_count_direct
    OR v.trailing_5yr_paid_count <> d.trailing_count_direct);

-- 2b. How much of the view check 2 actually covered, and how much has no
--     buyer context (sales to buyers outside the 69, or to Eredivisie clubs).
--     Expect the covered share to be large: the 69 buyers were chosen because
--     they account for the bulk of fees paid for Eredivisie players.
SELECT COUNT(*) FILTER (WHERE buyer_context_available)     AS rows_with_context,
       COUNT(*) FILTER (WHERE NOT buyer_context_available) AS rows_without_context,
       ROUND(100.0 * SUM(fee_amount) FILTER (WHERE buyer_context_available) / SUM(fee_amount), 1)
                                                           AS pct_of_fee_value_covered
FROM buyer_spend_context;

-- 3. Bounds. A share above 100 means the numerator is not inside the
--    denominator. Must return zero rows.
SELECT transfer_id, player_name, season_id, buyer_page_fee,
       season_paid_total, pct_of_buyer_season_spend, pct_of_buyer_5yr_spend
FROM buyer_spend_context
WHERE pct_of_buyer_season_spend > 100 OR pct_of_buyer_5yr_spend > 100
   OR pct_of_buyer_season_spend < 0   OR pct_of_buyer_5yr_spend < 0;

-- 4. Spot-check one real transfer by name. Compare the fee with what you
--    know, and the season total with the buyer's other signings that season.
SELECT player_name, buyer_club_name, season_id, fee_amount, buyer_page_fee,
       season_paid_total, season_paid_count, pct_of_buyer_season_spend,
       trailing_5yr_paid_total, trailing_5yr_paid_count, pct_of_buyer_5yr_spend
FROM buyer_spend_context
WHERE player_name ILIKE '%ligt%';
