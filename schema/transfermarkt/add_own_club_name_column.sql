-- add_own_club_name_column.sql
-- Adds own_club_name to the EXISTING eredivisie_transfers table without
-- dropping/losing the ~36k already-loaded rows. Backfilled from
-- eredivisie_club_status, since own_club_id is always resolvable
-- (NOT NULL on this table) -- see eredivisie_transfermarkt_transfers.sql
-- for the corresponding DDL update if the schema is ever rebuilt fresh.

ALTER TABLE eredivisie_transfers ADD COLUMN own_club_name TEXT;

UPDATE eredivisie_transfers t
SET own_club_name = cs.club_name
FROM (
    SELECT DISTINCT ON (club_id) club_id, club_name
    FROM eredivisie_club_status
    ORDER BY club_id, season_id DESC
) cs
WHERE t.own_club_id = cs.club_id;

-- Sanity check: should return zero rows. Any club_id here was never in
-- scope for eredivisie_club_status (e.g. a season/club combo not yet
-- compiled into that reference table) -- not a bug in this backfill,
-- but worth knowing about if it returns anything.
SELECT DISTINCT own_club_id FROM eredivisie_transfers
WHERE own_club_name IS NULL;
