# Roadmap

## Phase 1 - Scaffold

Delivered:

- Python 3.12-targeted project structure across `apps/`, `libs/`, `infra/`, and `tests/`
- Docker Compose with PostgreSQL and `pgvector`
- shared config and structured logging
- pytest and Ruff configuration
- `.env.example`
- `Makefile`
- README and docs updates

## Phase 2 - Database and retrieval

Delivered:

- SQL initialization for `sources`, `chunks`, and `audit_log`
- generated stored `tsv` column on `chunks`
- GIN and vector indexes
- repository layer for source, chunk, and audit operations
- hybrid retrieval service with lexical plus vector merge logic
- tests for lexical query generation, vector query generation, and merge behaviour

## Phase 3 - Local file ingestion

Delivered:

- recursive file discovery
- content hashing
- extraction for markdown, txt, pdf, and docx
- canonical source writer inputs
- heading-aware markdown chunking
- failure logging without whole-run crashes
- tests for local file ingestion flows

## Phase 4 - OneNote ingestion

Delivered:

- Microsoft Graph delegated auth via device code flow
- notebook, section, and page sync model
- HTML-to-text normalization
- incremental sync parameter support
- throttling retry transport
- mocked tests for Graph-backed sync logic

## Phase 5 - MCP server

Delivered:

- stdio-first MCP adapter using the Python MCP SDK
- tool definitions for:
  - `search_memory`
  - `get_source`
  - `get_chunk_context`
  - `list_sources`
- transport-agnostic service layer
- tests for core MCP tool behaviour

## Phase 6 - Hardening

Current hardening in this pass:

- provenance-first source and chunk models
- audit events for ingestion operations
- deterministic embeddings for stable local behaviour
- boring architecture with minimal moving parts

Next hardening steps:

1. Add integration tests against a live PostgreSQL container
2. Add source tombstoning and explicit delete workflows
3. Improve PDF extraction diagnostics for scanned documents
4. Add stronger auth token caching for delegated Graph sessions
5. Consider upgrading the local embedder to a stronger offline model

## Review checklist

Before extending this baseline, check for:

- edge cases
- broken abstractions
- over-engineering
- missing tests
- weak naming
- provenance gaps
- security concerns
