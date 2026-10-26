# Architecture: grid-emissions-lakehouse

Everything here is a proposal. Items marked **verify** rest on data-source or
provider details that should be checked before building.

## 1. Goals and non-goals

**Goals**

- A medallion pipeline whose correctness is *demonstrated*: contracts, gates,
  quarantine, reconciliation.
- Governance on a managed platform: catalog, lineage, quality scans, access.
- An honest, measured answer to whether Spark is justified for this data.

**Non-goals**

- A real-time or streaming pipeline.
- Orchestration with Airflow. Project 2 covers that; this project submits jobs
  from CI or Cloud Workflows to avoid duplicating it and to keep cost down.
- Official emissions accounting. Outputs are analytical, not regulatory.

## 2. Sources

| Source | Use | Access note (verify) |
| --- | --- | --- |
| EPA CAMPD hourly emissions | Unit-level hourly CO₂ mass, gross load, heat input, measurement flags | Bulk data files for large pulls; an API key from api.data.gov is needed for the API |
| EIA plant / unit metadata (EIA-860, or EPA eGRID) | Plant attributes, fuel, balancing authority | Used to filter to ERCOT's footprint, since state = TX is not the same as ERCOT |
| EIA hourly generation by balancing authority and fuel | Denominator for grid carbon intensity | Needs a free EIA API key |

**Scale.** The nationwide hourly CEMS record is large (tens of millions of
rows per year is the planning estimate; measure it). That is what makes Spark
a defensible choice, but see Decision 1 for the honest counter-argument.

## 3. Medallion layers

Storage: partitioned Parquet (ZSTD) on GCS for bronze and silver; BigQuery for
gold.

| Layer | Table | Grain | Notes |
| --- | --- | --- | --- |
| Bronze | `cems_hourly_raw` | One row per unit-hour as published | Typed, append-only, partitioned by year and month; source file and load id recorded |
| Bronze | `plant_meta_raw` | Per plant / unit per release | Kept per release for history |
| Silver | `cems_hourly` | Unit-hour, deduplicated | Standardized timestamps, units, flags; passes gates |
| Silver | `units` | One row per unit | Conformed identifiers and attributes |
| Silver | `cems_hourly_rejects` | Unit-hour | Failed rows with `reason_code`, `rule_id`, `load_id` |
| Gold | `emission_rate_unit_month` | Unit-month | tCO₂ per MWh (gross-load basis) and completeness |
| Gold | `fleet_emissions_hourly` | Balancing authority-hour | Summed CEMS CO₂ for the in-footprint fleet |
| Gold | `mart_carbon_intensity_hourly` | Balancing authority-hour | Fleet CO₂ ÷ total generation; the cross-project contract |

### Domain pitfalls the design must handle

These are the quality problems worth showing off. Confirm each against the
CAMPD data dictionary (**verify**):

- **Units.** Mass units in the published data may be short tons, not metric
  tonnes. Convert once, in silver, and record the unit.
- **Time.** Hour stamps are local to the plant and may be standard time with
  no daylight-saving shift. Convert to UTC in one place and test the DST
  boundary days.
- **Substituted and missing data.** When a monitor is down, reported values
  are substituted. Carry the measurement flag through to gold and report the
  measured share, so intensity numbers can be qualified.
- **Gross vs net, fossil only.** CEMS covers fossil units and reports gross
  load. Dividing by *total* generation (EIA) mixes bases, so the mart is a
  *fossil-fleet-attributed intensity*, and the assumption is documented.
- **Identifier drift.** Units and plants get renumbered or retired. Keep a
  conformed key and test that history joins.

## 4. Data contracts and quality

One YAML contract per table, in `contracts/`, as the single source of truth:

```yaml
# illustrative shape, not final
table: silver.cems_hourly
version: 1.0.0
owner: you
grain: [facility_id, unit_id, hour_utc]
freshness: { max_lag_days: 14 }
columns:
  - { name: co2_mass_tonnes, type: double, nullable: true, min: 0 }
  - { name: gross_load_mw,   type: double, nullable: true, min: 0 }
rules:
  - id: co2_without_load
    description: CO2 reported while gross load is zero or null needs a flag
    severity: warn
```

Quality runs in five layers:

| Layer | Where | Checks | On failure |
| --- | --- | --- | --- |
| Contract | CI | Schema validity; no unversioned breaking changes | Build fails |
| Row gates | Spark, bronze → silver | Non-null keys, ranges, valid timestamps, unit sanity | Row goes to quarantine with a reason; job continues |
| Dataset checks | Spark, silver and gold | Uniqueness of the grain; completeness (expected vs actual hours per unit-month); volume vs trailing average; freshness | Fail or warn by severity |
| Reconciliation | Gold | Annual unit CO₂ vs an independent EPA/EIA total, within a tolerance | Report; flag outliers |
| Platform | BigQuery | Dataplex quality scans on gold, results visible in the catalog | Scorecard drops; alert |

Publish a **quality scorecard** (rejection rate by rule, completeness, measured
share, freshness) as the project's front page for this skill.

### Governance

- **Ownership and docs:** every table has an owner and descriptions in the
  contract; push them to the catalog.
- **Lineage:** Dataproc Serverless to BigQuery lineage is reported as
  available (**verify** the setup); show a lineage graph screenshot.
- **Access:** one service account per layer with least privilege; no
  user-level grants in Terraform.
- **Change management:** semantic versions on contracts; a breaking change
  needs a new major version and a migration note.
- **Classification:** public data, no personal information; say so explicitly.

## 5. Infrastructure and execution

- **Terraform:** GCS buckets (landing, bronze, silver, quarantine), BigQuery
  datasets, service accounts and IAM, Dataproc Serverless batch config,
  Dataplex scans, and a budget alert. `apply` and `destroy` must both work.
- **Run:** `gcloud dataproc batches submit pyspark` from a GitHub Actions
  workflow or a small script, with parameters for year and month.
- **Local and CI:** `pyspark` in local mode on `data/sample`, so tests run with
  no cloud access.
- **Idempotency:** each run writes to a deterministic partition and overwrites
  only that partition.

## 6. Decisions to make (write each up as an ADR)

| # | Decision | Options | Leaning | Trade-off to document |
| - | --- | --- | --- | --- |
| 1 | Is Spark justified? | PySpark on Dataproc Serverless; BigQuery SQL only; both with a benchmark | Build in Spark, benchmark against BigQuery SQL | BigQuery may well do the same transforms cheaper and faster. Publish the numbers; either result is a valid finding |
| 2 | Table format | Plain partitioned Parquet; Iceberg or Delta on GCS | Plain Parquet | Simplicity vs ACID and schema evolution; mention Iceberg as the upgrade path |
| 3 | Quality tooling | Custom PySpark checks; Great Expectations; Soda; Deequ; Dataplex scans | Custom gates driven by contracts, plus Dataplex for the platform layer | Control and testability vs a maintained rule library; revisit if the rule count grows |
| 4 | Where rejects go | Drop; flag in place; quarantine table | Quarantine | Storage and review effort vs never silently losing rows |
| 5 | Footprint filter | State = TX; balancing authority = ERCOT | Balancing authority | Correctness vs simplicity; the state filter includes non-ERCOT plants |
| 6 | Intensity definition | Fossil CEMS ÷ total generation; fossil only ÷ fossil only | First, with caveats | Closer to "grid intensity" vs mixed gross/net bases |
| 7 | Orchestration | CI workflow; Cloud Workflows; Cloud Composer | CI workflow | Cost and scope vs a managed scheduler; Composer is costly and duplicates project 2 |
| 8 | Partitioning and file size | Year/month; add state; target file size | Year/month | Avoid the small-files problem; show file counts in the benchmark |

## 7. Benchmark plan (Decision 1)

Run the same silver + gold transforms three ways on the same data volume:
local Spark, Dataproc Serverless, and BigQuery SQL. Record wall-clock time,
approximate cost, lines of code, and ease of testing. Report where each wins.
Include one run at the full multi-year volume if the free tier allows.

## 8. Cost and risk

| Item | Note |
| --- | --- |
| GCS and BigQuery | Free-tier allowances exist but are region- and volume-dependent (**verify**); keep storage in a free-tier region |
| Dataproc Serverless | Billed by compute used; the main cost. Use sample-sized runs for development |
| Dataplex scans | Billed through BigQuery and Dataproc usage (**verify**) |
| Budget alert | Set before the first resource |

| Risk | Mitigation |
| --- | --- |
| Bulk file layout or API changes | Pin the download date and file list in the manifest |
| Unit or time-zone mistakes | Explicit tests on known plants and DST boundary days |
| Spark overkill for the data | Treat as a finding; benchmark (Decision 1) |
| Cost surprises | Budget alert, sample-first, `terraform destroy` verified |
| Governance features drift or rename | Screenshot early; record the date and product name in the write-up |
