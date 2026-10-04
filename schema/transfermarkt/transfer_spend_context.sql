-- transfer_spend_context.sql
-- For every incoming transfer, what % of the buying club's trailing
-- 5-year spend that single transfer represents -- a conviction/risk
-- signal, not just raw fee size. A EUR5M PSV signing and a EUR5M RKC
-- Waalwijk signing aren't the same bet relative to how each club
-- normally operates; this view makes them comparable.
--
-- Scoped to own_club_id per row, so eredivisie_transfers' known
-- non-deduplication (a transfer between two tracked clubs appears
-- twice, once from each club's page) is NOT a double-counting risk
-- here -- each row's trailing spend is computed only from THAT club's
-- own incoming transfers.
--
-- MIN_TRAILING_TRANSFERS floor: a club with very little trailing
-- history (newly promoted, or early in the dataset with few prior
-- seasons available) produces a wildly inflated pct_of_5yr_club_spend
-- off a tiny denominator -- same small-sample distortion the
-- fbref_nineties >= 5.0 floor exists to prevent elsewhere in this
-- project. pct_of_5yr_club_spend is set NULL (not filtered out --
-- the row itself may still be useful for other features) when the
-- trailing window has fewer than 3 real transfers to average over.

CREATE OR REPLACE VIEW transfer_spend_context AS
WITH incoming_fees AS (
    SELECT own_club_id, season_id, fee_amount
    FROM eredivisie_transfers
    WHERE direction = 'in'
      AND fee_type IN ('permanent_transfer', 'paid_loan')
      AND fee_amount IS NOT NULL
),
club_seasons AS (
    -- One row per (club, season), NOT per transfer. Joining
    -- incoming_fees to itself directly (one row per transfer on the
    -- left side) fans out: every fee in the trailing window gets
    -- counted once per incoming transfer the club made that season,
    -- inflating trailing_5yr_spend and trailing_5yr_transfer_count by
    -- that factor. Caught 2026-10-03 when PSV's trailing 5-year spend
    -- came back as EUR1,357M -- fixed by collapsing to distinct
    -- club-seasons first.
    SELECT DISTINCT own_club_id, season_id FROM incoming_fees
),
club_5yr_spend AS (
    SELECT a.own_club_id, a.season_id,
           SUM(b.fee_amount) AS trailing_5yr_spend,
           COUNT(b.fee_amount) AS trailing_5yr_transfer_count
    FROM club_seasons a
    JOIN incoming_fees b
      ON b.own_club_id = a.own_club_id
     AND b.season_id BETWEEN a.season_id - 4 AND a.season_id
    GROUP BY a.own_club_id, a.season_id
)
SELECT t.transfer_id, t.player_id, t.player_name, t.own_club_id, t.season_id,
       t.fee_amount,
       c.trailing_5yr_spend,
       c.trailing_5yr_transfer_count,
       CASE
           WHEN c.trailing_5yr_transfer_count >= 3
           THEN ROUND(100.0 * t.fee_amount / NULLIF(c.trailing_5yr_spend, 0), 1)
           ELSE NULL
       END AS pct_of_5yr_club_spend
FROM eredivisie_transfers t
JOIN club_5yr_spend c ON c.own_club_id = t.own_club_id AND c.season_id = t.season_id
WHERE t.direction = 'in'
  AND t.fee_type IN ('permanent_transfer', 'paid_loan')
  AND t.fee_amount IS NOT NULL;

-- =====================================================================
-- SANITY CHECKS -- run both after creating/refreshing the view above.
-- =====================================================================

-- 1. The floor should exclude a real, MODERATE number of rows (thin-
--    history club-seasons -- newly promoted clubs, or clubs early in
--    the dataset with few trailing seasons available), not most of
--    the view. If "floored" is close to "total", the floor is too
--    strict or something upstream is wrong -- investigate before
--    trusting pct_of_5yr_club_spend as a feature.
SELECT
    COUNT(*) FILTER (WHERE pct_of_5yr_club_spend IS NULL) AS floored,
    COUNT(*) AS total,
    ROUND(100.0 * COUNT(*) FILTER (WHERE pct_of_5yr_club_spend IS NULL) / NULLIF(COUNT(*), 0), 1) AS floored_pct
FROM transfer_spend_context;

-- 2. Spot-check PSV's (club_id 383) biggest signings -- each row's
--    pct_of_5yr_club_spend should be a real, plausible percentage
--    (roughly single digits to maybe 30-40% for a genuinely marquee
--    signing), not something absurd like >100% or a suspiciously
--    round number. If a value looks wrong, check trailing_5yr_spend
--    and trailing_5yr_transfer_count on that same row first. A
--    denominator that's absurdly HIGH (e.g. PSV at EUR1,357M) means a
--    join fan-out inflating the sum; an unexpectedly LOW one means the
--    window is missing seasons. Either way, run check 3 below.
SELECT * FROM transfer_spend_context
WHERE own_club_id = 383
ORDER BY fee_amount DESC
LIMIT 5;

-- 3. Independent denominator cross-check: recomputes every club-
--    season's trailing spend with a plain direct SUM (a different
--    query shape from the view's self-join) and returns any club-
--    season where the two disagree. MUST return zero rows -- any row
--    here means the view's denominator is wrong for that club-season.
--    This is the check that catches join fan-outs automatically,
--    rather than relying on someone eyeballing a spot-check.
SELECT v.own_club_id, v.season_id, v.trailing_5yr_spend, d.direct_sum
FROM (
    SELECT DISTINCT own_club_id, season_id, trailing_5yr_spend
    FROM transfer_spend_context
) v
JOIN LATERAL (
    SELECT SUM(t.fee_amount) AS direct_sum
    FROM eredivisie_transfers t
    WHERE t.own_club_id = v.own_club_id
      AND t.direction = 'in'
      AND t.fee_type IN ('permanent_transfer', 'paid_loan')
      AND t.fee_amount IS NOT NULL
      AND t.season_id BETWEEN v.season_id - 4 AND v.season_id
) d ON TRUE
WHERE ABS(v.trailing_5yr_spend - d.direct_sum) > 0.01;
