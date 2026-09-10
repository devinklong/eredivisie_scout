-- players_transfermarkt_candidate_pairs.sql
-- Candidate-pair VIEW for the entity-resolution SECOND pass: matching
-- canonical players against Transfermarkt's player_name.
--
-- REBUILT (2026-09-08) with real team/season blocking. The first
-- version had none -- confirmed via a real run that this produced an
-- unworkable 3,213-row review band (57.7% of all candidates), most of
-- it the riskiest collision pattern (same_given_name_diff_surname).
-- Root cause: comparing every canonical player against every
-- Transfermarkt player by name alone, with nothing narrowing the
-- comparison down first.
--
-- THE FIX: player_source_crosswalk already records which FBref/
-- WhoScored name each canonical player maps to -- joining that back
-- to the two stats tables reconstructs exactly which (team, season_id)
-- pairs each canonical player actually appeared in. Matching that
-- against eredivisie_transfers' own (own_club_name, season_id) gives a
-- real block: only Transfermarkt players who had an actual transfer
-- record at a club+season overlapping one of the canonical player's
-- known appearances become candidates at all. Team-name consistency
-- across sources is assumed (confirmed for PSV specifically -- see
-- patch_list.md -- not exhaustively re-checked for every club here).

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Speeds up the '%' similarity operator below via an index instead of
-- brute-force computing similarity() for every pairing.
CREATE INDEX IF NOT EXISTS idx_players_canonical_name_trgm
    ON players USING gin (canonical_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_transfers_player_name_trgm
    ON eredivisie_transfers USING gin (player_name gin_trgm_ops);

-- Sets the '%' operator's threshold as a database-wide default so it
-- doesn't need to be set per-session. Safe to rerun -- if this was
-- already set in an earlier session, this just reaffirms the same
-- value.
ALTER DATABASE postgres SET pg_trgm.similarity_threshold = 0.3;

-- Every (team, season_id) a canonical player is known to have
-- appeared in, from EITHER source side of the crosswalk.
CREATE OR REPLACE VIEW player_team_season_history AS
SELECT psc.player_id, s.team, s.season_id
FROM player_source_crosswalk psc
JOIN eredivisie_soccerdata_player_season_stats s
    ON psc.source = 'fbref' AND psc.source_name = s.player_name
UNION
SELECT psc.player_id, w.team, w.season_id
FROM player_source_crosswalk psc
JOIN eredivisie_whoscored_player_season_stats w
    ON psc.source = 'whoscored' AND psc.source_name = w.player_name;

-- Blocked candidates: a Transfermarkt player only shows up here if
-- BOTH conditions hold -- (1) a real transfer record at a club+season
-- matching one of the canonical player's known team/season
-- appearances, AND (2) the names are actually similar. CONFIRMED BUG
-- (2026-09-08): an earlier version of this view had ONLY the
-- team/season condition, no name-similarity filter at all -- since
-- eredivisie_transfers is NOT deduplicated (a club can have 20+
-- transfer records in one season), that produced 115,335 candidate
-- pairs, an order of magnitude WORSE than the original unblocked
-- version (5,570) -- every player who appeared for a club in a season
-- was matching every OTHER player who had any transfer at that same
-- club/season, with zero regard for whether the names looked anything
-- alike. Fixed by requiring the '%' similarity operator too, same as
-- the original unblocked version -- team/season narrows the pool,
-- name similarity picks real candidates out of that narrowed pool.
CREATE OR REPLACE VIEW players_transfermarkt_candidate_pairs AS
SELECT DISTINCT
    p.player_id AS canonical_player_id,
    p.canonical_name,
    t.player_id AS transfermarkt_player_id,
    t.player_name AS transfermarkt_name,
    similarity(p.canonical_name, t.player_name) AS trgm_similarity
FROM players p
JOIN player_team_season_history h ON h.player_id = p.player_id
JOIN eredivisie_transfers t
    ON t.own_club_name = h.team AND t.season_id = h.season_id
    AND p.canonical_name % t.player_name
WHERE t.player_id IS NOT NULL;

-- Sanity check after running the above:
SELECT COUNT(*) FROM players_transfermarkt_candidate_pairs;  -- should be meaningfully lower than the unblocked 5,570
