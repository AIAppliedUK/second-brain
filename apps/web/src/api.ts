import type {
  ActivityPayload,
  ChunkContext,
  DirectoryPayload,
  IngestFailurePayload,
  IngestStatus,
  OneNoteSyncPayload,
  OneNoteSyncStatus,
  ScopePayload,
  SearchResponse,
  SourceRecord,
} from './types'

async function readJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init)
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Request failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchScopes() {
  return readJson<ScopePayload>('/api/scopes')
}

export function createScope(scope: string, path: string) {
  return readJson<ScopePayload>('/api/scopes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scope, path }),
  })
}

export function deleteScope(scope: string) {
  const params = new URLSearchParams({ scope })
  return readJson<ScopePayload>(`/api/scopes?${params.toString()}`, {
    method: 'DELETE',
  })
}

export function fetchSearch(query: string, memoryScope?: string | null, sourceType?: string) {
  const params = new URLSearchParams({ query, limit: '12' })
  if (memoryScope) {
    params.set('memory_scope', memoryScope)
  }
  if (sourceType) {
    params.append('source_type', sourceType)
  }
  return readJson<SearchResponse>(`/api/search?${params.toString()}`)
}

export function fetchActivity(memoryScope?: string | null) {
  const params = new URLSearchParams({ limit: '8' })
  if (memoryScope) {
    params.set('memory_scope', memoryScope)
  }
  return readJson<ActivityPayload>(`/api/activity?${params.toString()}`)
}

export function fetchSource(sourceId: string) {
  return readJson<SourceRecord>(`/api/sources/${sourceId}`)
}

export function fetchChunkContext(chunkId: string) {
  return readJson<ChunkContext>(`/api/chunks/${chunkId}/context?before=1&after=1`)
}

export function fetchIngestStatus() {
  return readJson<IngestStatus>('/api/ingest')
}

export function triggerIngest(scope?: string | null) {
  return readJson<{ accepted: boolean; scope: string | null }>('/api/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scope: scope ?? null }),
  })
}

export function fetchIngestFailures(memoryScope?: string | null) {
  const params = new URLSearchParams({ limit: '6' })
  if (memoryScope) {
    params.set('memory_scope', memoryScope)
  }
  return readJson<IngestFailurePayload>(`/api/ingest/failures?${params.toString()}`)
}

export function fetchOneNoteSyncStatus() {
  return readJson<OneNoteSyncStatus>('/api/onenote/sync')
}

export function triggerOneNoteSync(since?: string | null) {
  return readJson<OneNoteSyncPayload>('/api/onenote/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ since: since ?? null }),
  })
}

export function fetchDirectories(path?: string) {
  const params = path ? `?path=${encodeURIComponent(path)}` : ''
  return readJson<DirectoryPayload>(`/api/directories${params}`)
}
