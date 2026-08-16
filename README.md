# eredivisie_scout

A Python -> Postgres -> Docker/FastAPI -> Azure -> Power BI data pipeline analyzing historical Eredivisie player statistics, age, and physical attributes set against historical transfer purchases to the "big 5" leagues/perennial Champions League clubs to determine which players are over or undervalued. Data will be stored and modeled using scikit-learn/XGBoost/PyMC for predictive modeling to simulate the bar for value a player's profile is bought against.

## Project Status

Just starting the scope, nothing built yet.

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

In progress

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
├── tests/           # Testing of scripts/schema/views and any other machine learning code
└── Dockerfile       # Container definition for the API and/or scheduled scoring job
```

## Getting Started

Development environment: VS Code on macOS (Apple Silicon), Python 3.13 via `pyenv`, PostgreSQL via Homebrew.
Will update as the stack pipeline gets introduced in the project.

MIT License — see [LICENSE](LICENSE) for details.
