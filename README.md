# eredivisie_scout

A Python -> Postgres -> Docker/FastAPI -> Azure -> Power BI data pipeline analyzing historical Eredivisie player statistics, age, and physical attributes set against historical transfer purchases to the "big 5" leagues/perennial Champions League clubs to determine which players are over or undervalued. Data will be stored and modeled using scikit-learn/XGBoost/PyMC for predictive modeling to simulate the bar for value a player's profile is bought against.

## Project Status

Data scoping phase — extraction sources confirmed, pipeline not yet built.

### v1.0 data collection/extraction map

- `standard`/`shooting`/`misc`/`playing_time` (soccerdata, already working)
- Passing completion + progression (WhoScored-derived)
- Possession/touches by zone + take-ons (WhoScored-derived)
- Defense: tackles/interceptions/blocks/clearances by zone (WhoScored-derived)
- Final-third/penalty-area entries as SCA proxy (WhoScored-derived, cheap)
- Transfermarkt fees/market value/bio/injury history

### v1.5 (future)

Composite "duel engagement" stat — Opta/WhoScored has no single event type matching the colloquial sense of "duel." It's assembled from several separate winner/loser event-type pairs across categories (`Aerial` win/loss, `Tackle` vs. `Dispossessed`/unsuccessful `TakeOn`, `Challenge` [always a loss] vs. the opponent's `TakeOn` [the win]). Building a true duel win-rate stat means combining these pairs deliberately, not pulling one column. See `docs/whoscored_qualifier_taxonomy.md`'s cross-event relationships table.

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

Still in the data-scoping phase — nothing built against these yet, this section reflects what's been confirmed feasible so far, not a finished integration.

- **FBref** (via the `soccerdata` library): standard, shooting, misc, playing-time, and keeper stats confirmed working. Requires a Cloudflare-bypass approach (SeleniumBase UC/undetected-browser mode) — plain `requests`/`cloudscraper` are blocked. FBref's Opta-sourced advanced metrics (passing, possession, defense, goal/shot creation, and xG/xA across the board) were pulled sitewide in January 2026 after the data provider terminated FBref's license — confirmed empty for both the current and a fully completed prior season, so this isn't a scraper gap or a timing issue.
- **Transfermarkt**: identified as the source for transfer fees, market values, bio data, and injury history. Not yet built.
- **WhoScored**: identified as the likely path to shot-level event data (location, body part, outcome) needed to train an in-house xG model, since FBref no longer provides it. Not yet built or confirmed scrapeable end-to-end.

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
│   └── transfermarkt/   # Transfermarkt scraping (not yet built)
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
