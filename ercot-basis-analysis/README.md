# ercot-basis-analysis

Analysis of nodal basis and congestion in ERCOT. The goal is to measure and
explain the spread between settlement point prices at individual resource
nodes and the hubs or load zones they settle against — the "basis" — and to
attribute that spread to transmission congestion. Day-ahead and real-time
settlement point prices are pulled from the ERCOT Public API via
[`gridstatus`](https://github.com/gridstatus/gridstatus), landed as Parquet,
queried with DuckDB, and surfaced through a Streamlit app alongside written
reports.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Fill in `.env` with your ERCOT Public API credentials. Register for an
   account at [apiexplorer.ercot.com](https://apiexplorer.ercot.com/) and
   obtain a subscription key via
   [developer.ercot.com](https://developer.ercot.com/applications/pubapi/).
   `.env` is gitignored and must never be committed.

3. Install dependencies:

   ```bash
   uv sync
   ```

4. Verify credentials and connectivity:

   ```bash
   uv run python src/ingest/smoke_test.py
   ```

## Layout

| Path              | Contents                                        |
| ----------------- | ----------------------------------------------- |
| `src/ingest`      | Pulls from the ERCOT API, writes to `data/raw`   |
| `src/transform`   | Cleaning and reshaping into `data/processed`     |
| `src/analysis`    | Basis and congestion calculations                |
| `app`             | Streamlit app                                    |
| `data/raw`        | Untouched API pulls (gitignored)                 |
| `data/processed`  | Derived tables (gitignored)                      |
| `tests`           | pytest suite                                     |
| `reports`         | Written findings                                 |

Assumptions and methodology decisions are recorded in
[`ASSUMPTIONS.md`](ASSUMPTIONS.md).
