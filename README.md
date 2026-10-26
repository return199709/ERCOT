# ERCOT / energy data portfolio

Four end-to-end data projects on the Texas and U.S. power sector, each closing
a distinct set of skills (markets and modeling, cloud and orchestration,
governed Spark pipelines, APIs and policy) on a different public dataset.

| # | Project | Closes | Dataset | Status |
| - | --- | --- | --- | --- |
| 1 | [`ercot-basis-analysis`](ercot-basis-analysis) | ERCOT / power markets · Energy modeling · ETL / data pipelines | ERCOT Public API | Built, tested, run on June 2025; congestion attribution validated (median R² 0.97). See its [`reports/findings.md`](ercot-basis-analysis/reports/findings.md) |
| 2 | [`grid-disclosure-copilot`](grid-disclosure-copilot) | Azure · RAG / agents · Airflow | SEC EDGAR filings | Architecture only |
| 3 | [`grid-emissions-lakehouse`](grid-emissions-lakehouse) | Spark · Data quality / governance · GCP | EPA CAMPD + EIA | Architecture only |
| 4 | [`energy-policy-api`](energy-policy-api) | Databricks · REST / GraphQL APIs · Regulatory & policy | Federal Register + Regulations.gov | Architecture only |

"Architecture only" means a README, an `ARCHITECTURE.md` with the open
decisions and trade-offs, an `ASSUMPTIONS.md` checklist, and an empty
directory skeleton. No pipeline code has been written for projects 2-4.

Project 1's implementation and these docs now live together on the default
branch. The gap analysis was written on 2026-10 against an earlier branch
layout; its findings on scope and modelling still apply, its "branch
situation" section is historical, and the credential finding it raises has
been acted on (rotation and branch deletion).

## Start here

- [`docs/portfolio/GAP_ANALYSIS.md`](docs/portfolio/GAP_ANALYSIS.md): how
  project 1 maps to its objective today, what is missing, and a prioritized
  backlog. Includes a repository-hygiene finding about credentials in git
  history.
- [`docs/portfolio/PORTFOLIO_ARCHITECTURE.md`](docs/portfolio/PORTFOLIO_ARCHITECTURE.md):
  how the four projects fit together, the skills-to-proof matrix, role
  coverage, and sequencing.
- [`docs/portfolio/CONVENTIONS.md`](docs/portfolio/CONVENTIONS.md): shared
  rules, the write-up template, and the definition of done.

## Repository layout

Each project is self-contained so it can be split into its own public repo
later (for example with `git subtree split --prefix=<project>`).
