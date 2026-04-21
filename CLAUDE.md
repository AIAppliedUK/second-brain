# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Dev Commands

```bash
make bootstrap          # Create .venv, install deps (Python 3.12+)
make up                 # Start PostgreSQL + MCP server in Docker
make down               # Stop all Docker containers
make test               # Run pytest
make lint               # Ruff check
make format             # Ruff format
make ingest             # One-off local file ingestion
make watch              # Start Dockerized file watcher (polls every 15s)
make ingest-onenote     # Sync OneNote pages (requires Microsoft Entra setup)
make mcp                # Start MCP server on stdio
make search             # Query memory via retriever CLI
```

Run a single test: `.venv/bin/python -m pytest tests/test_file.py::test_name`

## Architecture

**Monorepo** with a single `pyproject.toml`. All packages use editable install. PYTHONPATH is set in the Makefile to include all source roots.

### Apps (entry points)

- **ingester** (`apps/ingester/src/second_brain_ingester/`) — CLI for file and OneNote ingestion
- **retriever** (`apps/retriever/src/second_brain_retriever/`) — CLI for searching memory
- **mcp-server** (`apps/mcp-server/src/second_brain_mcp_server/`) — MCP server exposing `search_memory`, `get_source`, `get_chunk_context`, `list_sources`
- **api** (`apps/api/src/second_brain_api/`) — FastAPI server exposing `/api/*` endpoints for the React web client and optional static frontend delivery

### Libs (shared)

- **core** (`libs/core/src/second_brain_core/`) — Database, retrieval, config, chunking, embeddings, logging
- **models** (`libs/models/src/second_brain_models/`) — Pydantic domain models (`SourceRecord`, `ChunkRecord`, `SearchRequest`, `CanonicalDocument`, etc.)
- **file-ingest** (`libs/file-ingest/src/second_brain_file_ingest/`) — Local file extraction (md, txt, pdf, docx, code files) and ingestion
- **one-note** (`libs/one-note/src/second_brain_one_note/`) — Microsoft Graph OneNote integration

### Data flow

1. Ingester discovers files → extracts content → chunks with heading-aware splitting (220 target words, 40 overlap)
2. Deterministic embeddings via SHA256 + token frequency (no external API, dimension=256)
3. Upserts `sources` and `chunks` in PostgreSQL (pgvector), skips unchanged files by content hash
4. Retriever runs hybrid search: lexical (`websearch_to_tsquery` on `chunks.tsv`) + vector (cosine similarity), merged via reciprocal-rank fusion (0.45 lexical / 0.55 vector)

### Key tables (in `infra/postgres/init.sql`)

- `sources` — one row per document, unique on `(memory_scope, source_type, external_id)`
- `chunks` — retrieval units with embedding + generated stored `tsvector`
- `audit_log` — ingestion event tracking

### Memory scopes
Isolate memories within one DB instance. Configured via `SECOND_BRAIN_MEMORY_ROOTS` env var using `scope|path;scope|path` format. Both ingestion and retrieval respect scope filters.

## Code Conventions

- **Ruff** for linting and formatting: line-length 100, double quotes, rules E/F/I/B/UP/N/SIM
- **Pydantic** for domain models, **dataclasses with `slots=True`** for simple internal types
- **Repository pattern**: `SourceRepository`, `ChunkRepository`, `AuditRepository` with parameterized psycopg queries
- **Config**: `Settings` dataclass in `libs/core/.../config.py`, auto-loads `.env`, all env vars prefixed `SECOND_BRAIN_`
- **Logging**: `configure_logging()` + `get_logger(__name__)`, structured extras via `extra={"extras": {...}}`
- **Type hints** throughout

## Docker Setup

Docker Compose (`infra/docker-compose.yml`) runs:

- **postgres**: pgvector on `127.0.0.1:55432`
- **mcp-server**: streamable-http on `127.0.0.1:18000`
- **api**: FastAPI plus the built React UI on `127.0.0.1:18090`
- **ingester-watch**: polling watcher

## Testing

Tests in `tests/`. Most tests mock the database — no live PostgreSQL required. pytest config in `pyproject.toml` sets all source roots in `pythonpath`.
