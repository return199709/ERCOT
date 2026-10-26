# Architecture: grid-disclosure-copilot

Everything here is a proposal. Items marked **verify** rest on provider
details that should be checked against current documentation before building.

## 1. Goals and non-goals

**Goals**

- Cited answers over SEC filings, with abstention when evidence is missing.
- A measurable quality bar (a golden set with published metrics).
- An orchestrated, idempotent ingestion pipeline.
- An Azure deployment defined as code, runnable on free or near-free tiers.

**Non-goals**

- Investment advice or financial analysis.
- Real-time filing alerts.
- Fine-tuning models.
- Replacing project 1's market analysis; the optional SQL tool only *reads*
  its output.

## 2. Corpus

- **Source:** SEC EDGAR (`data.sec.gov` submissions API plus filing
  documents). It is free; it requires a descriptive `User-Agent` and enforces
  a request-rate limit (**verify** the current limit and fair-access policy).
- **Companies:** 5-8 ERCOT-active generators and retailers chosen up front and
  recorded in `ASSUMPTIONS.md`, rather than "all utilities".
- **Forms and sections:** 10-K and 10-Q first. Within them, prioritize risk
  factors, MD&A, and business / regulation sections. 8-K only if time allows.
- **Period:** from 2021 forward, which covers the February 2021 winter storm
  and the market-rule changes since.

## 3. Pipeline (Airflow)

Use Airflow's TaskFlow API and dynamic task mapping; use its dataset/asset
feature to chain DAGs (**verify** the naming in the Airflow version you pick).

| DAG | Trigger | Does | Idempotency key |
| --- | --- | --- | --- |
| `ingest_filings` | Daily; backfill by date | List new filings per CIK, download documents to Blob | accession number |
| `parse_chunk` | Asset update | HTML → sections → chunks with metadata | accession + parser version |
| `embed_index` | Asset update | Embed new/changed chunks, upsert to the index, delete removed ones | chunk content hash |
| `evaluate_rag` | Weekly; on demand | Run the golden set against the live stack; write metrics | run id |

Design rules:

- Every task is safe to rerun. Writes are keyed upserts, never appends.
- Re-parsing with a new parser version must not duplicate chunks.
- A DAG failing mid-run leaves the index consistent (write, then swap
  pointers or tag by version).
- Airflow runs locally in Docker Compose for development. Hosting it in Azure
  is a documented option, not a requirement (see Decision 6).

## 4. Data model

Chunk record (stored as Parquet in Blob and as an index document):

| Field | Notes |
| --- | --- |
| `chunk_id` | Hash of `accession_no + section + offset` |
| `content_hash` | Hash of the text; drives incremental re-embedding |
| `accession_no`, `cik`, `ticker`, `form_type` | Filing identity |
| `filing_date`, `period_end` | Enables "since 2021" style filters |
| `section` | e.g. risk factors, MD&A |
| `char_start`, `char_end` | Offsets into the source document, used for citations |
| `source_url` | Link back to the filing |
| `text`, `token_count` | |
| `embedding` | Vector; dimension is a cost lever (Decision 5) |
| `parser_version`, `embedding_model` | Reproducibility |

## 5. Serving

- **API:** FastAPI on Azure Container Apps (scale to zero). `POST /ask`
  returns `{answer, citations[], abstained, trace_id}`.
- **UI:** Streamlit, matching project 1, to keep the effort on retrieval.
- **Identity:** managed identity to Blob, AI Search, and OpenAI; secrets in
  Key Vault; no keys in app settings.
- **Observability:** OpenTelemetry to Application Insights. Log retrieval
  results, tool calls, token counts, and latency per request.

### Agent design

A fixed pipeline first (retrieve, answer with citations), then an agent that
adds tool routing only if evaluation shows a gain.

| Tool | Behaviour | Guardrails |
| --- | --- | --- |
| `search_filings(query, filters)` | Hybrid retrieval, returns passages with citation metadata | Result count capped; metadata filters validated |
| `query_market_data(sql)` *(optional)* | Read-only DuckDB over a project 1 Parquet snapshot | Allowlisted views, `SELECT` only, row limit, timeout |

**Prompt injection.** Filing text is untrusted data. It is delivered to the
model as quoted evidence, never as instructions, and no tool call may be
triggered by retrieved content alone. Test this explicitly with a planted
instruction in a sample filing.

## 6. Evaluation (the centrepiece)

- **Golden set:** 40-60 hand-written questions with the passages that answer
  them, including 10+ **unanswerable** questions (the right behaviour is to
  abstain) and several multi-filing comparison questions.
- **Metrics:**
  - Retrieval: recall@k, MRR.
  - Answer: citation precision (does the cited passage support the claim),
    faithfulness (LLM judge, **calibrated against a hand-labelled subset** and
    reported with that agreement rate), abstention accuracy.
  - Operations: latency and cost per query.
- **Comparisons to publish:** vector-only vs hybrid; fixed chunks vs
  structure-aware; fixed pipeline vs agent. Negative results are useful.
- **Regression gate:** `evaluate_rag` fails the DAG if a key metric drops
  below a threshold set from the baseline run.

## 7. Decisions to make (write each up as an ADR)

| # | Decision | Options | Leaning | Trade-off to document |
| - | --- | --- | --- | --- |
| 1 | Retrieval mode | Vector only; hybrid (BM25 + vector); hybrid + semantic reranker | Hybrid | The semantic ranker is reportedly not on the AI Search Free tier (**verify**), so the reranker costs a paid tier |
| 2 | Chunking | Fixed-size windows; structure-aware by filing section | Structure-aware | Better citations and filters vs a parser that breaks on formatting variation |
| 3 | Agent or fixed pipeline | Fixed; agent with tools | Fixed baseline, then agent | An agent adds latency, cost, and failure modes; keep it only if evals show a gain |
| 4 | LLM provider | Azure OpenAI; another model hosted on Azure | Azure OpenAI behind a thin provider interface | Availability of other vendors' models on Azure changes, so keep the interface (**verify**) |
| 5 | Index size and tier | AI Search Free vs Basic; embedding dimension | Free for dev | Free is reported at about 50 MB (**verify**); a 1,536-dimension float32 vector is about 6 KB, so only roughly 8,000 chunks fit before text and overhead. Options: shorter embeddings, fewer sections, or a paid tier |
| 6 | Airflow hosting | Local Docker Compose with recorded runs; self-host in Azure | Local + recorded runs | Cost and ops burden vs a "production" claim; say which one you did |
| 7 | Vector store | AI Search; Postgres with pgvector | AI Search | Azure-native and hybrid out of the box vs a fixed monthly cost; pgvector is cheaper to keep but less managed |
| 8 | Judge model | Same model as generator; different model | Different | Self-preference bias vs extra cost |

## 8. Infrastructure (Bicep)

Resource group containing: Storage account (Blob), AI Search, Azure OpenAI
(embedding + chat deployments), Container Apps environment and app, Key Vault,
Log Analytics / Application Insights, managed identity role assignments.
Include `infra/teardown.sh` and a cost-management budget alert.

## 9. Cost and risk

| Item | Note |
| --- | --- |
| Azure OpenAI | Dominated by embedding the corpus once and by eval runs. Budget it; cache embeddings by content hash |
| AI Search | Free tier for dev; a paid tier costs a fixed monthly amount (**verify** current price); tear down after the demo |
| Container Apps | Scale to zero; expected to be small at demo traffic |
| Airflow | Local; no cloud cost |

| Risk | Mitigation |
| --- | --- |
| EDGAR rate limits or blocking | Declare a `User-Agent`, throttle, cache raw downloads |
| HTML structure varies by company and year | Parser tests per company; log unparsed filings rather than dropping them silently |
| Judge unreliability | Calibrate on hand labels; report agreement |
| Prompt injection from filings | Treat as data; test with a planted instruction |
| Demo cost after the project ends | Teardown script; consider a recorded demo plus screenshots instead of an always-on endpoint |
