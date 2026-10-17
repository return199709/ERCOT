# ERCOT nodal basis and congestion analysis
#
# Typical first run:
#   cp .env.example .env && $EDITOR .env
#   make install
#   make ingest MONTH=2025-06
#   make analyze
#   make app

MONTH ?= 2025-06
DATASETS ?= dam_spp,rtm_spp,dam_shadow_prices,sced_shadow_prices,wind_by_region,solar_by_region,system_load

.PHONY: help install doctor env-check inspect-mapping summary ingest ingest-mapping backfill analyze app test lint quality views clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies with uv
	uv sync

doctor: ## Validate credentials, connectivity and column assumptions (run this first)
	uv run python -m src.ingest.preflight

ingest: ## Ingest one month (make ingest MONTH=2025-06)
	uv run python -m src.ingest.fetch --month $(MONTH) --datasets $(DATASETS)

ingest-mapping: ## Fetch the settlement point -> load zone mapping (needed for basis)
	uv run python -m src.ingest.fetch --month $(MONTH) --datasets settlement_point_mapping

inspect-mapping: ## Measure which mapping column is the settlement point, and whether ERCOT publishes a node->hub relationship
	uv run python -m src.ingest.inspect_mapping

env-check: ## Show which credential variables are set (names only, never values)
	@uv run python -c "from src.ingest.client import REQUIRED_VARS; from dotenv import load_dotenv, find_dotenv; import os; p=find_dotenv(); print('.env found at:', p or 'NOT FOUND'); load_dotenv(); [print(f'  {v}: ' + ('set' if os.getenv(v) else 'EMPTY or missing')) for v in REQUIRED_VARS]"

backfill: ## Ingest a date range (make backfill START=2023-10-01 END=2025-09-30)
	@test -n "$(START)" || (echo "START is required" && exit 1)
	@test -n "$(END)" || (echo "END is required" && exit 1)
	uv run python -m src.ingest.fetch --start $(START) --end $(END) --datasets $(DATASETS)

analyze: ## Run the transform and analysis pipeline
	uv run python -m src.run_analysis

app: ## Launch the Streamlit dashboard
	uv run streamlit run app/streamlit_app.py

test: ## Run the test suite
	uv run pytest -q

lint: ## Lint with ruff (same check CI runs)
	uv run ruff check src app tests

summary: ## Print a compact digest of every derived table (feeds the write-up)
	uv run python -m src.summary

quality: ## Show the generated data quality reports
	@ls -1 reports/quality/*.md 2>/dev/null || echo "No quality reports yet; run make analyze"

views: ## Register DuckDB views over the Parquet lake
	uv run python -c "from src import db; print(db.register_views())"

clean: ## Remove derived data (keeps raw pulls and the manifest)
	rm -rf data/processed data/ercot.duckdb
	@echo "Removed data/processed and the DuckDB file. data/raw is untouched."
