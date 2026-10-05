-- buyer_club_transfers_checks.sql
-- Run AFTER load_buyer_club_transfers.py. Three checks, each says what a
-- good and a bad result looks like. Read-only.
--
-- Check 2 matters most. The extractor labels direction by table-index
-- parity (even = 'in', odd = 'out'), which its own docstring says was
-- never fully confirmed, and for a buyer club direction = 'in' IS the
-- spend. The Eredivisie side gives independent ground truth: every paid
-- 'out' transfer from an Eredivisie club to a scraped buyer must appear
-- as an 'in' on that buyer's own page.

-- 1. Per-club coverage. Every scraped club should have rows in both
--    directions across a sensible season range. A club with 0 'in' or
--    0 'out' rows, a far-off season range, or many unrecognized fee
--    formats needs a look before the data is used.
SELECT own_club_id, own_club_name,
       COUNT(*)                                          AS total_rows,
       COUNT(*) FILTER (WHERE direction = 'in')          AS ins,
       COUNT(*) FILTER (WHERE direction = 'out')         AS outs,
       MIN(season_id)                                    AS first_season,
       MAX(season_id)                                    AS last_season,
       COUNT(*) FILTER (WHERE fee_type LIKE 'unrecognized%') AS unrecognized_fees
FROM buyer_club_transfers
GROUP BY own_club_id, own_club_name
ORDER BY total_rows DESC;

-- 2. Direction cross-check against the Eredivisie side's own records.
--    GOOD: pct_found_as_in near 100, found_only_as_out_direction_flipped
--    at or near 0. BAD: a meaningful found_only_as_out count means the
--    parity rule flipped direction for some tables and direction = 'in'
--    can't be trusted as the spend side. A high not_found with ~0
--    flipped is a different problem (season/club-id mismatch between the
--    two pages, or transfers missing from the buyer's page) -- inspect a
--    few not_found rows before concluding anything.
WITH ered_paid_out AS (
    SELECT player_id,
           own_club_id          AS seller_id,
           counterparty_club_id AS buyer_id,
           season_id
    FROM eredivisie_transfers
    WHERE direction = 'out'
      AND fee_type IN ('permanent_transfer', 'paid_loan')
      AND fee_amount IS NOT NULL
      AND player_id IS NOT NULL
      AND counterparty_club_id IN (SELECT DISTINCT own_club_id FROM buyer_club_transfers)
      AND season_id >= (SELECT MIN(season_id) FROM buyer_club_transfers)
),
matched AS (
    SELECT e.*,
           EXISTS (SELECT 1 FROM buyer_club_transfers b
                   WHERE b.own_club_id = e.buyer_id AND b.player_id = e.player_id
                     AND b.season_id = e.season_id AND b.counterparty_club_id = e.seller_id
                     AND b.direction = 'in')  AS as_in,
           EXISTS (SELECT 1 FROM buyer_club_transfers b
                   WHERE b.own_club_id = e.buyer_id AND b.player_id = e.player_id
                     AND b.season_id = e.season_id AND b.counterparty_club_id = e.seller_id
                     AND b.direction = 'out') AS as_out
    FROM ered_paid_out e
)
SELECT COUNT(*)                                          AS ered_outs_to_scraped_buyers,
       COUNT(*) FILTER (WHERE as_in)                     AS found_as_in,
       COUNT(*) FILTER (WHERE as_out AND NOT as_in)      AS found_only_as_out_direction_flipped,
       COUNT(*) FILTER (WHERE NOT as_in AND NOT as_out)  AS not_found,
       ROUND(100.0 * COUNT(*) FILTER (WHERE as_in) / NULLIF(COUNT(*), 0), 1) AS pct_found_as_in
FROM matched;

-- 3. Fee agreement on the transfers both pages describe. The seller's
--    page and the buyer's page should state the same fee. GOOD: 0 or
--    near-0 disagreements. Any rows listed are worth eyeballing -- they
--    point at either fee-parsing differences or a join on the wrong
--    transfer when a player moved twice in one season.
SELECT COUNT(*)                                                  AS matched_rows,
       COUNT(*) FILTER (WHERE b.fee_amount IS DISTINCT FROM e.fee_amount) AS fee_disagreements
FROM eredivisie_transfers e
JOIN buyer_club_transfers b
  ON b.own_club_id = e.counterparty_club_id
 AND b.counterparty_club_id = e.own_club_id
 AND b.player_id = e.player_id
 AND b.season_id = e.season_id
 AND b.direction = 'in'
WHERE e.direction = 'out'
  AND e.fee_type IN ('permanent_transfer', 'paid_loan')
  AND e.fee_amount IS NOT NULL;

-- 3b. The disagreements themselves (empty if check 3 is clean):
SELECT e.player_name, e.season_id, e.own_club_id AS seller_id,
       e.counterparty_club_id AS buyer_id,
       e.fee_amount AS seller_page_fee, b.fee_amount AS buyer_page_fee
FROM eredivisie_transfers e
JOIN buyer_club_transfers b
  ON b.own_club_id = e.counterparty_club_id
 AND b.counterparty_club_id = e.own_club_id
 AND b.player_id = e.player_id
 AND b.season_id = e.season_id
 AND b.direction = 'in'
WHERE e.direction = 'out'
  AND e.fee_type IN ('permanent_transfer', 'paid_loan')
  AND e.fee_amount IS NOT NULL
  AND b.fee_amount IS DISTINCT FROM e.fee_amount
ORDER BY e.season_id DESC
LIMIT 25;
