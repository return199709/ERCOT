# ercot-basis-analysis

Analysis of nodal basis and congestion in ERCOT. The project measures the
spread between settlement point prices at individual resource nodes and the
hubs they are referenced against — the *basis* — attributes that spread to
transmission congestion, and ranks the nodes and binding constraints that
matter most. Day-ahead and real-time settlement point prices, shadow prices,
wind and solar actuals and system load are pulled from the ERCOT Public API
via [`gridstatus`](https://github.com/gridstatus/gridstatus), landed as
partitioned Parquet, queried with DuckDB, and surfaced through a Streamlit
dashboard.

> **Current status:** the pipeline is built and tested (83 tests passing), but
> **no data has been ingested and no findings have been produced.** See
> [`reports/findings.md`](reports/findings.md).

## Setup

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and outbound network
access to `api.ercot.com`, `ercotb2c.b2clogin.com` and `www.ercot.com`.

```bash
cp .env.example .env     # then fill in your ERCOT credentials
make install
```

Register at [apiexplorer.ercot.com](https://apiexplorer.ercot.com/) and get a
subscription key from
[developer.ercot.com](https://developer.ercot.com/applications/pubapi/).

`.env` is gitignored and must never be committed. **Do not put real
credentials in `.env.example`** — that file is tracked and public.

Verify credentials with a single-day pull:

```bash
uv run python src/ingest/smoke_test.py
```

## Running it

```bash
make doctor                  # validate credentials, connectivity and columns FIRST
make ingest-mapping          # settlement point -> load zone (required for basis)
make ingest MONTH=2025-06    # validate on one month before backfilling
make analyze                 # transform, quality checks, all seven analyses
make app                     # Streamlit dashboard
make test                    # pytest
```

`make doctor` pulls a single day of every dataset and checks that the column
names this project depends on are actually present, so a feed whose schema has
changed surfaces in minutes rather than hours into a backfill. It reports
missing columns alongside the ones that did arrive, and never guesses a
substitute. Exit code 0 means a backfill is safe to start.

Backfill once one month looks right:

```bash
make backfill START=2023-10-01 END=2025-09-30
```

Ingest is **idempotent and resumable**: completed days are recorded in
`data/raw/_manifest.jsonl` and skipped on re-run, so an interrupted backfill
picks up where it stopped. Transient failures back off exponentially;
authentication and network-policy denials fail fast rather than retrying
pointlessly.

Expect roughly 75M+ rows (~1–2 GB Parquet) for 24 months of 15-minute RTM
prices across all settlement points.

## Analyses

| # | Question | Module |
|---|---|---|
| 1 | Basis distribution: mean, P5/P95, on/off-peak, by month and hour; worst 25 nodes | `src/analysis/basis_stats.py` |
| 2 | Year-over-year basis trend; nodes with widening negative basis | `src/analysis/trend.py` |
| 3 | Basis versus wind and solar output (West, Panhandle) | `src/analysis/renewables.py` |
| 4 | Negative price hours: count and share by node and month | `src/analysis/negative_prices.py` |
| 5 | Constraints ranked by congestion cost; seasonality; top 15 | `src/analysis/constraints.py` |
| 6 | DA–RT spread mean and volatility; persistent bias | `src/analysis/da_rt.py` |
| 7 | Storage screen: daily top-4 minus bottom-4 hour spread | `src/analysis/storage.py` |

## Layout

| Path | Contents |
| --- | --- |
| `src/ingest` | Credentialed clients, dataset registry, resumable day-by-day fetch |
| `src/transform` | DST-aware time handling, cleaning, quality checks, hub mapping, basis |
| `src/analysis` | The seven analyses above |
| `app` | Streamlit dashboard |
| `data/raw` | Untouched API pulls, partitioned by year/month (gitignored) |
| `data/processed` | Derived tables (gitignored) |
| `reports/quality` | Generated gap, duplicate and node-rename reports |
| `tests` | pytest suite over labelled synthetic fixtures |

## Data integrity rules

These are enforced in code, not just documented:

- **Gaps are reported, never filled.** No interpolation, no forward-fill, no
  zero-fill. Detection covers the full location x day grid, so a settlement
  point missing from a day *entirely* is caught, not just a short day --
  grouping alone misses the former. Whole absences and partial days are
  reported separately, as are locations that do not span the period because
  they were commissioned or retired mid-way.
- **Short days are not silently dropped either.** Per-interval statistics use
  the observations that exist and report `n` alongside every figure, so a
  node resting on thin data is visible. Day-level analyses that would be
  distorted by a short day guard explicitly: the storage screen returns NaN
  rather than a spread built from fewer than two disjoint windows.
- **Hub assignment is never guessed.** A node whose load zone is unknown is
  reported as unmapped and excluded, rather than attributed to a plausible hub.
- **DST is handled explicitly.** Expected interval counts are 23/92 on
  spring-forward days and 25/100 on fall-back days; all joins key on UTC.
- **Synthetic data is confined to tests** and is labelled as such. It never
  reaches a report.
- **Credentials are never printed.** Error messages name missing variables, not
  their values.

Every methodological choice is recorded in [`ASSUMPTIONS.md`](ASSUMPTIONS.md).
