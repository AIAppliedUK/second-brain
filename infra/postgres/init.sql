CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    id UUID PRIMARY KEY,
    memory_scope TEXT NOT NULL DEFAULT 'general',
    source_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    uri TEXT NOT NULL,
    container_lineage TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    content_hash TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_html TEXT,
    raw_text TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    canonical_text TEXT,
    deleted_at TIMESTAMPTZ,
    UNIQUE (memory_scope, source_type, external_id)
);

ALTER TABLE sources ADD COLUMN IF NOT EXISTS memory_scope TEXT;
UPDATE sources SET memory_scope = 'general' WHERE memory_scope IS NULL;
ALTER TABLE sources ALTER COLUMN memory_scope SET DEFAULT 'general';
ALTER TABLE sources ALTER COLUMN memory_scope SET NOT NULL;
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_source_type_external_id_key;
ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_memory_scope_source_type_external_id_key;
ALTER TABLE sources
    ADD CONSTRAINT sources_memory_scope_source_type_external_id_key
    UNIQUE (memory_scope, source_type, external_id);

CREATE INDEX IF NOT EXISTS idx_sources_memory_scope ON sources (memory_scope);
CREATE INDEX IF NOT EXISTS idx_sources_source_type ON sources (source_type);
CREATE INDEX IF NOT EXISTS idx_sources_updated_at ON sources (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sources_metadata ON sources USING GIN (metadata);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
    memory_scope TEXT NOT NULL DEFAULT 'general',
    chunk_index INTEGER NOT NULL,
    heading_path TEXT[] NOT NULL DEFAULT '{}',
    chunk_text TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(256),
    tsv TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('english', COALESCE(chunk_text, ''))
    ) STORED,
    UNIQUE (source_id, chunk_index)
);

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS memory_scope TEXT;
UPDATE chunks c
SET memory_scope = s.memory_scope
FROM sources s
WHERE c.source_id = s.id AND c.memory_scope IS NULL;
UPDATE chunks SET memory_scope = 'general' WHERE memory_scope IS NULL;
ALTER TABLE chunks ALTER COLUMN memory_scope SET DEFAULT 'general';
ALTER TABLE chunks ALTER COLUMN memory_scope SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_memory_scope ON chunks (memory_scope);
CREATE INDEX IF NOT EXISTS idx_chunks_source_id ON chunks (source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_heading_path ON chunks USING GIN (heading_path);
CREATE INDEX IF NOT EXISTS idx_chunks_metadata ON chunks USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY,
    source_id UUID REFERENCES sources (id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_source_created ON audit_log (source_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_event_status ON audit_log (event_type, status);
