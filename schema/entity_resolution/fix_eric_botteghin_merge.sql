-- fix_eric_botteghin_merge.sql
-- Run this in TWO STEPS since not all SQL clients support psql's
-- :variable substitution syntax.

-- STEP 1: run this block first, alone. It returns one row with a
-- player_id column -- note that number, you'll need it in step 2.
INSERT INTO players (canonical_name) VALUES ('Eric Botteghin')
RETURNING player_id;

SELECT player_id FROM players WHERE canonical_name = 'Eric Botteghin';

-- STEP 2: replace the literal number 999 below (in all three places)
-- with the actual player_id STEP 1 returned, then run this block.
INSERT INTO player_source_crosswalk
    (player_id, source, source_name, confidence, match_method, verified, notes)
VALUES
    (1710, 'fbref', 'Eric Botteghin', NULL, 'manual_review', TRUE,
     'Verified via Wikipedia (2026-09-07): full name Eric Fernando Botteghin, one real person'),
    (1710, 'whoscored', 'Eric Botteghin', 1.0, 'exact_normalized', TRUE,
     'Short-form spelling used by WhoScored in some seasons'),
    (1710, 'whoscored', 'Eric Fernando Botteghin', 0.7568, 'manual_review', TRUE,
     'Full-form spelling used by WhoScored in other seasons -- same real person, verified via Wikipedia');


-- STEP 3 (sanity check): confirm both WhoScored spellings now point to
-- the same player_id.
SELECT * FROM player_source_crosswalk WHERE source_name ILIKE '%botteghin%';

