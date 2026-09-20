-- fix_bad_heights.sql
-- Clears the two confirmed-implausible height_cm = 875 rows found in
-- the 2026-09-18 data-quality audit (player_ids 101810, 128168) --
-- almost certainly a decimal-parsing artifact in scrape_player_bio.py's
-- parse_height_cm(), not a real value.
--
-- DELETEs rather than UPDATEs to NULL: scrape_player_bio.py's own
-- query (get_distinct_player_ids) only fetches players NOT already
-- present in eredivisie_transfermarkt_player_bio -- deleting these
-- rows means the next run of that script automatically re-scrapes
-- them for real, rather than leaving a NULL that nothing will ever
-- revisit.

DELETE FROM eredivisie_transfermarkt_player_bio WHERE player_id IN (101810, 128168);

-- Confirm: should be 0.
SELECT COUNT(*) FROM eredivisie_transfermarkt_player_bio
WHERE height_cm IS NOT NULL AND (height_cm < 155 OR height_cm > 210);
