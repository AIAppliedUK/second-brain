# second-brain

Local-first second brain built around PostgreSQL + pgvector, PostgreSQL full-text search with `tsvector`, local files and OneNote as input sources, hybrid RAG retrieval, and an MCP server for Codex and Claude.

## What v1 includes

- Python 3.12-oriented project layout with app and library boundaries
- Docker Compose for local PostgreSQL with `pgvector`
- `sources`, `chunks`, and `audit_log` schema with provenance-first fields
- first-class memory scopes for general and project-specific memories in one stack
- Hybrid retrieval using lexical `tsvector` search, vector similarity, and metadata filters
- Local file ingestion for markdown, txt, pdf, and docx
- OneNote ingestion through Microsoft Graph delegated authentication only
- stdio MCP server exposing `search_memory`, `get_source`, `get_chunk_context`, and `list_sources`
- Tests for chunking, retrieval, ingestion, OneNote sync logic, and MCP service behaviour

## Repository layout

```text
second-brain/
  apps/
    ingester/
    retriever/
    mcp-server/
  libs/
    core/
    models/
    file-ingest/
    one-note/
  infra/
    docker-compose.yml
    postgres/init.sql
  tests/
```

## Local setup

1. Use Python 3.12 for local development. The code also compiles on newer Python versions, but v1 targets 3.12.
2. Copy `.env.example` to `.env` and fill in the OneNote delegated auth settings if you plan to sync OneNote.
   The shared configuration layer auto-loads `.env` for normal local runs, so you do not need to manually export each variable first.
3. Create a virtual environment and install dependencies:

```bash
make bootstrap
```

4. Start PostgreSQL:

```bash
make up
```

By default, the container binds PostgreSQL to host port `55432` instead of `5432`, so it should not clash with other local databases. If you want a different host port, change `SECOND_BRAIN_DB_PORT` in your local `.env`.

The database comes up with `pgvector` enabled and initializes:

- `sources` as the canonical source record table
- `chunks` as retrieval units with `embedding` and generated stored `tsv`
- `audit_log` for ingestion and indexing events

### Scoped memories

This build supports separate memory scopes in one local stack.

A practical setup is:

- `general` for your reusable notes and reference material
- `project:second-brain` for this repo's docs, architecture patterns, onboarding notes, and other project files

The file ingester can ingest multiple scoped roots. Example:

```env
SECOND_BRAIN_DEFAULT_MEMORY_SCOPE=project:second-brain
SECOND_BRAIN_MEMORY_ROOTS=project:second-brain|.;general|~/second-brain/general
```

That lets you ingest the whole supported project folder into `project:second-brain` while keeping personal or shared notes in `general`. Retrieval can stay project-focused by filtering on `memory_scope`.

## Why PostgreSQL uses both pgvector and tsvector

PostgreSQL is the retrieval system of record in v1. `chunks.tsv` is a generated stored `tsvector` column built from `chunk_text` and indexed with GIN. That means lexical search is not optional or bolted on later; it is part of the base schema and query path. `chunks.embedding` stores local embeddings in a `vector(256)` column indexed with `ivfflat`.

Retrieval works as:

1. Run lexical retrieval with `websearch_to_tsquery` and `ts_rank_cd`
2. Run vector retrieval with `pgvector` cosine similarity
3. Apply memory-scope, metadata, and source filters to both paths
4. Merge both candidate sets with weighted reciprocal-rank fusion
5. Return citations and provenance with every hit

## Ingestion workflow

### Local files

- Recursively walk configured folders
- Extract canonical text from markdown, txt, pdf, and docx
- Hash file contents to detect changes
- Preserve source path, timestamps, and extraction metadata
- Chunk content with heading-aware handling for markdown
- Write canonical source, chunks, and audit events to PostgreSQL
- Log failures without stopping the overall ingest run
- Skip unchanged files using stored metadata and content hashes
- Support polling-based watch mode for incremental local updates

### OneNote

OneNote ingestion uses Microsoft Graph delegated authentication only. v1 intentionally does not implement app-only auth.

- Authenticate via OAuth device code flow
- Read notebooks, sections, and pages from `/me/onenote/...`
- Preserve notebook, section, and page identifiers in metadata
- Store raw HTML plus cleaned canonical text
- Support incremental sync with `lastModifiedDateTime`
- Retry on Graph throttling responses

## Running services

```bash
make ingest
make watch
make ingest-onenote
make search query="project notes"
make mcp
```

The CLI equivalents are:

```bash
python3 -m second_brain_ingester.cli ingest-files
python3 -m second_brain_ingester.cli watch-files --interval 2.0
python3 -m second_brain_ingester.cli ingest-onenote --since 2025-01-01T00:00:00Z
python3 -m second_brain_retriever.cli "hybrid retrieval"
python3 -m second_brain_mcp_server.cli
```

`watch-files` uses a boring polling loop. It is designed for local reliability and incremental updates: unchanged supported files are skipped, changed files are reindexed, and new files are ingested.

`list_sources` is intentionally lightweight: it returns source summaries for navigation, not full raw document bodies. Use `get_source` when you want the full stored source record.

## Quality checks

```bash
make format
make lint
make test
```

## Environment variables

- `SECOND_BRAIN_DB_PORT`: host port mapped to the container's PostgreSQL `5432`
- `SECOND_BRAIN_DB_DSN`: PostgreSQL DSN for all apps
- `SECOND_BRAIN_EMBEDDING_DIMENSION`: vector size, default `256`
- `SECOND_BRAIN_DEFAULT_MEMORY_SCOPE`: default scope used for scoped ingest fallback and MCP retrieval
- `SECOND_BRAIN_MEMORY_ROOTS`: semicolon-separated `scope|path` entries for scoped local ingest
- `SECOND_BRAIN_FILE_ROOTS`: comma-separated directories for local ingest
- `SECOND_BRAIN_MCP_SERVER_NAME`: stdio MCP server name
- `SECOND_BRAIN_ONENOTE_TENANT_ID`: Entra tenant, use `common` for multi-tenant delegated login
- `SECOND_BRAIN_ONENOTE_CLIENT_ID`: public client app id for delegated Graph auth
- `SECOND_BRAIN_ONENOTE_SCOPES`: delegated Graph scopes
- `SECOND_BRAIN_ONENOTE_REDIRECT_URI`: redirect URI registered for the public client
- `SECOND_BRAIN_ONENOTE_TIMEOUT_SECONDS`: auth and API timeout
- `SECOND_BRAIN_ONENOTE_USER_AGENT`: Graph client user agent
- `SECOND_BRAIN_ONENOTE_MEMORY_SCOPE`: scope to assign to ingested OneNote content

Use [`.env.example`](/Users/davidmcnabb/projects/second-brain/.env.example) as the template for your real local `.env`, and keep that real `.env` out of version control.

## Notes

- The default embedder is intentionally local and deterministic so v1 can work without cloud dependencies. It is a quality baseline, not the final ranking ceiling.
- The MCP server is stdio-first and designed so a later HTTP transport can wrap the same service layer without changing retrieval logic.
- Update [docs/architecture.md](/Users/davidmcnabb/projects/second-brain/second-brain-starter/docs/architecture.md) if architectural decisions change.
