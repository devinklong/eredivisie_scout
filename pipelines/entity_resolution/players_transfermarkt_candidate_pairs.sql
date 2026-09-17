-- players_transfermarkt_candidate_pairs.sql
--
-- REFACTORED (2026-09-16): TWO real bugs fixed in this version, both
-- of the same root cause -- blocking on a raw team-name string instead
-- of a real ID.
--
-- BUG 1 (pre-existing, undocumented until now): the original version
-- joined `t.own_club_name = h.team` -- but eredivisie_transfers has
-- no own_club_name column at all in its tracked schema, only the
-- numeric own_club_id. Whether this ever actually ran depends on
-- whether own_club_name was added directly to the live database
-- outside the tracked schema file -- either way, it's fixed now by
-- using own_club_id directly, which IS real and already numeric.
--
-- BUG 2: even setting BUG 1 aside, blocking on any raw team-name
-- string is the same class of bug already found and fixed for
-- FBref<->WhoScored blocking (fbref_whoscored_candidate_pairs.sql,
-- 2026-09-15/16) -- confirmed to silently exclude every player at a
-- club whose spellings disagreed across sources. The original
-- comment here even flagged this as a known risk ("Team-name
-- consistency across sources is assumed... not exhaustively
-- re-checked for every club here") but was never followed up on.
--
-- THE FIX: player_team_season_history now resolves each appearance's
-- team to a real team_id via team_name_alias (same table used for the
-- FBref<->WhoScored fix). eredivisie_transfers' own_club_id is
-- ALREADY Transfermarkt's real numeric club ID -- the same ID space
-- team_name_alias.club_id is anchored on -- so the Transfermarkt side
-- of this join needs NO string resolution at all, just a direct
-- integer comparison.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_players_canonical_name_trgm
    ON players USING gin (canonical_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_transfers_player_name_trgm
    ON eredivisie_transfers USING gin (player_name gin_trgm_ops);

ALTER DATABASE postgres SET pg_trgm.similarity_threshold = 0.3;

-- Every (team_id, season_id) a canonical player is known to have
-- appeared in, from EITHER source side of the crosswalk -- team
-- resolved to a real ID via team_name_alias, not left as a raw string.
--
-- Uses DROP VIEW + CREATE VIEW, not CREATE OR REPLACE, same reason as
-- master_player_season_stats: Postgres won't let CREATE OR REPLACE
-- rename an existing column (this version renames the old "team"
-- column to "team_id"), only append new ones at the end. CASCADE is
-- required since players_transfermarkt_candidate_pairs depends on
-- this view -- it gets dropped too and is recreated right after.
DROP VIEW IF EXISTS player_team_season_history CASCADE;

CREATE VIEW player_team_season_history AS
SELECT psc.player_id, fbref_alias.club_id AS team_id, s.season_id
FROM player_source_crosswalk psc
JOIN eredivisie_soccerdata_player_season_stats s
    ON psc.source = 'fbref' AND psc.source_name = s.player_name
JOIN team_name_alias fbref_alias
    ON fbref_alias.source = 'fbref' AND fbref_alias.source_name = s.team

UNION

SELECT psc.player_id, ws_alias.club_id AS team_id, w.season_id
FROM player_source_crosswalk psc
JOIN eredivisie_whoscored_player_season_stats w
    ON psc.source = 'whoscored' AND psc.source_name = w.player_name
JOIN team_name_alias ws_alias
    ON ws_alias.source = 'whoscored' AND ws_alias.source_name = w.team;

-- Blocked candidates: a Transfermarkt player only shows up here if
-- BOTH conditions hold -- (1) a real transfer record at a club+season
-- matching one of the canonical player's known team/season
-- appearances, now via team_id not a name string, AND (2) the names
-- are actually similar.
--
-- Also DROP + CREATE, not REPLACE -- this view was just dropped via
-- the CASCADE above (its old column shape doesn't matter now, but
-- CREATE OR REPLACE would fail the same way if any future column
-- gets renamed here too, so this is written the safe way from the
-- start).
DROP VIEW IF EXISTS players_transfermarkt_candidate_pairs;

CREATE VIEW players_transfermarkt_candidate_pairs AS
SELECT DISTINCT
    p.player_id AS canonical_player_id,
    p.canonical_name,
    t.player_id AS transfermarkt_player_id,
    t.player_name AS transfermarkt_name,
    similarity(p.canonical_name, t.player_name) AS trgm_similarity
FROM players p
JOIN player_team_season_history h ON h.player_id = p.player_id
JOIN eredivisie_transfers t
    ON t.own_club_id = h.team_id AND t.season_id = h.season_id
    AND p.canonical_name % t.player_name
WHERE t.player_id IS NOT NULL;

-- Sanity check after running the above:
SELECT COUNT(*) FROM players_transfermarkt_candidate_pairs;
