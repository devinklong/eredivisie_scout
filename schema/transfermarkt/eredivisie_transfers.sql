-- eredivisie_transfers.sql
-- Raw transfer records scraped from Transfermarkt's full club transfer-
-- history pages (pipelines/transfermarkt/extract_transfermarkt_transfer_
-- history.py), across all 29 clubs that have played in the Eredivisie
-- since 2010-11 (pipelines/transfermarkt/scrape_all_eredivisie_clubs.py,
-- confirmed 29/29 succeeded, 2026-08-29 -- ~36k rows total). One row per
-- scraped transfer event, from the perspective of whichever club's page
-- it came from (own_club_id) -- NOT deduplicated. A transfer between two
-- clubs that are both in the 29-club set appears TWICE (once from each
-- club's own page, with direction flipped) -- this is intentional at the
-- raw-table level, matching this project's 3NF convention of storing raw
-- data undeduplicated and handling derived logic in views, not here.
-- Dedup/join logic against eredivisie_club_status.sql is a downstream
-- concern, not enforced by this schema.

DROP TABLE IF EXISTS eredivisie_transfers CASCADE;

CREATE TABLE eredivisie_transfers (
    transfer_id             SERIAL PRIMARY KEY,
    player_id               INTEGER,                 -- Transfermarkt's numeric player ID (the "spieler/{id}" in the player's profile link) -- the real join key; player_name is display-only, not reliable for joins (accent/formatting inconsistencies)
    player_name             TEXT,
    own_club_id             INTEGER NOT NULL,        -- Transfermarkt club ID of the club whose transfer-history page this row was scraped from
    direction                TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    counterparty_club_id    INTEGER,                 -- NULL when the player retired, or when Transfermarkt has no linked club reference for this transfer (counterparty_club_name = 'Unknown' in that case -- confirmed NOT a reliable signal that the club no longer exists, see docs/v1_roadmap.md)
    counterparty_club_name  TEXT,
    season_id                INTEGER,                 -- Starting year of the season this transfer occurred in -- join key against eredivisie_club_status.season_id
    fee_amount               NUMERIC(6,2),             -- In millions of euros. NULL for any fee_type other than 'permanent_transfer', 'paid_loan', or 'free_transfer' (which is 0.00, not NULL)
    fee_type                 TEXT NOT NULL,            -- One of: permanent_transfer, free_transfer, unpaid_loan, paid_loan, paid_loan_undisclosed, loan_ended, unknown_historical, unknown, empty_cell, or an 'unrecognized: ...' string for any genuinely new format hit by a club outside the original PSV validation set
    is_internal_promotion    BOOLEAN NOT NULL DEFAULT FALSE  -- TRUE for youth/reserve-team-to-first-team moves (e.g. counterparty 'PSV U21') -- not a real external transfer, exclude from valuation-model training data
);

-- NOTE: buy-option clauses on loans (e.g. Arokodare's loan from Wolves) are
-- NOT captured anywhere in this table -- confirmed not present in the
-- source data this was scraped from. Do not add a "loan_with_option"
-- fee_type expecting it to be populated; see docs/v1_roadmap.md.

-- No hard foreign key to eredivisie_club_status is enforced here
-- deliberately -- own_club_id/season_id combinations may include seasons
-- or clubs outside what's been populated in eredivisie_club_status yet.
-- Join at query time instead.

SELECT COUNT(*) FROM eredivisie_transfers;  -- ~36k rows, 2026-08-29