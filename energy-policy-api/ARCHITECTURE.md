# Architecture: energy-policy-api

Everything here is a proposal. Items marked **verify** rest on provider
details that should be checked against current documentation before building.

## 1. Goals and non-goals

**Goals**

- A queryable, well-modeled history of energy-sector regulatory events.
- One service layer exposed through both REST and GraphQL, each used where it
  fits.
- Policy analysis that is explicit about what the data can and cannot show.

**Non-goals**

- Legal advice or a legal research tool.
- Full-text search over the whole Federal Register.
- Causal claims about market effects. Case studies are descriptive.

## 2. Sources

| Source | Use | Access note (verify) |
| --- | --- | --- |
| Federal Register API | Rules, proposed rules, notices; agency, CFR references, dates, abstracts | Reported to need no API key; check rate and page-size limits |
| Regulations.gov API v4 | Dockets, documents, comment metadata and counts | Free api.data.gov key; roughly 1,000 requests per hour per key and about 5,000 records per query were reported, so ingestion must window by date |
| *Stretch:* ERCOT rule changes, Texas PUC filings | Texas market-specific events | Web pages without a clean API; check terms before scraping and treat as optional |

**Scope filter.** Energy-relevant agencies and CFR titles (for example EPA
air programs, FERC, DOE, Treasury guidance on energy credits), plus a keyword
list. Record the exact filter in `ASSUMPTIONS.md`; the filter *is* a modeling
decision.

## 3. Platform: Databricks

Unity Catalog three-level names: `energy_policy.bronze`, `.silver`, `.gold`.
Delta tables throughout. Declarative pipelines build silver and gold
(**verify** the current product name and features; it was previously called
Delta Live Tables). Deployment through a Databricks Asset Bundle
(`databricks/databricks.yml`) so the whole workspace state is code.

### Free Edition constraints that shape the design (verify all)

Reported limits to design around:

- Serverless compute only; no custom clusters.
- One active pipeline per pipeline type.
- One SQL warehouse, smallest size.
- Apps stop automatically after about 24 hours and must be restarted.
- Daily compute quota; non-commercial use.
- **Outbound internet from the workspace may be restricted** unless the
  account is verified. If so, ingestion cannot run inside Databricks.

**Consequence: ingest outside, process inside.** A scheduled GitHub Actions
job calls the public APIs and uploads JSON files to a Unity Catalog Volume
(through the Databricks CLI or Files API). Databricks does everything after
landing. This works whether or not outbound access is available, and the
write-up should say which constraint forced it (Decision 1).

## 4. Data model

| Layer | Table | Grain | Notes |
| --- | --- | --- | --- |
| Bronze | `fr_documents_raw`, `rg_documents_raw`, `rg_comments_raw` | One record per API item per fetch | Raw JSON plus `_ingested_at`, `_source_url`, `_batch_id` |
| Silver | `documents` | Federal Register document | Normalized fields, `document_type` (proposed rule, final rule, notice), publication date, CFR refs, abstract |
| Silver | `agencies`, `document_agencies` | Agency; document-agency link | Many-to-many |
| Silver | `dockets`, `docket_documents` | Docket; membership | Joins the two sources via docket id |
| Silver | `comments_daily` | Docket-day | Comment counts (metadata, not text) |
| Gold | `policy_events` | One regulatory event | Type, date, agencies, topics, docket, a stable `event_id` |
| Gold | `docket_activity` | Docket-day | Documents and comment volume, for timelines |
| Gold | `topic_tags` | Event-topic | Tag, method (rule / model), score |
| Gold | `events_x_market` *(optional)* | Event-window | Joins events to project 1's `mart_basis_daily` for descriptive windows |

### Tagging

- **Event type** from `document_type` and title patterns (high precision).
- **Topic** (for example power-sector emissions, interconnection and
  transmission, market rules and reliability, clean-energy tax credits) by a
  rules baseline on CFR references and keywords, then optionally an embedding
  or LLM-assisted tagger.
- **Measure it.** Hand-audit a random sample (50-100 events), report
  precision and the confusion between topics, and publish that number. An
  unmeasured classifier is a liability in a policy dataset.

## 5. API service

FastAPI. A single `services` layer holds the logic; REST and GraphQL are thin
adapters, so behaviour cannot drift between them.

**Data access.** Two modes behind one interface (Decision 4): a Parquet
snapshot exported from gold and queried with DuckDB (cheap, fast, works when
the workspace is asleep), or the Databricks SQL warehouse through its Python
connector (live, but cold starts and quota limits).

**REST `/v1`** (resource-oriented; best for lists, filters, exports,
time series):

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/events` | Filter by agency, topic, type, date range; cursor pagination |
| `GET /v1/events/{event_id}` | One event with linked docket |
| `GET /v1/dockets/{docket_id}/activity` | Time series of documents and comments |
| `GET /v1/topics` | Taxonomy |
| `GET /v1/events/{event_id}/market-window` *(optional)* | Descriptive market window, if project 1's mart is present |

**GraphQL `/graphql`** (best for navigating relationships in one request):
`events(filter, first, after)` returning nested `agencies`, `docket` with
`activity`, and `topics`. Use DataLoader-style batching to avoid N+1 queries.

**Cross-cutting.** Cursor pagination (stable ordering, opaque cursors); API
keys stored hashed; per-key rate limits; ETag / cache headers; RFC 9457
problem-details errors; OpenAPI published and versioned; a documented
deprecation policy; request IDs and structured logs.

**Testing.** Unit tests on the services with sample data; REST contract tests
generated from the OpenAPI schema (for example with Schemathesis); a GraphQL
schema snapshot test plus query tests; CI runs all of it with no Databricks.

**Hosting.** Databricks Apps if its Free Edition behaviour is acceptable
(reported auto-stop after about 24 hours), otherwise a free-tier container
host serving the snapshot. Say which in the write-up.

## 6. Policy analysis

The regulatory skill is shown in `docs/policy/`, not in the code:

- A **primer per case study**: what changed, who is affected, the mechanism by
  which it could reach prices or investment, and the exact data window.
- **Candidate case studies** (choose 2-3 and verify every fact before
  writing): ERCOT's RTC+B go-live on 2025-12-05 (confirmed by
  [ERCOT's release](https://www.ercot.com/news/release/12052025-ercot-goes-live));
  a FERC interconnection or transmission-planning order; an EPA power-sector
  emissions rule and its subsequent history.
- **Limits section in each**: weather, fuel prices, and other concurrent
  changes confound any before/after comparison, so present descriptive
  windows and say plainly what they do not establish.

## 7. Decisions to make (write each up as an ADR)

| # | Decision | Options | Leaning | Trade-off to document |
| - | --- | --- | --- | --- |
| 1 | Where ingestion runs | Inside Databricks; GitHub Actions to a Volume | GitHub Actions | Works regardless of workspace internet access; adds a second system to operate |
| 2 | Pipeline style | Declarative pipelines; plain Spark jobs | Declarative | Built-in expectations and lineage vs a Free Edition cap on active pipelines |
| 3 | Tagging method | Rules only; embeddings; LLM-assisted | Rules baseline, then optional model | Auditability and cost vs coverage; always report measured precision |
| 4 | API data access | Live SQL warehouse; Parquet snapshot | Snapshot, warehouse path optional | Freshness vs cost, cold starts, and quota |
| 5 | REST vs GraphQL | Both; one | Both, one service layer | REST for bulk and time series, GraphQL for nested navigation; double the contract surface to test |
| 6 | Auth and limits | API keys; OAuth; none | API keys, hashed, rate limited | Simplicity vs delegated access; enough for a public read-only demo |
| 7 | Comment text | Metadata only; ingest text | Metadata only | Text enables NLP but multiplies volume and invites misuse; start without |
| 8 | Market linkage | Include `events_x_market`; omit | Include, descriptive only | Valuable story vs risk of overclaiming causation |

## 8. Cost and risk

| Item | Note |
| --- | --- |
| Databricks | Free Edition is reported as no-cost but non-commercial and quota-limited (**verify**) |
| API hosting | Free-tier container host, or Databricks Apps |
| GitHub Actions | Within free minutes at a daily schedule |

| Risk | Mitigation |
| --- | --- |
| Free Edition limits change | Re-read the limits page before starting; keep the pipeline portable |
| API rate limits and result caps | Window requests by date; resume from a cursor; cache raw responses |
| Docket and document joins are incomplete across the two sources | Report join coverage as a data-quality metric |
| Misleading policy conclusions | Descriptive case studies only, with a limits section |
| Public API abuse | Rate limits, request size caps, read-only data |
