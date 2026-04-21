PYTHON ?= /opt/homebrew/bin/python3
VENV_PYTHON = .venv/bin/python
VENV_PIP = .venv/bin/pip
PYTHONPATHS=apps/ingester/src:apps/retriever/src:apps/mcp-server/src:apps/api/src:libs/core/src:libs/models/src:libs/file-ingest/src:libs/one-note/src
export PYTHONPATH=$(PYTHONPATHS)

.PHONY: bootstrap up down test lint format ingest watch watch-logs watch-down ingest-onenote search mcp api web-install web-dev web-build

bootstrap:
	$(PYTHON) -m venv .venv
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e ".[dev]"

up:
	docker compose -f infra/docker-compose.yml up -d postgres mcp-server api

down:
	docker compose -f infra/docker-compose.yml down

test:
	$(VENV_PYTHON) -m pytest

lint:
	$(VENV_PYTHON) -m ruff check .

format:
	$(VENV_PYTHON) -m ruff format .

ingest:
	$(VENV_PYTHON) -m second_brain_ingester.cli ingest-files

watch:
	docker compose -f infra/docker-compose.yml up -d postgres ingester-watch

watch-logs:
	docker compose -f infra/docker-compose.yml logs -f ingester-watch

watch-down:
	docker compose -f infra/docker-compose.yml stop ingester-watch

ingest-onenote:
	$(VENV_PYTHON) -m second_brain_ingester.cli ingest-onenote

search:
	$(VENV_PYTHON) -m second_brain_retriever.cli

mcp:
	$(VENV_PYTHON) -m second_brain_mcp_server.cli

api:
	$(VENV_PYTHON) -m second_brain_api.cli --host 127.0.0.1 --port $${SECOND_BRAIN_API_PORT:-8090}

web-install:
	cd apps/web && npm install

web-dev:
	cd apps/web && npm run dev

web-build:
	cd apps/web && npm run build
