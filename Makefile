PYTHON ?= /opt/homebrew/bin/python3
VENV_PYTHON = .venv/bin/python
VENV_PIP = .venv/bin/pip
PYTHONPATHS=apps/ingester/src:apps/retriever/src:apps/mcp-server/src:libs/core/src:libs/models/src:libs/file-ingest/src:libs/one-note/src
export PYTHONPATH=$(PYTHONPATHS)

.PHONY: bootstrap up up-https down test lint format ingest watch ingest-onenote search mcp

bootstrap:
	$(PYTHON) -m venv .venv
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install -e ".[dev]"

up:
	docker compose -f infra/docker-compose.yml up -d postgres mcp-server

up-https:
	docker compose -f infra/docker-compose.yml up -d postgres mcp-server https-proxy

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
	$(VENV_PYTHON) -m second_brain_ingester.cli watch-files

ingest-onenote:
	$(VENV_PYTHON) -m second_brain_ingester.cli ingest-onenote

search:
	$(VENV_PYTHON) -m second_brain_retriever.cli

mcp:
	$(VENV_PYTHON) -m second_brain_mcp_server.cli
