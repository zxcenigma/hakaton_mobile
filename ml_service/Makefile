.DEFAULT_GOAL := help
SHELL := /bin/bash

PY ?= python
VENV ?= .venv
ifeq ($(OS),Windows_NT)
	BIN := $(VENV)/Scripts
else
	BIN := $(VENV)/bin
endif

DBT_DIR := transform/dbt_monetka
DBT := $(BIN)/dbt --project-dir $(DBT_DIR) --profiles-dir $(DBT_DIR)

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ----------------------------------------------------------------- setup ---

.PHONY: install
install: ## Create the venv and install the project with dev extras
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip setuptools wheel
	$(BIN)/python -m pip install -e ".[dev,transform]"
	$(DBT) deps
	@echo "done — activate with: source $(BIN)/activate"

.PHONY: hooks
hooks: ## Install pre-commit hooks
	$(BIN)/pre-commit install

# ------------------------------------------------------------- pipeline ---

.PHONY: demo
demo: ## End-to-end local run, no containers (this is what CI runs)
	$(BIN)/monetka demo

.PHONY: generate
generate: ## Generate synthetic telemetry
	$(BIN)/monetka generate

.PHONY: elt
elt: ## bronze -> silver -> gold
	$(BIN)/monetka bronze
	$(BIN)/monetka silver
	$(BIN)/monetka gold

.PHONY: quality
quality: ## Run the data-quality and compliance checks
	$(BIN)/monetka quality

.PHONY: train
train: ## Train all models (fails if a quality gate fails)
	$(BIN)/monetka train

.PHONY: export
export: ## Export models to ONNX, with the parity check
	$(BIN)/monetka export

.PHONY: drift
drift: ## Feature drift report
	$(BIN)/monetka drift

.PHONY: monitor
monitor: ## Production model health + cohort comparison
	$(BIN)/monetka monitor

.PHONY: contracts
contracts: ## Regenerate the JSON Schema and Avro event contracts
	$(BIN)/monetka contracts

.PHONY: serve
serve: ## Run the API on :8000 (OpenAPI at /docs)
	$(BIN)/monetka serve --reload

# ------------------------------------------------------------------ dbt ---

.PHONY: dbt-docs
dbt-docs: ## Generate and serve the dbt documentation site
	$(DBT) docs generate
	$(DBT) docs serve --port 8088

.PHONY: dbt-test
dbt-test: ## Run the dbt test suite
	$(DBT) test

# ----------------------------------------------------------------- code ---

.PHONY: test
test: ## Run the test suite with coverage
	$(BIN)/pytest --cov=monetka --cov-report=term-missing --cov-report=xml

.PHONY: test-fast
test-fast: ## Run tests, skipping the ones that need the full stack
	$(BIN)/pytest -m "not integration and not slow"

.PHONY: lint
lint: ## ruff + mypy
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests
	$(BIN)/mypy

.PHONY: format
format: ## Auto-format and fix what ruff can fix
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

# ---------------------------------------------------------------- stack ---

.PHONY: stack-check
stack-check: ## Validate the compose stack without starting it (no daemon needed)
	$(BIN)/monetka stack-check

.PHONY: up
up: stack-check ## Start the lakehouse + API stack
	@test -f .env || cp .env.template .env
	docker compose up -d --build
	@echo ""
	@echo "  API        http://localhost:8000/docs"
	@echo "  SeaweedFS  http://localhost:9333/cluster/status  (S3 API on :9000)"
	@echo "  Trino      http://localhost:8080"
	@echo "  Redpanda   localhost:19092"

.PHONY: up-full
up-full: ## Start everything, including Airflow, MLflow and Grafana
	@test -f .env || cp .env.template .env
	docker compose --profile full up -d --build
	@echo ""
	@echo "  Airflow    http://localhost:8081"
	@echo "  MLflow     http://localhost:5000"
	@echo "  Grafana    http://localhost:3000"

.PHONY: down
down: ## Stop the stack
	docker compose --profile full down

.PHONY: clean-data
clean-data: ## Delete generated data, the warehouse and model artefacts
	rm -rf data artifacts $(DBT_DIR)/target $(DBT_DIR)/dbt_packages

.PHONY: nuke
nuke: down clean-data ## Stop everything and remove volumes
	docker compose --profile full down -v
