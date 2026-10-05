-- buyer_club_transfers.sql
-- Full transfer history for the NON-Eredivisie clubs that have paid real
-- fees for Eredivisie-sourced players (the 69 clubs with >= EUR10M total
-- paid -- see pipelines/transfermarkt/list_buyer_clubs.py and the
-- 2026-10-03 entry in docs/patch_list.md). Scraped from each club's own
-- Transfermarkt /alletransfers/ page by scrape_buyer_clubs.py, loaded by
-- load_buyer_club_transfers.py.
--
-- WHY A SEPARATE TABLE, NOT eredivisie_transfers: nearly all of a buyer
-- club's history (Bayern buying from Barcelona, say) has nothing to do
-- with the Eredivisie. Mixing it in would corrupt anything downstream
-- that assumes every row has an Eredivisie club on the own_club_id side.
--
-- Same shape and conventions as eredivisie_transfers: one row per
-- scraped transfer event from the perspective of the club whose page it
-- came from (own_club_id), NOT deduplicated, raw undeduplicated storage
-- with derived logic left to views.
--
-- DELIBERATE DIFFERENCE from this project's other schema files: uses
-- CREATE TABLE IF NOT EXISTS, not DROP TABLE ... CASCADE + CREATE. Those
-- files are safe to re-run because the table is cheap to rebuild, this
-- one holds a multi-club scrape that takes real time, and an accidental
-- re-run of a DROP-first file would wipe it. To rebuild from scratch on
-- purpose, DROP TABLE buyer_club_transfers first, then run this file.
--
-- own_club_id here is never an Eredivisie club (those 29 are already in
-- eredivisie_transfers from their own pages).

CREATE TABLE IF NOT EXISTS buyer_club_transfers (
    transfer_id             SERIAL PRIMARY KEY,
    player_id               INTEGER,                 -- Transfermarkt's numeric player ID -- same ID space as eredivisie_transfers.player_id, the real join key
    player_name             TEXT,                    -- display-only, not reliable for joins
    own_club_id             INTEGER NOT NULL,        -- Transfermarkt club ID of the BUYER club whose history page this row came from
    own_club_name           TEXT,                    -- from the scrape-target CSV, for readability, NULL if the club isn't in that CSV
    direction               TEXT NOT NULL CHECK (direction IN ('in', 'out')),  -- 'in' = a signing BY own_club_id (this is the spend side). Direction comes from table-index parity in the extractor, which was never fully confirmed -- see buyer_club_transfers_checks.sql check 2 before trusting it
    counterparty_club_id    INTEGER,
    counterparty_club_name  TEXT,
    season_id               INTEGER,                 -- starting year of the season, same convention as eredivisie_transfers
    fee_amount              NUMERIC(6,2),            -- millions of EUR, NULL for any fee_type other than permanent_transfer / paid_loan / free_transfer (0.00)
    fee_type                TEXT NOT NULL,           -- same vocabulary as eredivisie_transfers.fee_type
    is_internal_promotion   BOOLEAN NOT NULL DEFAULT FALSE,  -- NOTE: the extractor's pattern only matches U16-U23 suffixes, so reserve sides named 'B' / 'II' (Barcelona B, Din. Zagreb II) are NOT flagged
    scraped_at              TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS buyer_club_transfers_club_season_idx
    ON buyer_club_transfers (own_club_id, season_id);
CREATE INDEX IF NOT EXISTS buyer_club_transfers_player_idx
    ON buyer_club_transfers (player_id);
