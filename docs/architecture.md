# Local Second Brain Architecture

## Objective

Build a local-first second brain using:

- local PostgreSQL with `pgvector`
- PostgreSQL full-text search via `tsvector`
- OneNote and local files as input sources
- hybrid RAG retrieval
- an MCP server for Codex and Claude over stdio
- Python services
- Docker Compose for local development

## Architectural stance

This v1 follows a conservative design:

- PostgreSQL is the system of record for retrieval
- source systems remain inputs, not the primary query interface
- ingestion is explicit and auditable
- retrieval is hybrid, not vector-only
- `tsvector` is first-class in schema and query design
- MCP is the access layer for AI clients
- v1 is read-mostly

## Core components

### 1. Input sources

#### Local files

Supported in v1:

- markdown
- txt
- pdf
- docx

Implementation notes:

- recursively ingest configured folders
- detect changes by content hash
- preserve original path and timestamps
- extract canonical text into `sources.raw_text` and `sources.canonical_text`
- log extraction failures to `audit_log` without aborting the whole run

#### OneNote

Use Microsoft Graph with delegated authentication only.

Implementation notes:

- sync notebooks, sections, and pages from Graph `/me/onenote/*`
- preserve notebook, section, and page identifiers in `sources.metadata`
- store raw HTML and cleaned canonical text
- support incremental sync using `lastModifiedDateTime`
- implement throttling backoff for `429` responses

### 2. Ingestion and normalization

Every source is normalized into a canonical internal representation before indexing.

Canonical source data preserves:

- source type
- external identifier
- source URI or file path
- title
- timestamps
- content hash
- container lineage
- raw content where useful
- cleaned text for chunking
- metadata JSON

Pipeline:

1. detect new or changed content
2. extract raw content
3. normalize into canonical source record
4. chunk content
5. generate local embeddings
6. write source, chunks, and audit entries

### 3. Storage model

#### `sources`

Canonical source records for documents or OneNote pages.

Key fields:

- `source_type`
- `external_id`
- `title`
- `uri`
- `container_lineage`
- `created_at`
- `updated_at`
- `content_hash`
- `metadata`
- `raw_html`
- `raw_text`
- `canonical_text`
- `status`

#### `chunks`

Retrieval units derived from sources.

Key fields:

- `source_id`
- `chunk_index`
- `heading_path`
- `chunk_text`
- `token_count`
- `metadata`
- `embedding vector(256)`
- generated stored `tsv tsvector`

Indexing:

- GIN on `tsv` for lexical retrieval
- IVFFlat on `embedding` for vector similarity
- GIN on `metadata`
- source and uniqueness indexes for provenance-safe lookups

#### `audit_log`

Captures ingestion and indexing events with status, message, and structured metadata.

### 4. Retrieval

Retrieval supports:

- lexical search using `websearch_to_tsquery` and `ts_rank_cd`
- vector similarity using `pgvector`
- metadata filters
- source-type, container, and date filters

Retrieval flow:

1. lexical candidate search against `chunks.tsv`
2. vector candidate search against `chunks.embedding`
3. consistent filters applied to both queries
4. merge candidates with weighted reciprocal-rank fusion
5. return source metadata, chunk metadata, and explicit citations

Lexical retrieval is a first-class path, not a fallback.

### 5. MCP access layer

Expose memory through an MCP server over stdio.

Tools:

- `search_memory`
- `get_source`
- `get_chunk_context`
- `list_sources`

Design notes:

- request and response models are typed
- the MCP adapter is thin
- the core service layer is transport-agnostic for later HTTP support
- retrieval responses always include provenance and citation payloads

### 6. Trust and observability

Requirements implemented in v1 foundation:

- audit logs for file ingest and OneNote sync
- source-linked retrieval responses
- deterministic local embeddings for repeatable tests
- a replace-chunks workflow that supports reindexing a source

### 7. Non-goals for v1

Not included:

- autonomous write-back to OneNote
- cloud-hosted database
- browser UI
- app-only OneNote authentication
- vector-only retrieval

### 8. Definition of done for v1 foundation

v1 foundation is complete when:

- local files can be ingested reliably
- OneNote pages can be ingested with delegated auth
- sources and chunks are stored in PostgreSQL
- hybrid retrieval uses both `tsvector` and `pgvector`
- retrieval returns citations and provenance
- an MCP server exposes the memory system over stdio
- tests cover chunking, ingestion, retrieval, and MCP tools

