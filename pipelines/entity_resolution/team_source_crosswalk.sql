-- team_source_crosswalk.sql
--
-- Minimal, closed-set team identity table -- NOT a rebuild of
-- player_source_crosswalk's fuzzy-matching machinery. Teams don't need
-- that: there are 29 known clubs total, total, across the entire
-- dataset's history, and every mismatch found so far was resolved by a
-- human eyeballing two short lists side by side, in seconds, with zero
-- ambiguity. Full crosswalk-with-confidence-scoring is the wrong tool
-- for a 29-row, fully-known, fully-closed problem.
--
-- Anchored on Transfermarkt's own numeric club_id -- already real,
-- already unique, already loaded (eredivisie_club_status), no need to
-- invent a new numbering scheme.
--
-- team_name_alias holds every known spelling variant per source. A
-- lookup pass (see normalize_team_name() below) resolves any source's
-- raw team string to the canonical team_id in one step.

DROP TABLE IF EXISTS team_name_alias CASCADE;

CREATE TABLE team_name_alias (
    club_id      INTEGER NOT NULL,   -- Transfermarkt's numeric club ID, the canonical anchor
    source       TEXT NOT NULL,       -- 'fbref', 'whoscored', or 'transfermarkt'
    source_name  TEXT NOT NULL,       -- the exact string that source uses
    UNIQUE (source, source_name)
);

-- Canonical identities: all 29 clubs, real data from
-- populate_eredivisie_club_status.sql (Transfermarkt's own club_id +
-- club_name). Every club gets its Transfermarkt-side name registered as
-- an alias of itself, since eredivisie_club_status IS the transfermarkt
-- source already.
INSERT INTO team_name_alias (club_id, source, source_name) VALUES
(1268, 'transfermarkt', 'ADO Den Haag'),
(610,  'transfermarkt', 'Ajax'),
(1090, 'transfermarkt', 'AZ'),
(798,  'transfermarkt', 'Excelsior'),
(234,  'transfermarkt', 'Feyenoord'),
(642,  'transfermarkt', 'De Graafschap'),
(202,  'transfermarkt', 'Groningen'),
(306,  'transfermarkt', 'Heerenveen'),
(1304, 'transfermarkt', 'Heracles Almelo'),
(132,  'transfermarkt', 'NAC Breda'),
(467,  'transfermarkt', 'NEC Nijmegen'),
(383,  'transfermarkt', 'PSV'),
(192,  'transfermarkt', 'Roda JC'),
(317,  'transfermarkt', 'Twente'),
(200,  'transfermarkt', 'Utrecht'),
(499,  'transfermarkt', 'Vitesse'),
(1426, 'transfermarkt', 'VVV Venlo'),
(403,  'transfermarkt', 'Willem II'),
(235,  'transfermarkt', 'RKC Waalwijk'),
(133,  'transfermarkt', 'Cambuur'),
(1435, 'transfermarkt', 'Go Ahead Eagles'),
(1269, 'transfermarkt', 'PEC Zwolle'),
(1455, 'transfermarkt', 'Dordrecht'),
(468,  'transfermarkt', 'Sparta'),
(1283, 'transfermarkt', 'Emmen'),
(385,  'transfermarkt', 'Fortuna Sittard'),
(724,  'transfermarkt', 'Volendam'),
(723,  'transfermarkt', 'Almere City'),
(1434, 'transfermarkt', 'Telstar');

-- WhoScored aliases: the 8 already confirmed (real, from tonight's
-- investigation + the pre-existing PSV Eindhoven fix already live in
-- aggregate_and_load_whoscored_season.py's TEAM_NAME_NORMALIZATION).
INSERT INTO team_name_alias (club_id, source, source_name) VALUES
(383,  'whoscored', 'PSV Eindhoven'),
(202,  'whoscored', 'FC Groningen'),
(200,  'whoscored', 'FC Utrecht'),
(1269, 'whoscored', 'PEC Zwolle'),
(306,  'whoscored', 'SC Heerenveen'),
(1304, 'whoscored', 'Heracles'),
(192,  'whoscored', 'Roda'),
(468,  'whoscored', 'Sparta Rotterdam');

-- FBref aliases: the confirmed correct-side spellings from the 7 pairs
-- above, where FBref's convention differs from Transfermarkt's.
INSERT INTO team_name_alias (club_id, source, source_name) VALUES
(468,  'fbref', 'Sparta R.'),
(1304, 'fbref', 'Heracles Almelo'),
(192,  'fbref', 'Roda JC');

-- AUTO-POPULATE: for every distinct team name FBref or WhoScored
-- actually uses, if that exact string already matches one of the 29
-- canonical Transfermarkt names above, register it as an alias
-- automatically. Zero guessing involved -- exact string equality only
-- -- but this should resolve the majority of the 29 clubs immediately
-- (most club names likely already agree across sources; only the
-- handful already found, plus whatever query 6/7 still surface, are
-- genuine mismatches). Safe to rerun -- UNIQUE(source, source_name)
-- makes this idempotent.
INSERT INTO team_name_alias (club_id, source, source_name)
SELECT canon.club_id, 'fbref', t.team
FROM (SELECT DISTINCT team FROM eredivisie_soccerdata_player_season_stats) t
JOIN team_name_alias canon ON canon.source = 'transfermarkt' AND canon.source_name = t.team
ON CONFLICT (source, source_name) DO NOTHING;

INSERT INTO team_name_alias (club_id, source, source_name)
SELECT canon.club_id, 'whoscored', t.team
FROM (SELECT DISTINCT team FROM eredivisie_whoscored_player_season_stats) t
JOIN team_name_alias canon ON canon.source = 'transfermarkt' AND canon.source_name = t.team
ON CONFLICT (source, source_name) DO NOTHING;

-- GAP REPORT: every distinct FBref/WhoScored team name that STILL has
-- no alias row after the auto-populate above -- these are the genuine
-- mismatches left to resolve by hand (via check_team_name_mismatches.sql
-- queries 6/7), same list that query would surface, but generated
-- directly against the live alias table so it's always current.
SELECT DISTINCT team, 'fbref' AS source
FROM eredivisie_soccerdata_player_season_stats
WHERE team NOT IN (SELECT source_name FROM team_name_alias WHERE source = 'fbref')

UNION ALL

SELECT DISTINCT team, 'whoscored' AS source
FROM eredivisie_whoscored_player_season_stats
WHERE team NOT IN (SELECT source_name FROM team_name_alias WHERE source = 'whoscored')

ORDER BY source, team;

-- GENERAL LOOSE MATCHING, not one-off hand-typed pairs. Every mismatch
-- found so far (Groningen/FC Groningen, Sparta/Sparta Rotterdam/
-- Sparta R., AZ/AZ Alkmaar, Zwolle/PEC Zwolle, Emmen/FC Emmen,
-- Volendam/FC Volendam, Dordrecht/FC Dordrecht, Almere City/Almere
-- City FC, VVV Venlo/VVV-Venlo) is one of three mechanical shapes: a
-- prefix word (FC/SC), a suffix word (Alkmaar/City/Rotterdam/FC), or a
-- hyphen-vs-space difference. This is codeable ONCE, not something
-- that needs discovering and hand-typing club by club as each new
-- season's data gets checked.
CREATE OR REPLACE FUNCTION loose_club_name(name TEXT)
RETURNS TEXT AS $$
    SELECT trim(regexp_replace(
        regexp_replace(
            regexp_replace(lower(name), '-', ' ', 'g'),  -- hyphen -> space
            '\s+', ' ', 'g'                                -- collapse whitespace
        ),
        '\y(fc|sc|vv)\y', '', 'g'                          -- drop prefix/suffix club-type words
    ))
$$ LANGUAGE sql IMMUTABLE;

-- PREVIEW (run this first, eyeball it): every FBref/WhoScored team name
-- still missing an alias, matched against the canonical Transfermarkt
-- name via loose_club_name() equality OR containment either direction.
-- Closed set of 29 clubs, so a human can and should glance at this
-- before trusting it -- not blind-inserted without review.
SELECT
    gap.team AS unmapped_name,
    gap.source,
    canon.club_id,
    canon.source_name AS matched_canonical_name
FROM (
    SELECT DISTINCT team, 'fbref' AS source
    FROM eredivisie_soccerdata_player_season_stats
    WHERE team NOT IN (SELECT source_name FROM team_name_alias WHERE source = 'fbref')
    UNION ALL
    SELECT DISTINCT team, 'whoscored' AS source
    FROM eredivisie_whoscored_player_season_stats
    WHERE team NOT IN (SELECT source_name FROM team_name_alias WHERE source = 'whoscored')
) gap
JOIN team_name_alias canon
    ON canon.source = 'transfermarkt'
    AND (
        loose_club_name(canon.source_name) = loose_club_name(gap.team)
        OR loose_club_name(gap.team) LIKE '%' || loose_club_name(canon.source_name) || '%'
        OR loose_club_name(canon.source_name) LIKE '%' || loose_club_name(gap.team) || '%'
    )
ORDER BY gap.source, gap.team;

-- APPLY: same join, actually inserted. Run only after eyeballing the
-- preview above shows sane matches (no unrelated clubs accidentally
-- catching each other's names).
INSERT INTO team_name_alias (club_id, source, source_name)
SELECT canon.club_id, gap.source, gap.team
FROM (
    SELECT DISTINCT team, 'fbref' AS source
    FROM eredivisie_soccerdata_player_season_stats
    WHERE team NOT IN (SELECT source_name FROM team_name_alias WHERE source = 'fbref')
    UNION ALL
    SELECT DISTINCT team, 'whoscored' AS source
    FROM eredivisie_whoscored_player_season_stats
    WHERE team NOT IN (SELECT source_name FROM team_name_alias WHERE source = 'whoscored')
) gap
JOIN team_name_alias canon
    ON canon.source = 'transfermarkt'
    AND (
        loose_club_name(canon.source_name) = loose_club_name(gap.team)
        OR loose_club_name(gap.team) LIKE '%' || loose_club_name(canon.source_name) || '%'
        OR loose_club_name(canon.source_name) LIKE '%' || loose_club_name(gap.team) || '%'
    )
ON CONFLICT (source, source_name) DO NOTHING;

-- Re-run the gap-report query further down after this -- whatever's
-- STILL unmapped after loose matching is a genuinely different naming
-- pattern (not prefix/suffix/hyphen-shaped) and needs a real look, not
-- another auto-rule guessed blind.

SELECT COUNT(*) FROM team_name_alias;
SELECT club_id, COUNT(*) AS alias_count FROM team_name_alias GROUP BY club_id ORDER BY alias_count DESC;

-- Lookup function: resolves any source's raw team-name string to the
-- canonical Transfermarkt club_id in one step. Returns NULL if the name
-- isn't registered as an alias for any source yet -- callers should
-- treat a NULL as "this name needs adding to team_name_alias", not
-- silently drop the row.
CREATE OR REPLACE FUNCTION normalize_team_id(p_source TEXT, p_team_name TEXT)
RETURNS INTEGER AS $$
    SELECT club_id FROM team_name_alias
    WHERE source = p_source AND source_name = p_team_name
    LIMIT 1;
$$ LANGUAGE sql STABLE;
