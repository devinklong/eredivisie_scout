# eredivisie_scout

A Python -> Postgres -> Docker/FastAPI -> Azure -> Power BI data pipeline analyzing historical Eredivisie player statistics, age, and physical attributes set against historical transfer purchases to the "big 5" leagues/perennial Champions League clubs to determine which players are over or undervalued. Data will be stored and modeled using scikit-learn/XGBoost/PyMC for predictive modeling to simulate the bar for value a player's profile is bought against.

## Project Status

Data extraction phase — Transfermarkt and soccerdata fully scraped and loaded into Postgres. WhoScored derivation logic built and verified across 3 seasons, not yet loaded. Model training not yet started.

### v1.0 data collection/extraction map

- `standard`/`shooting`/`misc`/`playing_time`/`keeper` (soccerdata) — **done, loaded into Postgres.** All 16 seasons (2010-11 to 2025-26), `eredivisie_player_season_stats` (9,229 rows) and `eredivisie_keeper_season_stats` (589 rows).
- Passing completion + progression (WhoScored-derived) — **done, verified across 3 seasons (2025-26, 2024-25, 2022-23), not yet loaded into Postgres.**
- Possession/touches by zone + take-ons (WhoScored-derived) — **done, same status as above.** `carries` specifically out of scope for v1 (needs SPADL output format).
- Defense: tackles/interceptions/clearances by zone (WhoScored-derived) — **done, same status as above.**
- Final-third/penalty-area entries as SCA proxy (WhoScored-derived) — **done, same status as above.** Pass-based only; carries-based entries out of scope for v1.
- Transfermarkt fees/market value/bio — **done, loaded into Postgres.** All 29 clubs that played Eredivisie since 2010-11, filtered to real Eredivisie seasons: `eredivisie_transfers` (8,060 rows), `eredivisie_club_status` (288 rows, the season-participation reference table). Market value *history* (not just current snapshot) and injury history not yet built.

### v1.5 (future)

- Composite "duel engagement" stat — Opta/WhoScored has no single event type matching the colloquial sense of "duel." It's assembled from several separate winner/loser event-type pairs across categories (`Aerial` win/loss, `Tackle` vs. `Dispossessed`/unsuccessful `TakeOn`, `Challenge` [always a loss] vs. the opponent's `TakeOn` [the win]). Building a true duel win-rate stat means combining these pairs deliberately, not pulling one column. See `docs/whoscored_qualifier_taxonomy.md`'s cross-event relationships table.
- Composite "successful take-on leading to a final-third/box entry" feature — a genuinely explosive, defender-beating carry is a stronger signal than an isolated `TakeOn` count or a generic final-third entry alone. Requires joining a `TakeOn` event to the same player's immediately following carry (by timestamp proximity), then checking whether that carry's end location lands in the final third/penalty area. Depends on carries existing first (see v1_roadmap.md's SPADL/carries item) — can't be built before that.
- Loan buy-option/obligation-to-buy distinction — confirmed not present in any Transfermarkt data scraped so far (fee data distinguishes paid/unpaid loans, but not whether a buy option or obligation is attached). Would need each player's individual transfer-detail page, likely reported in prose rather than a structured field.

### v2

xG or "advanced" metrics - deliberately deferred to test free data model's strength vs paywalled Opta-sourced data as of January 2026

## Overview

Borne from a strong passion for Ajax/the Eredivisie, this project determines which players are over or undervalued relative to what "big 5"/Champions League clubs actually pay for their archetype. Models like CIES and Transfermarkt already do this well, but at global scale, using coarse, generalized features across 70+ leagues. This project trades that breadth for depth: a single-league scope with domain-specific feature engineering (playing style, club context, role fit) that a generalist global model has no reason to build for one competition alone.

## Tech Stack

- **Language:** Python 3.13
- **Database:** PostgreSQL
- **ML/Modeling:** scikit-learn, XGBoost, PyMC
- **Container:** Docker & FastAPI
- **Version Control:** Git & GitHub CLI (`gh`)
- **Visualization/Reporting:** Power BI
- **Cloud Deployment:** Azure

## Data Sources

Two of three sources fully extracted and loaded into Postgres; the third is built and verified but not yet loaded.

- **FBref** (via the `soccerdata` library) — **done, loaded into Postgres.** standard, shooting, misc, playing-time, and keeper stats for all 16 seasons (2010-11 to 2025-26). Requires a Cloudflare-bypass approach (SeleniumBase UC/undetected-browser mode) — plain `requests`/`cloudscraper` are blocked. FBref's Opta-sourced advanced metrics (passing, possession, defense, goal/shot creation, and xG/xA across the board) were pulled sitewide in January 2026 after the data provider terminated FBref's license — confirmed empty across every season tested, so this isn't a scraper gap or a timing issue. One real data-quality bug found and fixed during loading (two FBref rows with genuinely inconsistent identity metadata for the same real player — see `docs/v1_roadmap.md`).
- **Transfermarkt** — **done, loaded into Postgres.** All 29 clubs that played Eredivisie since 2010-11: full multi-season transfer history (fees, categorized by type: permanent/loan/free/undisclosed/historical-unknown) plus current squad data (market value, bio). Plain `requests` works — no Cloudflare bypass needed for this site. Filtered against a manually-compiled season-participation reference table so only genuine Eredivisie-season transfers are counted. Not yet built: market value *history* (only current snapshot so far), injury history, loan buy-option/obligation-to-buy terms.
- **WhoScored** (via `soccerdata`, plus custom derivation logic on top) — **built and verified for 2020-21 through 2025-26, not yet loaded into Postgres.** Source of shot-level and general event data (location, body part, outcome) used to derive passing/possession/defense/final-third stats not otherwise available (see v1.0 map above), and the eventual path to an in-house xG model (v2). Requires the same Cloudflare-bypass approach as FBref. A confirmed library-level inefficiency (`read_events()` refetching the full season calendar on every call for an in-progress season) was root-caused and fixed with a `force_cache=True` parameter — see `docs/patch_list.md`. **Historical coverage below 2020-21 is mixed, not a clean cutoff:** 2019-20 is a genuine COVID-shortened season (season annulled mid-way, not a bug); 2015-16 through 2018-19 have real usable data but need a different parser than soccerdata's standard path provides (a working converter exists, not yet wired into the batch scraper); 2010-11 through 2014-15 appear to be largely genuine data gaps on WhoScored's own side, though not yet exhaustively confirmed. See `docs/v1_roadmap.md` and `docs/patch_list.md` for the full breakdown.

## v1 Data Sources Not Yet Used

- **FootyStats** — has real, confirmed Eredivisie xG/xA data from 2020/21 onward, via a paid API (~$36/month). Deliberately deferred to v2 as a one-time, bounded pull for comparing model performance with vs. without Opta-sourced advanced metrics. Their site's own Terms of Service explicitly prohibit scraping — API only.

## Folder Structure

```text
eredivisie_scout/
├── api/             # FastAPI app code for the deployed scoring/query service
├── cleaning_logs/   # Ambiguous name-matching or other data inconsistencies logs
├── config/          # Environment and connection settings (DB credentials, constants)
├── data/            # Raw and processed data files (ignored by git where applicable)
├── docs/            # Project documentation & any other methodology notes arising
├── models/          # Trained model artifacts only (serialized XGBoost models, PyMC traces)
├── notebooks/       # Exploratory analysis and prototyping (Jupyter)
├── pipelines/       # ETL and retrain/rescore pipeline code (extract -> clean -> train -> write back)
├── schema/          # Database schema only (tables, views, materialized views, migrations)
├── scripts/         # One-off/supporting scripts not part of a scheduled pipeline
│   ├── soccerdata/    # Scripts using the soccerdata library (covers both FBref and WhoScored)
│   ├── fbref/          # Custom FBref scraping, outside soccerdata's supported categories
│   ├── whoscored/       # Custom WhoScored logic beyond soccerdata's built-in read_* methods
│   └── transfermarkt/   # Transfermarkt scraping
├── tests/           # Testing of scripts/schema/views and any other machine learning code
│   ├── soccerdata/
│   ├── fbref/
│   ├── whoscored/
│   └── transfermarkt/
└── Dockerfile       # Container definition for the API and/or scheduled scoring job
```

**Source-folder convention:** `soccerdata/` holds anything using the `soccerdata` library, regardless of which site it's pulling from underneath. `fbref/`, `whoscored/`, and `transfermarkt/` hold custom, hand-written scraping/extraction logic for that source specifically — code written because the library doesn't cover it.

## Getting Started

Development environment: VS Code on macOS (Apple Silicon), Python 3.13 via `pyenv`, PostgreSQL via Homebrew.
Will update as the stack pipeline gets introduced in the project.

MIT License — see [LICENSE](LICENSE) for details.
