# Hybrid Retrieval Notes

This note explains how the local second brain stores knowledge in PostgreSQL.
The system uses both pgvector embeddings and PostgreSQL full-text search with
tsvector so results can combine semantic similarity with lexical precision.

## Provenance

Every chunk keeps provenance back to the original source document. Retrieval
responses include citations, source metadata, and chunk context so an AI client
can explain where an answer came from.

## Change Detection

Incremental ingestion should skip unchanged files, reindex changed files, and
support a watch mode that notices updates inside a project memory root.

## OneNote

OneNote pages are ingested through Microsoft Graph delegated authentication.
The integration is read-mostly in v1 and stores both cleaned text and raw HTML
for traceability.
