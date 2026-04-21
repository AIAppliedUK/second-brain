export type Scope = {
  memory_scope: string
  path: string | null
  configured: boolean
  ingested: boolean
  source_count: number
  source_type_count: number
  last_updated_at: string | null
}

export type ScopePayload = {
  default_memory_scope: string
  scopes: Scope[]
}

export type SourceSummary = {
  id: string
  memory_scope: string
  source_type: string
  title: string
  uri: string
  container_lineage: string[]
  updated_at: string | null
  ingested_at: string | null
  status: string
  metadata: Record<string, unknown>
  chunk_count: number
}

export type SourceRecord = SourceSummary & {
  external_id: string
  created_at: string | null
  content_hash: string
  raw_html?: string | null
  raw_text?: string | null
  canonical_text?: string | null
  deleted_at?: string | null
}

export type SearchHit = {
  chunk_id: string
  source_id: string
  memory_scope: string
  score: number
  lexical_score?: number | null
  vector_score?: number | null
  chunk_text: string
  source_title: string
  source_uri: string
  source_type: string
  heading_path: string[]
  metadata: Record<string, unknown>
  source_metadata: Record<string, unknown>
  citation: {
    source_id: string
    chunk_id: string
    memory_scope: string
    title: string
    uri: string
    source_type: string
    heading_path: string[]
    chunk_index: number
  }
}

export type SearchResponse = {
  query: string
  hits: SearchHit[]
}

export type ChunkContext = {
  chunks: Array<{
    id: string
    source_id: string
    memory_scope: string
    chunk_index: number
    heading_path: string[]
    chunk_text: string
    token_count: number
    metadata: Record<string, unknown>
  }>
}

export type ActivityPayload = {
  recent_sources: SourceSummary[]
  recent_memories: SourceSummary[]
}

export type IngestStatus = {
  state: 'idle' | 'running' | 'completed' | 'failed'
  started_at: number | null
  finished_at: number | null
  scope: string | null
  error: string | null
  total_files: number
  processed_files: number
  ingested_files: number
  skipped_files: number
  failed_files: number
  per_scope: Record<
    string,
    {
      discovered: number
      ingested: number
      skipped: number
      failed: number
      indexed_total?: number
    }
  > | null
}

export type IngestFailure = {
  created_at: string
  event_type: string
  status: string
  message: string
  metadata: Record<string, string>
}

export type IngestFailurePayload = {
  failures: IngestFailure[]
}

export type OneNoteSyncStatus = {
  state: 'idle' | 'running' | 'auth_required' | 'completed' | 'failed'
  started_at: number | null
  finished_at: number | null
  since: string | null
  error: string | null
  pages_synced: number
  auth_message: string | null
  verification_uri: string | null
  verification_uri_complete: string | null
  user_code: string | null
  interval: number | null
  expires_in: number | null
}

export type OneNoteSyncPayload = {
  accepted: boolean
  since: string | null
}

export type DirectoryPayload = {
  root: string
  current: string
  parent: string | null
  directories: Array<{ name: string; path: string }>
}
