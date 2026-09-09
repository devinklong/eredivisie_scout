-- players.sql
-- Canonical player identity table. One row per real person, independent
-- of any single source's naming convention. Synthetic surrogate key
-- (player_id), NOT tied to any one source's own ID scheme (e.g. not
-- Transfermarkt's spieler/{id}) -- decided during entity-resolution
-- planning so adding/removing a source later doesn't require re-keying
-- everything downstream.

DROP TABLE IF EXISTS players CASCADE;

CREATE TABLE players (
    player_id       SERIAL PRIMARY KEY,
    canonical_name   TEXT NOT NULL,   -- defaults to the FBref-side name for a confirmed FBref<->WhoScored match -- see player_source_crosswalk.sql for the actual per-source name each source used
    created_at        TIMESTAMP NOT NULL DEFAULT now()
);

SELECT COUNT(*) FROM players;

SELECT t.season_id, COUNT(DISTINCT t.player_id) AS players,
       COUNT(DISTINCT b.player_id) FILTER (WHERE b.height_cm IS NOT NULL) AS with_height
FROM eredivisie_transfers t
LEFT JOIN eredivisie_transfermarkt_player_bio b ON t.player_id = b.player_id
WHERE t.player_id IS NOT NULL
GROUP BY t.season_id
ORDER BY t.season_id;