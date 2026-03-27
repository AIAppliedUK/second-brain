# second-brain

Local-first memory infrastructure for AI agents and personal knowledge retrieval.

This project ingests local files and, when Microsoft Entra plus Microsoft Graph
delegated auth are configured, OneNote content into PostgreSQL. It indexes that
content with both `pgvector` and PostgreSQL full-text search, and exposes the
memory through an MCP server for Claude and Codex.

Important: local file ingestion is the straightforward path. OneNote sync is
not zero-config and requires separate Microsoft Entra setup before
`ingest-onenote` will work.

## What it does

This is a read-mostly second brain with PostgreSQL as the system of record for retrieval.

It is designed to help with:

- project memory for codebases, docs, architecture notes, and ADRs
- general memory for personal notes and reference material
- hybrid retrieval for agents that need both exact-match and semantic recall
- provenance-first answers with citations back to the original source and chunk

The core flow is:

1. ingest content from local files or OneNote
2. normalize it into canonical source records
3. chunk and index it in PostgreSQL
4. query it with hybrid lexical plus vector retrieval
5. expose it to AI tools through MCP

## Key capabilities

- PostgreSQL with `pgvector` and generated stored `tsvector`
- hybrid retrieval using:
  - lexical search with `websearch_to_tsquery` and `ts_rank_cd`
  - vector similarity with `pgvector`
  - metadata and memory-scope filters
- local file ingestion with incremental change detection
- OneNote ingestion via Microsoft Graph delegated auth only, with separate
  Microsoft Entra app registration required
- memory scopes so one stack can serve multiple project memories plus a general memory
- stdio MCP server exposing:
  - `search_memory`
  - `get_source`
  - `get_chunk_context`
  - `list_sources`
- provenance and citations on retrieval results
- tests for chunking, retrieval, ingestion, OneNote sync, and MCP behavior

## How it works

### Storage model

The database has three main tables:

- `sources`
  - one canonical row per source document or OneNote page
  - stores metadata, timestamps, content hash, title, URI, and raw/canonical content
- `chunks`
  - retrieval units derived from a source
  - stores chunk text, heading path, metadata, embedding, and generated stored `tsv`
- `audit_log`
  - ingestion and indexing events

### Retrieval model

Retrieval is hybrid by design, not vector-only.

For each search request the retriever:

1. runs lexical search against `chunks.tsv`
2. runs vector search against `chunks.embedding`
3. applies the same memory-scope and metadata filters to both
4. merges both candidate sets with weighted reciprocal-rank fusion
5. returns results with source metadata and citation payloads

### Memory scopes

Memory scopes let you keep multiple memories separate while using one local stack.

Typical scopes:

- `general`
- `project:second-brain`
- `project:ai-recruitment`

This means you can use one Postgres instance and one MCP server, but still retrieve only the memory relevant to the current project.

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

## Setup

### 1. Requirements

- Python 3.12 is the target baseline for the project
- Docker Desktop or equivalent Docker runtime
- if you want OneNote sync, a Microsoft Entra app registration with delegated
  Microsoft Graph permissions

Newer Python versions may work, but the documented target is Python 3.12.

### 2. If you need OneNote, set up Microsoft Entra first

OneNote sync depends on an existing Microsoft Entra app registration. Copying
`.env.example` is not enough by itself.

1. Create or choose a Microsoft Entra app registration for delegated sign-in.
2. Configure delegated Microsoft Graph permissions for `Notes.Read.All`,
   `User.Read`, and `offline_access`.
3. Note the app's client ID and the tenant you want to authenticate against.
4. Then continue with the local project setup below and place those values in
   `.env`.

If you only want local file ingestion, you can skip this step.

### 3. Configure local environment

Copy [`.env.example`](/Users/davidmcnabb/projects/second-brain/.env.example) to [`.env`](/Users/davidmcnabb/projects/second-brain/.env).

```bash
cp .env.example .env
```

The config layer auto-loads `.env`, so you do not need to manually export each variable.

If you are not using OneNote, you can leave the OneNote settings empty.

### 4. Bootstrap the project

```bash
make bootstrap
```

### 5. Start PostgreSQL

```bash
make up
```

By default, PostgreSQL binds to host port `55432` so it does not clash with local databases already using `5432`.

## Environment variables

Important settings:

- `SECOND_BRAIN_DB_PORT`
- `SECOND_BRAIN_DB_DSN`
- `SECOND_BRAIN_EMBEDDING_DIMENSION`
- `SECOND_BRAIN_DEFAULT_MEMORY_SCOPE`
- `SECOND_BRAIN_MEMORY_ROOTS`
- `SECOND_BRAIN_MCP_SERVER_NAME`
- `SECOND_BRAIN_ONENOTE_TENANT_ID`
- `SECOND_BRAIN_ONENOTE_CLIENT_ID`
- `SECOND_BRAIN_ONENOTE_SCOPES`
- `SECOND_BRAIN_ONENOTE_TOKEN_CACHE_PATH`
- `SECOND_BRAIN_ONENOTE_AUTO_OPEN_BROWSER`
- `SECOND_BRAIN_ONENOTE_TIMEOUT_SECONDS`
- `SECOND_BRAIN_ONENOTE_USER_AGENT`
- `SECOND_BRAIN_ONENOTE_MEMORY_SCOPE`

Use [`.env.example`](/Users/davidmcnabb/projects/second-brain/.env.example) as the reference template.

For OneNote specifically, these settings reference an existing Microsoft Entra
app registration; they do not provision one. `SECOND_BRAIN_ONENOTE_CLIENT_ID`
must point to an app that can request the delegated permissions listed in
`SECOND_BRAIN_ONENOTE_SCOPES`.

## Configuring memories

`SECOND_BRAIN_MEMORY_ROOTS` maps memory scopes to local folders using:

```text
scope|path;scope|path
```

Example:

```env
SECOND_BRAIN_DEFAULT_MEMORY_SCOPE=project:second-brain
SECOND_BRAIN_MEMORY_ROOTS=project:second-brain|.;project:ai-recruitment|/Users/davidmcnabb/projects/ai-recruitment;general|/Users/davidmcnabb/notes
SECOND_BRAIN_ONENOTE_MEMORY_SCOPE=general
```

That setup means:

- this repo ingests into `project:second-brain`
- the `ai-recruitment` repo ingests into `project:ai-recruitment`
- your personal notes folder ingests into `general`
- OneNote pages also ingest into `general`

## Ingestion

### Local files

Supported file types currently include:

- `.md`
- `.txt`
- `.pdf`
- `.docx`
- many code and config text files such as `.py`, `.java`, `.ts`, `.tsx`, `.kt`, `.json`, `.yaml`, `.sql`, `.sh`

Local ingestion:

- recursively scans configured memory roots
- preserves path and timestamps
- hashes content to detect changes
- skips unchanged files
- logs failed extracts without crashing the whole run
- stores chunked text plus provenance in PostgreSQL

Run a one-off ingest:

```bash
make ingest
```

Run incremental watch mode:

```bash
make watch
```

`watch-files` is polling-based, intentionally simple, and designed for local reliability.

### OneNote

OneNote ingestion uses Microsoft Graph delegated authentication only.

This project does not implement app-only auth.

Prerequisite: complete the Microsoft Entra setup above before running this
command. The `.env` values below only point this repo at that existing app
registration:

1. Set `SECOND_BRAIN_ONENOTE_CLIENT_ID` to your Entra app's client ID.
2. Set `SECOND_BRAIN_ONENOTE_TENANT_ID` to `common` or your specific tenant ID.
3. Keep `SECOND_BRAIN_ONENOTE_SCOPES` aligned with the delegated Graph
   permissions configured on that app registration.

On first login, the ingester uses device-code authentication and caches the
delegated refresh token locally so later runs can refresh access tokens without
prompting again.
When interactive login is needed, it also opens the Microsoft device login page
in the default browser unless you disable that behavior in the environment.

Run a sync:

```bash
make ingest-onenote
```

Or with the CLI:

```bash
.venv/bin/python -m second_brain_ingester.cli ingest-onenote --since 2025-01-01T00:00:00Z
```

OneNote ingestion preserves notebook, section, and page identifiers, stores raw HTML plus normalized text, and supports incremental sync with modification timestamps where available.

## Searching memory

### Retriever CLI

Search all scopes allowed by your request:

```bash
.venv/bin/python -m second_brain_retriever.cli "hybrid retrieval"
```

Search a specific memory:

```bash
.venv/bin/python -m second_brain_retriever.cli "tenant context cleanup filter" --memory-scope project:ai-recruitment
```

Search general memory only:

```bash
.venv/bin/python -m second_brain_retriever.cli "meeting notes architecture decision" --memory-scope general
```

Search multiple scopes:

```bash
.venv/bin/python -m second_brain_retriever.cli "vector search" --memory-scope general --memory-scope project:second-brain
```

### What a good retrieval result looks like

A good hit should include:

- relevant chunk text
- source title and URI
- heading path where applicable
- source metadata
- citation information

If results are noisy, tighten the query and scope first before changing the architecture.

## MCP usage

Start the MCP server locally over stdio:

```bash
make mcp
```

Or:

```bash
.venv/bin/python -m second_brain_mcp_server.cli
```

Start the MCP server as a local HTTP service:

```bash
.venv/bin/python -m second_brain_mcp_server.cli --transport streamable-http --host 127.0.0.1 --port 8000
```

Start the always-on Dockerized MCP service:

```bash
make up
```

Start the HTTPS-published stack for remote clients such as Manus:

```bash
make up-https
```

This compose stack now runs:

- PostgreSQL in Docker on `127.0.0.1:55432`
- an MCP server in Docker on `http://127.0.0.1:18000/mcp`

If you want a different host port for the MCP container, set `SECOND_BRAIN_MCP_BIND_PORT` in [`.env`](/Users/davidmcnabb/projects/second-brain/.env).

The MCP server still supports stdio for local agent clients, but it can now also run as a remote `streamable-http` service for tools that prefer a persistent endpoint.

### Public HTTPS for Manus

Manus requires your MCP server to be reachable over public HTTPS.

To publish this stack over HTTPS:

1. set `SECOND_BRAIN_PUBLIC_HOSTNAME` in [`.env`](/Users/davidmcnabb/projects/second-brain/.env) to a real DNS name such as `mcp.example.com`
2. set `SECOND_BRAIN_ACME_EMAIL` to an email address for certificate issuance
3. point that DNS name at the machine running Docker
4. ensure inbound ports `80` and `443` reach that machine
5. run:

```bash
make up-https
```

The HTTPS URL Manus, Claude, and Codex should use in that setup is:

```text
https://YOUR_HOSTNAME/mcp
```

Available tools:

- `search_memory`
- `get_source`
- `get_chunk_context`
- `list_sources`

`list_sources` returns compact source summaries for efficiency. Use `get_source` when you need the full stored record.

## Recommended usage with agents

For project work:

- ingest the whole project repo into a dedicated project scope
- keep architecture docs, ADRs, notes, and useful code/config files in that scope
- point Claude or Codex at the MCP server with that scope as the default

For personal memory:

- ingest OneNote and local notes into `general`
- query `general` explicitly when you want cross-project recall

Agent workflow recommendation:

1. use `list_sources` to see what memory is available
2. use `search_memory` early for architecture, terminology, prior decisions, and docs
3. use `get_chunk_context` if a chunk looks useful but needs surrounding context
4. use `get_source` when you need the full underlying source record
5. prefer the live codebase over memory if they conflict

## Commands

Common commands:

```bash
make bootstrap
make up
make down
make ingest
make watch
make ingest-onenote
make search query="tenant context"
make mcp
make format
make lint
make test
```

## Testing and validation

Run checks:

```bash
make lint
make test
```

Useful validation steps:

- verify PostgreSQL is up on `55432`
- verify the MCP endpoint responds on `18000`
- run `make ingest`
- run targeted searches with `--memory-scope`
- inspect source counts in Postgres for each memory scope
- test MCP retrieval from Claude or Codex

## Current limitations

- the default embedder is local and deterministic, which is good for offline repeatability but not the strongest retrieval quality ceiling
- OneNote auth uses delegated device-code flow with local refresh-token caching
- watch mode handles new and changed files, but source tombstoning for deleted files is not implemented yet
- malformed source files are handled gracefully, but scanned PDFs without usable text remain a weak path because OCR is intentionally out of scope for v1
- some clients still differ in remote MCP transport support, so confirm whether they expect `streamable-http`, SSE, or stdio before wiring them

## Related docs

- [architecture.md](/Users/davidmcnabb/projects/second-brain/docs/architecture.md)
- [roadmap.md](/Users/davidmcnabb/projects/second-brain/docs/roadmap.md)

If architecture decisions change, update the docs alongside the code.
