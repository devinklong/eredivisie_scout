-- eredivisie_club_status.sql
-- Reference/lookup table: whether a given club was actually playing in the
-- Eredivisie (top flight) during a given season. Built from a manual
-- Wikipedia season-by-season compilation (2026-08-29), covering 2010-11
-- through the current season, 29 distinct clubs. Used to filter
-- eredivisie_transfers.sql down to only Eredivisie-relevant seasons per
-- club -- a club's transfer history includes years spent in lower
-- divisions too, which this table lets you exclude at query time.

DROP TABLE IF EXISTS eredivisie_club_status CASCADE;

CREATE TABLE eredivisie_club_status (
    club_id             INTEGER NOT NULL,       -- Transfermarkt's numeric club ID (the "verein/{id}" in each club's URL)
    club_name           TEXT NOT NULL,           -- Display name, e.g. 'Ajax', 'De Graafschap' -- no separate clubs dimension table exists yet, so this is stored here for readability rather than normalized further
    season_id           INTEGER NOT NULL,        -- Starting year of the season, matching the season_id already captured in scraped transfer rows (e.g. 2020 = the 2020-21 season)
    was_eredivisie       BOOLEAN NOT NULL,        -- TRUE if this club played in the Eredivisie (top flight) that season
    PRIMARY KEY (club_id, season_id)
);

-- Populate via INSERT statements built from the manual season compilation --
-- not included here since that's data, not schema. One row per
-- (club, season) pair actually confirmed, covering 2010-11 onward.

SELECT COUNT(*) FROM eredivisie_club_status;
SELECT * FROM eredivisie_club_status;