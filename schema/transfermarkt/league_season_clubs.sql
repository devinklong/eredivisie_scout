-- league_season_clubs.sql
-- Which clubs were in each Big-5 league in each season, 2010-2025. Scraped from
-- Transfermarkt's league-season pages by scrape_league_seasons.py and loaded by
-- load_league_season_clubs.py. Used to tell whether a transfer's BUYER was in a
-- Big-5 league that season. By season and not by club: a club's overview page
-- shows only its current league, which is wrong for historical transfers.
--
-- league_code is Transfermarkt's competition code: GB1 Premier League, ES1 La
-- Liga, IT1 Serie A, L1 Bundesliga, FR1 Ligue 1. season_id is the season's
-- starting year (2019 = 2019/20), the same convention as every other table in
-- this project. club_id is Transfermarkt's club id, the same id space as
-- buyer_club_transfers.own_club_id. club_name is display-only (Transfermarkt's
-- official names, including suffixes such as 'Brescia Calcio (- 2025)').
--
-- UNIQUE (season_id, club_id): a club plays in one top-flight league per season,
-- so a club appearing in two Big-5 leagues in the same season would mean a bad
-- scrape. The load fails loudly instead of storing it.
--
-- Absence from this table means "not in the Big 5 that season", which lumps
-- together other countries' top flights, lower divisions, and the Eredivisie.
--
-- CREATE TABLE IF NOT EXISTS, not DROP-first: deliberate, same reasoning as
-- buyer_club_transfers. To rebuild on purpose, DROP TABLE league_season_clubs
-- first, then run this file.

CREATE TABLE IF NOT EXISTS league_season_clubs (
    league_code  TEXT    NOT NULL CHECK (league_code IN ('GB1', 'ES1', 'IT1', 'L1', 'FR1')),
    season_id    INTEGER NOT NULL,
    club_id      INTEGER NOT NULL,
    club_name    TEXT,
    scraped_at   TIMESTAMP NOT NULL DEFAULT now(),
    PRIMARY KEY (league_code, season_id, club_id),
    UNIQUE (season_id, club_id)
);

CREATE INDEX IF NOT EXISTS league_season_clubs_club_idx ON league_season_clubs (club_id, season_id);
