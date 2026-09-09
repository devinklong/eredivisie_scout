-- eredivisie_transfermarkt_player_bio.sql
-- Physical attributes (height, preferred foot) scraped from
-- Transfermarkt player profile pages. Confirmed via a real page
-- (transfermarkt.com/frenkie-de-jong/profil/spieler/326330, 2026-09-07)
-- that Transfermarkt does NOT track player weight -- only height and
-- foot are available here, nothing more.
--
-- IMPORTANT: use the transfermarkt.com domain, NOT transfermarkt.us --
-- confirmed the .us domain renders height in feet/inches (e.g.
-- "5 ft 11 in"), while .com renders clean metric (e.g. "1,81 m",
-- comma decimal separator -- convert to a period before parsing to
-- NUMERIC). Scraping from .com avoids needing to parse/convert
-- imperial units at all.
--
-- Keyed on Transfermarkt's own numeric player_id -- the same
-- player_id already used as the real, clean join key in
-- eredivisie_transfers (unlike FBref/WhoScored, which have no numeric
-- ID and need the fuzzy-matching crosswalk instead). One row per
-- player -- height/foot don't vary by season, so this is a snapshot
-- table, not a per-season one, matching how market value is already
-- treated elsewhere in this project (current snapshot, not history).

DROP TABLE IF EXISTS eredivisie_transfermarkt_player_bio CASCADE;

CREATE TABLE eredivisie_transfermarkt_player_bio (
    player_id       INTEGER PRIMARY KEY,   -- Transfermarkt's numeric player ID -- same ID space as eredivisie_transfers.player_id
    height_cm        SMALLINT,              -- parsed from e.g. "1,81 m" -> 181. NULL if Transfermarkt has no height listed for this player (confirmed real gap for lower-profile/youth players -- not every profile has this filled in)
    foot              TEXT,                  -- 'right', 'left', 'both', or NULL if not listed -- stored lowercase, exactly as Transfermarkt itself displays it, not remapped to any other convention
    scraped_at         TIMESTAMP NOT NULL DEFAULT now()
);

-- No hard foreign key to eredivisie_transfers enforced here, same
-- convention as that table's own relationship to eredivisie_club_status --
-- join at query time instead.

SELECT COUNT(*) FROM eredivisie_transfermarkt_player_bio;
