# HN Pulse

[![pipeline](https://github.com/VasilenData/hn-pulse/actions/workflows/pipeline.yml/badge.svg)](https://github.com/VasilenData/hn-pulse/actions/workflows/pipeline.yml)

An end-to-end data engineering project: a scheduled pipeline snapshots the Hacker News front page, models it with **dbt** (with automated data tests), and publishes a **live dashboard**.

**Live dashboard: https://vasilendata.github.io/hn-pulse/**

**Stack:** Python · DuckDB · dbt · Apache Airflow · GitHub Actions · GitHub Pages

## Architecture

```mermaid
flowchart LR
    A[Hacker News API] -->|extract.py<br/>top 100 stories| B[(data/raw_snapshots.csv<br/>append-only history)]
    B --> C[dbt: staging -> fact -> marts<br/>DuckDB]
    C -->|15 data tests| D{tests pass?}
    D -->|yes| E[export.py -> docs/data.json]
    E --> F[GitHub Pages dashboard]
    G[Airflow DAG hourly<br/>local orchestration] -.-> A
    H[GitHub Actions<br/>every 3h, free hosting] -.-> A
```

## Why this design
- **Append-only raw layer.** Every run adds a timestamped snapshot, so history is never overwritten and any model can be rebuilt from scratch.
- **dbt layers.** `stg_snapshots` (typing, domain parsing, de-duplication) -> `fct_stories` (one row per story with peak score and time on the front page) -> four marts that feed the dashboard.
- **Tests gate publishing.** `dbt build` runs 15 data tests (not null, unique, a custom `rank_in_window` test); if any fail, the dashboard data is not updated.
- **Two orchestrators, same code.** The Airflow DAG (`dags/hn_pulse_dag.py`) shows the production pattern: `extract >> dbt_build >> export`, with retries and no overlapping runs. GitHub Actions runs the same steps on a cron so the live dashboard needs no server.
- **Python unit tests** cover the parsing logic (`test_extract.py`), including dead/deleted items and text posts.

## Run it

Without Docker:
```bash
git clone https://github.com/VasilenData/hn-pulse.git && cd hn-pulse
pip install -r requirements.txt
pytest -q                 # unit tests
python run_pipeline.py    # extract -> dbt build -> export
open docs/index.html      # needs a local server: python -m http.server -d docs
```

With Airflow (Docker):
```bash
docker compose up --build
# http://localhost:8080 , enable the hn_pulse DAG
```

## Project layout
```
extract.py            Hacker News API -> data/raw_snapshots.csv
models/               dbt models and schema tests
tests/generic/        custom dbt test
export.py             marts -> docs/data.json
dags/hn_pulse_dag.py  Airflow DAG
docs/                 static dashboard (GitHub Pages)
.github/workflows/    scheduled pipeline + publishing
```

## Possible next steps
Swap DuckDB for a cloud warehouse (BigQuery or Snowflake) by changing the dbt profile, and add story-level trend features.

---
Built by [Vasilen Kanchev](https://vasilendata.github.io) · [LinkedIn](https://www.linkedin.com/in/vasilenkanchev/)
