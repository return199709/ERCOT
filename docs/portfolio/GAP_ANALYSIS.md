# Project 1 gap analysis: `ercot-basis-analysis` vs. the objective

> **Read with its date in mind.** Written when project 1 sat on an unmerged
> branch and had not been run on real data. Since then: the pipeline has been
> merged to the default branch and run on June 2025, the on-peak window was
> corrected, 59 unmapped nodes were recovered, congestion attribution was
> built and validated (backlog item 4), CI and secret scanning were added
> (item 6), and the credential finding was acted on. Items 1 (multi-month
> backfill), 7 (demo data), 9 and 10 remain open.

**Objective (from the "Projects to build" list):** an end-to-end project that
uses **ERCOT / power markets**, **Energy modeling**, and **ETL / data
pipelines** together, shipped as a public repo with a README, a short write-up
of the decisions and trade-offs, and a live demo or screenshots.

## What was audited

| | |
| --- | --- |
| Code audited | Branch `claude/ercot-pipeline` at `d760e0c` (10 commits beyond the scaffold) |
| What I ran | `uv sync --frozen` and `pytest` on a clean export of that commit: **161 tests pass** |
| What I could not run | Ingest and analysis against real ERCOT data. The sandbox cannot reach ERCOT's hosts, which is the same block the project's own `findings.md` describes |

Everything below about behaviour on real data is therefore read from code and
docs, not observed.

### Branch situation (read this first)

| Branch | What it holds |
| --- | --- |
| `claude/ercot-basis-project-setup-44541a` (the repo's **default** branch) | Scaffold only: one smoke test, an empty `ASSUMPTIONS.md`, empty folders |
| `claude/ercot-pipeline` | The actual project: ~5,000 lines of ingest, transform, analysis, dashboard, and tests |
| `claude/sharp-euler-q6dp2f` (this branch) | Cut from the scaffold, plus these portfolio docs |

The two project-1 branches diverged at `8671621`. Anyone opening the repo's
default branch sees a scaffold, not the finished pipeline. **Merging
`claude/ercot-pipeline` into the default branch is the single cheapest
improvement to how the project reads.**

## Verdict

**The engineering is strong and unusually honest; what is missing is
evidence.** The pipeline is built and tested, the methodology is documented to
a professional standard, but it has never run against real prices, so there
are no findings, no charts, and no demo. Two real modeling and market gaps
remain beyond that (below).

| Skill | State | One-line reason |
| --- | --- | --- |
| ERCOT / power markets | **Strong, unproven on data** | Deep, correct-looking domain handling; RTC+B regime change not addressed |
| Energy modeling | **Partly met** | A real dispatch model exists; congestion attribution and any forward-looking element do not |
| ETL / data pipelines | **Strong, no CI** | Idempotent resumable ingest, DST-aware quality checks; no automation or gates that fail |
| Deliverables | **Not yet shippable** | README honest; write-up empty by design; no demo without data |

## Skill-by-skill mapping

### 1. ERCOT / power markets

**Evidence in the code and docs:**

- Seven datasets registered against verified `gridstatus` 0.36.0 methods: DAM
  and real-time SPP, DAM and SCED shadow prices, wind and solar by region,
  system load, plus the settlement-point mapping.
- `ASSUMPTIONS.md` (16 sections) records the choices that matter: ERCOT
  publishes no node-to-hub mapping, so hub assignment by load zone is an
  explicit assumption with the four NOIE zones flagged as weakest links;
  basis is also computed against every reference hub so conclusions can be
  re-cut; on-peak is defined as 5×16 with NERC holidays; DST is handled with
  23/25-hour day counts and UTC joins; shadow prices are normalized to
  $-hours so 5-minute SCED and 1-hour DAM intervals are comparable; wind and
  solar region taxonomies are confirmed to differ and are not compared
  region-for-region.
- Data-integrity rules are enforced in code and covered by tests: gaps are
  reported and never filled, including wholly absent location-days.

**Gaps:**

- **No real data has been ingested.** Every assumption in `ASSUMPTIONS.md` is
  marked unvalidated for that reason.
- **The RTC+B regime change is not addressed.** A search of the branch finds
  no mention of it. ERCOT went live with real-time co-optimization plus
  batteries on 2025-12-05
  ([ERCOT release](https://www.ercot.com/news/release/12052025-ercot-goes-live)),
  moving ancillary-service procurement into the real-time market. The
  README's example backfill (2023-10-01 to 2025-09-30) ends before it, which
  may be deliberate; if the window is later extended, pre- and post-go-live
  data must not be pooled silently. Decide the window explicitly and record
  it as a new section in `ASSUMPTIONS.md`. A pre/post comparison could itself
  be a headline result.
- **The `basis` table is DAM-only** (hourly). Real-time prices enter only the
  DA–RT spread analysis. That is a defensible scope, but the write-up should
  say so.

### 2. Energy modeling

**Evidence:**

- `dispatch.py` solves battery operation by dynamic programming over a
  discretized state of charge, with power and energy limits, round-trip loss,
  and a throughput cost. `ASSUMPTIONS.md` §15 compares it with the simpler
  top-4-minus-bottom-4 screen on constructed days, states plainly that
  perfect foresight makes it an upper bound and not a backtest, and lists
  what it omits (ancillary revenue, price impact).
- `dispatch_decomposition` splits revenue into what a hub-located battery
  would earn from the system-wide price shape versus the node's own basis.
- Seven descriptive analyses cover basis distribution, trend, renewable
  co-movement, negative prices, constraint ranking, DA–RT bias, and storage.

**Gaps:**

| Gap | Why it matters |
| --- | --- |
| **No congestion attribution.** Constraints are ranked system-wide by cost; nothing links a node's basis to the constraints that drive it. | The project's stated goal ("attributes that spread to transmission congestion") is only half delivered. Public data has no shift factors, so a regression of node basis on binding-constraint shadow prices is the natural estimation, with its assumptions documented |
| **Everything is in-sample and ex-post.** | A forecast-based or rolling-horizon dispatch next to the perfect-foresight run would give a "value of foresight" number and turns an upper bound into something closer to an estimate |

Congestion attribution is the higher-value item: it completes the project's
own stated question.

### 3. ETL / data pipelines

**Evidence:**

- Day-by-day fetch that is idempotent and resumable through
  `data/raw/_manifest.jsonl`; exponential backoff for transient errors; fast
  failure on authentication and network-policy denials.
- A `preflight` check (`make doctor`) that validates credentials,
  connectivity, and expected columns on one day of every dataset before a
  long backfill.
- Raw data as year/month-partitioned Parquet, DuckDB views over it, a
  transform layer with DST-aware time handling, and quality reports for gaps,
  duplicates, and settlement-point changes.
- A `Makefile` covering install, doctor, ingest, backfill, analyze, app, test.

**Gaps:**

- **No CI and no secret scanning.** There is no `.github/` directory and no
  pre-commit configuration. Tests only run when someone runs them.
- **Quality checks report; they do not gate.** The checks write reports and
  warn, but nothing fails a run or marks a table as untrusted past a
  threshold. Whether that is right is a design decision worth recording
  either way.
- **No scheduled refresh.** Acceptable for a portfolio project, but say so,
  because "data pipeline" invites the question.

## Deliverables check

| "You ship" item | State | Gap |
| --- | --- | --- |
| Public repo with README | README is thorough and truthful about status | Not on the default branch; the "83 tests" figure is stale (161 pass); the repo description reads "poker game simulation" |
| Short write-up of decisions and trade-offs | `ASSUMPTIONS.md` is most of the *decisions* half; `reports/findings.md` is intentionally empty | Needs the *results* half. Template: [`CONVENTIONS.md`](CONVENTIONS.md) |
| Live demo or screenshots | Five-tab Streamlit app exists and degrades gracefully without data | Cannot be demonstrated until data is ingested; plus a demo-data decision |

**Demo-data decision.** `.gitignore` excludes `data/**`, `*.parquet` and
`*.duckdb`, and the ERCOT API needs credentials, so a hosted Streamlit app
cannot rebuild its data. Options: (a) commit a small curated processed
snapshot through an explicit `.gitignore` exception, (b) publish it as a
GitHub Release asset the app downloads, (c) screenshots only. Option (b) keeps
the repo small and the demo live.

## The critical path

Everything that remains is blocked on one thing: **ingesting real data.** The
project's own `findings.md` reports that the build container's network policy
denies `api.ercot.com`, `ercotb2c.b2clogin.com`, `www.ercot.com`, and
`sso.ercot.com` at the TLS tunnel, before authentication. Two ways through:

1. Run `make doctor`, then `make ingest MONTH=2025-06`, on a machine with
   normal internet access.
2. Or allow those four hosts in the cloud environment's network settings
   (Edit environment, Network access, Allowed domains).

## Repository hygiene

Findings in git history, not in the working tree of `claude/ercot-pipeline`:

- Commit `9860ee1` added `ercot-basis-analysis/.env` containing **non-empty
  values for the username, password, and subscription key**; `1b136f4` stopped
  tracking it, but the values remain in history.
- Commit `7f93f3f` filled `.env.example` with values that do not look like
  placeholders (a 22-character username and a 15-character password). On the
  default branch that file is still in that state.
- Those commits are in the history of the **default branch**
  (`claude/ercot-basis-project-setup-44541a`) and of this branch.
  `claude/ercot-pipeline` branched earlier and **does not contain them**, and
  its `.env.example` is clean.
- The repository is **private**, which limits exposure today.

I did not print or test any value. Whether they are real is the owner's to
check; the safe assumption is that they are. Recommended order:

1. **Rotate** the ERCOT API password and subscription key.
2. Replace the default branch's `.env.example` values with placeholders (the
   `ercot-pipeline` version already is).
3. **Before anything is made public:** either scrub history
   (`git filter-repo` plus force-push, which rewrites shared history and is the
   owner's call), or publish from the clean `ercot-pipeline` lineage, for
   example `git subtree split --prefix=ercot-basis-analysis` on that branch.
   The second needs no history rewrite.
4. Add a secret scanner (`gitleaks`) as a pre-commit hook and CI check.

## Prioritized backlog to finish project 1

| # | Item | Closes |
| --- | --- | --- |
| 0 | Rotate credentials; placeholder `.env.example` on the default branch | Hygiene |
| 1 | Get ERCOT network access; run `make doctor`, then one month, then backfill | Unblocks everything |
| 2 | Decide the analysis window around the 2025-12-05 RTC+B go-live; add it to `ASSUMPTIONS.md` | Markets |
| 3 | `make analyze`; read `reports/quality/`; validate the unvalidated assumptions against real data | Markets, ETL |
| 4 | Congestion attribution: regress node basis on binding-constraint shadow prices | Modeling |
| 5 | Write `reports/findings.md` with one chart per question | Write-up |
| 6 | CI (lint plus tests) and `gitleaks`; fix the NumPy timedelta deprecation warnings in the tests; correct the README test count | ETL hygiene |
| 7 | Demo-data decision, then hosted app or screenshots | Demo |
| 8 | Merge `claude/ercot-pipeline` into the default branch; fix the repo description | Presentation |
| 9 | *Optional:* forecast-based dispatch vs perfect foresight; hard quality gates | Modeling, ETL |
| 10 | *For cross-project use:* build `mart_basis_daily` (see below) | Portfolio links |

## Contract for the other projects

The other projects optionally read a daily basis table. **It does not exist
yet.** The closest existing table is `basis` (DAM, node-hourly, with
`basis` against the assigned hub and `basis_vs_<HUB>` columns). The proposed
contract, to be derived from it in `src/analysis/`:

| Column | Notes |
| --- | --- |
| `date` | Central Prevailing Time delivery date |
| `settlement_point` | Resource node |
| `assigned_hub` | From the load-zone mapping |
| `mean_basis`, `p05_basis`, `p95_basis` | Daily, $/MWh |
| `n_intervals` | Observed count, so thin days are visible |

See [`PORTFOLIO_ARCHITECTURE.md`](PORTFOLIO_ARCHITECTURE.md) for who consumes it.
