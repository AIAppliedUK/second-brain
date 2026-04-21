import { useCallback, useEffect, useEffectEvent, useRef, useState, type ReactNode } from 'react'
import './App.css'
import {
  createScope,
  fetchActivity,
  fetchChunkContext,
  fetchDirectories,
  fetchIngestFailures,
  fetchIngestStatus,
  fetchOneNoteSyncStatus,
  fetchScopes,
  fetchSearch,
  fetchSource,
  deleteScope,
  triggerOneNoteSync,
  triggerIngest,
} from './api'
import type {
  ActivityPayload,
  ChunkContext,
  DirectoryPayload,
  IngestFailure,
  IngestStatus,
  OneNoteSyncStatus,
  Scope,
  SearchHit,
  SearchResponse,
  SourceRecord,
} from './types'

type InspectorState =
  | { kind: 'empty' }
  | { kind: 'source'; source: SourceRecord }
  | { kind: 'hit'; hit: SearchHit; source: SourceRecord; chunks: ChunkContext['chunks'] }

type WorkspaceMode = 'searching' | 'indexing'

function truncate(text: string | null | undefined, length = 260) {
  if (!text) {
    return ''
  }
  return text.length > length ? `${text.slice(0, length).trimEnd()}...` : text
}

function prettyState(status: IngestStatus) {
  const label = status.state.charAt(0).toUpperCase() + status.state.slice(1)
  return status.scope ? `${label}: ${status.scope}` : label
}

function prettyOneNoteState(status: OneNoteSyncStatus) {
  if (status.state === 'auth_required') {
    return 'Auth needed'
  }
  return status.state.charAt(0).toUpperCase() + status.state.slice(1)
}

function formatRelativeTime(value: string | null) {
  if (!value) {
    return 'No timestamp'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(
    Math.round((date.getTime() - Date.now()) / (1000 * 60 * 60)),
    'hour',
  )
}

function ModeButton({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: ReactNode
  onClick: () => void
}) {
  return (
    <button className={`modeButton ${active ? 'active' : ''}`} type="button" onClick={onClick}>
      {children}
    </button>
  )
}

function StatCard({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <article className="statCard">
      <span className="statLabel">{label}</span>
      <strong className="statValue">{value}</strong>
      {detail ? <p className="statDetail">{detail}</p> : null}
    </article>
  )
}

export default function App() {
  const [mode, setMode] = useState<WorkspaceMode>('searching')
  const [scopes, setScopes] = useState<Scope[]>([])
  const [defaultScope, setDefaultScope] = useState<string | null>(null)
  const [activeScope, setActiveScope] = useState<string | null>(null)
  const [searchScope, setSearchScope] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [sourceType, setSourceType] = useState('')
  const [results, setResults] = useState<SearchResponse | null>(null)
  const [activity, setActivity] = useState<ActivityPayload | null>(null)
  const [inspector, setInspector] = useState<InspectorState>({ kind: 'empty' })
  const [ingestStatus, setIngestStatus] = useState<IngestStatus>({
    state: 'idle',
    started_at: null,
    finished_at: null,
    scope: null,
    error: null,
    total_files: 0,
    processed_files: 0,
    ingested_files: 0,
    skipped_files: 0,
    failed_files: 0,
    per_scope: null,
  })
  const [ingestFailures, setIngestFailures] = useState<IngestFailure[]>([])
  const [controlFeedback, setControlFeedback] = useState('')
  const [scopeName, setScopeName] = useState('')
  const [scopePath, setScopePath] = useState('')
  const [directoryPayload, setDirectoryPayload] = useState<DirectoryPayload | null>(null)
  const [browserOpen, setBrowserOpen] = useState(false)
  const [loadingSearch, setLoadingSearch] = useState(false)
  const [deletingScope, setDeletingScope] = useState<string | null>(null)
  const [onenoteStatus, setOnenoteStatus] = useState<OneNoteSyncStatus>({
    state: 'idle',
    started_at: null,
    finished_at: null,
    since: null,
    error: null,
    pages_synced: 0,
    auth_message: null,
    verification_uri: null,
    verification_uri_complete: null,
    user_code: null,
    interval: null,
    expires_in: null,
  })
  const onenotePollDelay = useRef(2000)

  const visibleActivity =
    activity?.recent_memories.length ? activity.recent_memories : (activity?.recent_sources ?? [])
  const ingestedScopes = scopes.filter((scope) => scope.ingested)
  const scopeReports = Object.entries(ingestStatus.per_scope ?? {})
    .sort((a, b) => b[1].ingested - a[1].ingested || b[1].discovered - a[1].discovered)
    .slice(0, 5)

  const choosePreferredScope = useCallback((nextScopes: Scope[], configuredDefault: string | null) => {
    const defaultCandidate = nextScopes.find((scope) => scope.memory_scope === configuredDefault)
    const firstIngested = nextScopes.find((scope) => scope.ingested)
    setActiveScope((current) => {
      if (current && nextScopes.some((scope) => scope.memory_scope === current)) {
        return current
      }
      if (defaultCandidate?.ingested) {
        return defaultCandidate.memory_scope
      }
      return firstIngested?.memory_scope ?? null
    })
  }, [])

  const refreshScopes = useCallback(async () => {
    const payload = await fetchScopes()
    setScopes(payload.scopes)
    setDefaultScope(payload.default_memory_scope)
    setSearchScope((current) =>
      current && payload.scopes.some((scope) => scope.memory_scope === current) ? current : null,
    )
    choosePreferredScope(payload.scopes, payload.default_memory_scope)
  }, [choosePreferredScope])

  const refreshActivity = useCallback(async () => {
    const payload = await fetchActivity(activeScope)
    setActivity(payload)
  }, [activeScope])

  const refreshOneNoteStatus = useCallback(async () => {
    const payload = await fetchOneNoteSyncStatus()
    setOnenoteStatus(payload)
    return payload
  }, [])

  const refreshIngestStatus = useCallback(async () => {
    const payload = await fetchIngestStatus()
    setIngestStatus(payload)
    const failures = await fetchIngestFailures(activeScope)
    setIngestFailures(failures.failures)
    if (payload.state !== 'running') {
      await refreshScopes()
      await refreshActivity()
    }
  }, [activeScope, refreshActivity, refreshScopes])

  const pollIngestStatus = useEffectEvent(() => {
    void refreshIngestStatus()
  })

  useEffect(() => {
    void refreshScopes()
  }, [refreshScopes])

  useEffect(() => {
    void refreshActivity()
  }, [refreshActivity])

  useEffect(() => {
    void refreshOneNoteStatus()
  }, [refreshOneNoteStatus])

  useEffect(() => {
    void (async () => {
      const payload = await fetchIngestStatus()
      setIngestStatus(payload)
      const failures = await fetchIngestFailures(activeScope)
      setIngestFailures(failures.failures)
      if (payload.state !== 'running') {
        await refreshScopes()
        await refreshActivity()
      }
    })()
  }, [activeScope, refreshActivity, refreshScopes])

  useEffect(() => {
    if (onenoteStatus.state !== 'running' && onenoteStatus.state !== 'auth_required') {
      onenotePollDelay.current = 2000
      return
    }
    const delay = onenotePollDelay.current
    const timer = window.setTimeout(() => {
      void refreshOneNoteStatus()
    }, delay)
    onenotePollDelay.current = Math.min(delay * 2, 30000)
    return () => window.clearTimeout(timer)
  }, [onenoteStatus.state, refreshOneNoteStatus])

  useEffect(() => {
    if (ingestStatus.state !== 'running') {
      return
    }
    const timer = window.setInterval(() => {
      pollIngestStatus()
    }, 2000)
    return () => window.clearInterval(timer)
  }, [ingestStatus.state])

  async function runSearch(event?: React.FormEvent) {
    event?.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) {
      return
    }
    setMode('searching')
    setLoadingSearch(true)
    setControlFeedback('')
    setResults(null)
    try {
      const payload = await fetchSearch(trimmed, searchScope, sourceType)
      setResults(payload)
    } catch (error) {
      setControlFeedback(error instanceof Error ? error.message : 'Search failed.')
    } finally {
      setLoadingSearch(false)
    }
  }

  async function inspectSource(sourceId: string) {
    const source = await fetchSource(sourceId)
    setInspector({ kind: 'source', source })
  }

  async function inspectHit(hit: SearchHit) {
    setMode('searching')
    const [source, context] = await Promise.all([
      fetchSource(hit.source_id),
      fetchChunkContext(hit.chunk_id),
    ])
    setInspector({ kind: 'hit', hit, source, chunks: context.chunks })
  }

  async function handleIngest(scope?: string | null) {
    try {
      setMode('indexing')
      setControlFeedback(scope ? `Starting ingest for ${scope}...` : 'Starting full ingest...')
      await triggerIngest(scope)
      await refreshIngestStatus()
    } catch (error) {
      setControlFeedback(error instanceof Error ? error.message : 'Failed to start ingest.')
    }
  }

  async function handleAddScope(event: React.FormEvent) {
    event.preventDefault()
    if (!scopeName.trim() || !scopePath.trim()) {
      setControlFeedback('Enter both a scope and a folder path.')
      return
    }
    try {
      const nextScope = scopeName.trim()
      const payload = await createScope(nextScope, scopePath.trim())
      setScopes(payload.scopes)
      setDefaultScope(payload.default_memory_scope)
      setScopeName('')
      setScopePath('')
      setControlFeedback(`Added ${nextScope}.`)
    } catch (error) {
      setControlFeedback(error instanceof Error ? error.message : 'Failed to add scope.')
    }
  }

  async function handleDeleteScope(scope: Scope) {
    const confirmed = window.confirm(
      `Delete ${scope.memory_scope} and all indexed data for it? This removes the configured scope entry too if it exists.`,
    )
    if (!confirmed) {
      return
    }
    try {
      setDeletingScope(scope.memory_scope)
      setControlFeedback(`Deleting ${scope.memory_scope}...`)
      await deleteScope(scope.memory_scope)
      await refreshIngestStatus()
      setControlFeedback(`Deleted ${scope.memory_scope}.`)
    } catch (error) {
      setControlFeedback(error instanceof Error ? error.message : 'Failed to delete scope.')
    } finally {
      setDeletingScope(null)
    }
  }

  async function handleOneNoteSync() {
    try {
      setControlFeedback('Starting OneNote sync...')
      await triggerOneNoteSync(null)
      await refreshOneNoteStatus()
    } catch (error) {
      setControlFeedback(error instanceof Error ? error.message : 'Failed to start OneNote sync.')
    }
  }

  async function handleBrowse(path?: string) {
    try {
      const payload = await fetchDirectories(path)
      setDirectoryPayload(payload)
      setBrowserOpen(true)
    } catch (error) {
      setControlFeedback(error instanceof Error ? error.message : 'Failed to browse folders.')
    }
  }

  return (
    <div className={`shell shell--${mode}`}>
      <header className="appHeader">
        <div className="brandBlock">
          <p className="eyebrow">Second Brain</p>
          <h1 className="appTitle">Index first. Search second.</h1>
          <p className="appLead">
            Loading and indexing prepare the corpus. Searching is where you ask questions and inspect evidence.
          </p>
        </div>

        <div className="modeSwitch" role="tablist" aria-label="Workspace mode">
          <ModeButton active={mode === 'searching'} onClick={() => setMode('searching')}>
            Searching
          </ModeButton>
          <ModeButton active={mode === 'indexing'} onClick={() => setMode('indexing')}>
            Loading & indexing
          </ModeButton>
        </div>
      </header>

      {mode === 'indexing' ? (
        <div className="modeLayout indexingLayout">
          <section className="panel indexingScopePanel">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">Step 1</p>
                <h2 className="sectionTitle">Choose or add a scope</h2>
                <p className="sectionCopy">This is the content you are about to index.</p>
              </div>
              <span className="statusPill">Default: {defaultScope ?? 'None'}</span>
            </div>
            <div className="scopeList">
              <article className={`scopeCard ${activeScope === null ? 'active' : ''}`}>
                <button
                  className="scopeCardSelect"
                  type="button"
                  onClick={() => setActiveScope(null)}
                >
                  <p className="scopeName">All scopes</p>
                  <p className="metaLine">Run indexing across the full corpus.</p>
                </button>
              </article>
              {scopes.map((scope) => (
                <article
                  key={scope.memory_scope}
                  className={`scopeCard ${activeScope === scope.memory_scope ? 'active' : ''}`}
                >
                  <button
                    className="scopeCardSelect"
                    type="button"
                    onClick={() => setActiveScope(scope.memory_scope)}
                  >
                    <p className="scopeName">{scope.memory_scope}</p>
                    <p className="metaLine">
                      {scope.source_count} sources
                      {scope.path ? ` • ${truncate(scope.path, 40)}` : ''}
                    </p>
                    <div className="tagRow">
                      <span className="stateChip">{scope.configured ? 'Configured' : 'Discovered'}</span>
                      <span className="stateChip">{scope.ingested ? 'Indexed' : 'Not indexed'}</span>
                    </div>
                  </button>
                  <div className="scopeCardActions">
                    <button
                      className="scopeDeleteButton"
                      type="button"
                      disabled={deletingScope === scope.memory_scope}
                      onClick={() => void handleDeleteScope(scope)}
                    >
                      {deletingScope === scope.memory_scope ? 'Deleting...' : 'Delete'}
                    </button>
                  </div>
                </article>
              ))}
            </div>

            <form className="formStack" onSubmit={handleAddScope}>
              <p className="subsectionTitle">Add a new scope</p>
              <label className="field">
                <span className="fieldLabel">Scope name</span>
                <input
                  value={scopeName}
                  onChange={(event) => setScopeName(event.target.value)}
                  placeholder="project:new-project"
                />
              </label>
              <label className="field">
                <span className="fieldLabel">Folder path</span>
                <input
                  value={scopePath}
                  onChange={(event) => setScopePath(event.target.value)}
                  placeholder="/Users/davidmcnabb/projects/new-project"
                />
              </label>
              <div className="buttonRow">
                <button className="secondaryButton" type="button" onClick={() => void handleBrowse(scopePath || undefined)}>
                  Browse folders
                </button>
                <button className="primaryButton" type="submit">
                  Add scope
                </button>
              </div>
            </form>

            {browserOpen && directoryPayload ? (
              <div className="folderBrowser">
                <div className="folderHeader">
                  <strong className="panelTitle">Choose a folder</strong>
                  <button className="linkButton" type="button" onClick={() => setBrowserOpen(false)}>
                    Close
                  </button>
                </div>
                <div className="folderMeta">
                  <button
                    className="linkButton"
                    type="button"
                    disabled={!directoryPayload.parent}
                    onClick={() => void handleBrowse(directoryPayload.parent ?? undefined)}
                  >
                    Up
                  </button>
                  <span className="folderCurrent">{directoryPayload.current}</span>
                </div>
                <div className="folderList">
                  <button
                    className="folderEntry"
                    type="button"
                    onClick={() => {
                      setScopePath(directoryPayload.current)
                      setBrowserOpen(false)
                    }}
                  >
                    Use this folder
                  </button>
                  {directoryPayload.directories.map((directory) => (
                    <button
                      key={directory.path}
                      className="folderEntry"
                      type="button"
                      onClick={() => void handleBrowse(directory.path)}
                    >
                      {directory.name}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <p className="feedback">{controlFeedback}</p>
          </section>

          <section className="panel indexingRunPanel">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">Step 2</p>
                <h2 className="sectionTitle">Start indexing</h2>
                <p className="sectionCopy">Run all content or only the selected scope.</p>
              </div>
              <span className={`statusPill ${ingestStatus.state}`}>{prettyState(ingestStatus)}</span>
            </div>
            <div className="buttonStack">
              <button className="primaryButton" type="button" onClick={() => void handleIngest(null)}>
                Ingest all content
              </button>
              <button
                className="secondaryButton"
                type="button"
                disabled={!activeScope || ingestStatus.state === 'running'}
                onClick={() => void handleIngest(activeScope)}
              >
                Ingest selected scope
              </button>
              </div>
            <div className="oneNoteSyncCard">
              <div className="sectionHeader sectionHeaderTop">
                <div>
                  <p className="eyebrow">OneNote</p>
                  <h3 className="subsectionTitle">Sync notebook pages</h3>
                  <p className="sectionCopy">Pull OneNote pages into the repository from the UI, even inside a container.</p>
                </div>
                <span className={`statusPill ${onenoteStatus.state}`}>{prettyOneNoteState(onenoteStatus)}</span>
              </div>
              {onenoteStatus.state === 'auth_required' ? (
                <div className="oneNoteAuthBox">
                  <p className="emptyMessage">
                    {onenoteStatus.auth_message ?? 'Complete Microsoft sign-in to continue the sync.'}
                  </p>
                  <div className="tagRow">
                    {onenoteStatus.user_code ? <span className="tag">Code: {onenoteStatus.user_code}</span> : null}
                    {onenoteStatus.verification_uri ? <span className="tag">{onenoteStatus.verification_uri}</span> : null}
                  </div>
                </div>
              ) : null}
              <div className="buttonRow">
                <button
                  className="secondaryButton"
                  type="button"
                  disabled={onenoteStatus.state === 'running' || onenoteStatus.state === 'auth_required'}
                  onClick={() => void handleOneNoteSync()}
                >
                  Sync OneNote
                </button>
                {onenoteStatus.verification_uri_complete ? (
                  <a
                    className="linkButton"
                    href={onenoteStatus.verification_uri_complete}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open login
                  </a>
                ) : null}
              </div>
              <p className="microMeta">
                {onenoteStatus.pages_synced ? `${onenoteStatus.pages_synced} pages synced.` : 'No sync has run in this session yet.'}
              </p>
              {onenoteStatus.error ? <p className="feedback">{onenoteStatus.error}</p> : null}
            </div>
            <div className="summaryGrid">
              <StatCard
                label="Processed"
                value={`${ingestStatus.processed_files}/${ingestStatus.total_files}`}
                detail="Files handled in the current run."
              />
              <StatCard label="New" value={`${ingestStatus.ingested_files}`} detail="Newly indexed in this run." />
              <StatCard label="Skipped" value={`${ingestStatus.skipped_files}`} detail="Already up to date." />
              <StatCard label="Failed" value={`${ingestStatus.failed_files}`} detail="Need attention." />
            </div>
            {scopeReports.length ? (
              <div className="scopeReportList scrollArea scrollAreaMedium">
                {scopeReports.map(([scope, stats]) => (
                  <article key={scope} className="scopeReportCard">
                    <div className="scopeReportHeader">
                      <p className="cardTitle">{scope}</p>
                      <span className="scopeReportTotal">{stats.indexed_total ?? 0} indexed</span>
                    </div>
                    <div className="scopeReportGrid">
                      <div>
                        <span className="miniLabel">Discovered</span>
                        <strong className="miniValue">{stats.discovered}</strong>
                      </div>
                      <div>
                        <span className="miniLabel">New</span>
                        <strong className="miniValue">{stats.ingested}</strong>
                      </div>
                      <div>
                        <span className="miniLabel">Skipped</span>
                        <strong className="miniValue">{stats.skipped}</strong>
                      </div>
                      <div>
                        <span className="miniLabel">Failed</span>
                        <strong className="miniValue">{stats.failed}</strong>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="emptyState compactEmptyState">
                <p className="emptyMessage">Run indexing to see per-scope reporting.</p>
              </div>
            )}
            <p className="feedback">{controlFeedback}</p>
          </section>

          <section className="panel indexingReviewPanel">
            <div className="sectionHeader">
              <div>
                <p className="eyebrow">Step 3</p>
                <h2 className="sectionTitle">Review what changed</h2>
                <p className="sectionCopy">Recent activity and failures help you catch issues before searching.</p>
              </div>
              <span className="layoutHint">Live</span>
            </div>
            <div className="splitStack">
              <section className="subpanel">
                <h3 className="subsectionTitle">Recent activity</h3>
                <div className="activityList scrollArea scrollAreaMedium">
                  {visibleActivity.length ? (
                    visibleActivity.map((entry) => (
                      <button
                        key={entry.id}
                        className="activityCard"
                        type="button"
                        onClick={() => void inspectSource(entry.id)}
                      >
                        <p className="cardTitle">{entry.title}</p>
                        <div className="activityMeta">
                          <span>{entry.source_type}</span>
                          <span>{entry.memory_scope}</span>
                          <span>{entry.chunk_count} chunks</span>
                        </div>
                      </button>
                    ))
                  ) : (
                    <div className="emptyState compactEmptyState">
                      <p className="emptyMessage">No recent activity yet.</p>
                    </div>
                  )}
                </div>
              </section>
              <section className="subpanel">
                <h3 className="subsectionTitle">Issues to fix</h3>
                {ingestFailures.length ? (
                  <div className="failureList scrollArea scrollAreaMedium">
                    {ingestFailures.map((failure, index) => (
                      <article key={`${failure.created_at}-${index}`} className="failureCard">
                        <p className="cardTitle">{truncate(failure.metadata.path ?? failure.message, 64)}</p>
                        <p className="metaLine">{failure.message}</p>
                        <p className="microMeta">{formatRelativeTime(failure.created_at)}</p>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="emptyState compactEmptyState">
                    <p className="emptyMessage">No recent ingest issues.</p>
                  </div>
                )}
              </section>
            </div>
          </section>
        </div>
      ) : (
        <div className="modeLayout searchLayout">
          <section className="panel searchPanel searchQueryPanel">
            <div className="sectionHeader sectionHeaderTop">
              <div>
                <p className="eyebrow">Step 1</p>
                <h2 className="sectionTitle">Ask a question</h2>
                <p className="sectionCopy">Use one query, then refine by scope or source type if needed.</p>
              </div>
            </div>
            <form className="searchForm" onSubmit={(event) => void runSearch(event)}>
              <div className="searchScopeBar">
                <div className="searchScopeBarHeader">
                  <span className="fieldLabel">Scope</span>
                  <span className="searchScopeBarState">
                    {searchScope ? 'Filtered to one scope' : 'Searching all ingested scopes'}
                  </span>
                </div>
                <div className="searchScopeChips" aria-label="Search scope choices">
                  <button
                    className={`scopeChip ${searchScope === null ? 'selected' : ''}`}
                    type="button"
                    onClick={() => setSearchScope(null)}
                  >
                    All ingested scopes
                  </button>
                  {ingestedScopes.length ? (
                    ingestedScopes.map((scope) => (
                      <button
                        key={scope.memory_scope}
                        className={`scopeChip ${searchScope === scope.memory_scope ? 'selected' : ''}`}
                        type="button"
                        onClick={() => setSearchScope(scope.memory_scope)}
                      >
                        {scope.memory_scope}
                      </button>
                    ))
                  ) : (
                    <span className="scopeChipEmpty">No ingested scopes yet. Run indexing first.</span>
                  )}
                </div>
                {searchScope ? (
                  <button className="scopeClearButton" type="button" onClick={() => setSearchScope(null)}>
                    Clear scope
                  </button>
                ) : null}
              </div>
              <label className="field fieldGrow">
                <span className="fieldLabel">Query</span>
                <input
                  className="queryInput"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search architecture notes, decisions, implementation details..."
                />
              </label>
              <label className="field">
                <span className="fieldLabel">Source type</span>
                <select className="queryInput sourceTypeSelect" value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
                  <option value="">All sources</option>
                  <option value="local_file">Local files</option>
                  <option value="agent_memory">Agent memory</option>
                  <option value="onenote">OneNote pages</option>
                </select>
              </label>
              <button className="primaryButton searchButton" type="submit">
                {loadingSearch ? 'Searching...' : 'Search'}
              </button>
            </form>
            <div className="searchHints">
              <span className="hintChip">Start with a short phrase</span>
              <span className="hintChip">Pick an ingested scope from the scope bar</span>
              <span className="hintChip">Narrow by source type</span>
            </div>
          </section>

          <div className="workspaceGrid">
            <section className="panel resultsPanel">
              <div className="sectionHeader">
                <div>
                  <p className="eyebrow">Results</p>
                  <h2 className="sectionTitle">Results</h2>
                  <p className="sectionCopy">
                    {results
                      ? `${results.hits.length} matches for "${results.query}".`
                      : 'Run a search to see matching chunks.'}
                  </p>
                </div>
                <span className="layoutHint">{results?.hits.length ?? 0} shown</span>
              </div>

              {results?.hits.length ? (
                <div className="resultList scrollArea scrollAreaTall">
                  {results.hits.map((hit) => (
                    <button
                      key={hit.chunk_id}
                      className="resultCard"
                      type="button"
                      onClick={() => void inspectHit(hit)}
                    >
                      <p className="resultTitle">{hit.source_title}</p>
                      <div className="resultMeta">
                        <span>{hit.source_type}</span>
                        <span>{hit.memory_scope}</span>
                        <span>Chunk {hit.citation.chunk_index + 1}</span>
                      </div>
                      <p className="resultExcerpt">{truncate(hit.chunk_text, 280)}</p>
                      {hit.heading_path.length ? (
                        <div className="tagRow">
                          {hit.heading_path.map((item) => (
                            <span key={item} className="tag">
                              {item}
                            </span>
                          ))}
                        </div>
                      ) : null}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="emptyState">
                  <p className="emptyMessage">
                    {results
                      ? 'No matches found. Try different wording, a broader scope, or another source type.'
                      : 'Search across your ingested memory and inspect the context alongside each hit.'}
                  </p>
                </div>
              )}
            </section>

            <section className="panel inspectorPanel">
              <div className="sectionHeader">
                <div>
                  <p className="eyebrow">Evidence</p>
                  <h2 className="sectionTitle">Inspect provenance</h2>
                  <p className="sectionCopy">Open a source or hit to see the full trail and nearby chunks.</p>
                </div>
                <span className="layoutHint">Details</span>
              </div>
              <InspectorPane inspector={inspector} />
            </section>
          </div>
        </div>
      )}
    </div>
  )
}

function InspectorPane({ inspector }: { inspector: InspectorState }) {
  if (inspector.kind === 'empty') {
    return (
      <div className="emptyState inspectorEmpty">
        <p className="emptyMessage">Select a source or search result to inspect provenance and nearby context.</p>
      </div>
    )
  }

  if (inspector.kind === 'source') {
    const { source } = inspector
    return (
      <div className="inspectorStack scrollArea scrollAreaTall">
        <article className="inspectorCard">
          <p className="cardTitle">{source.title}</p>
          <div className="sourceMeta">
            <span>{source.source_type}</span>
            <span>{source.memory_scope}</span>
            <span>{source.uri}</span>
          </div>
          <div className="tagRow">
            {Object.entries(source.metadata ?? {})
              .slice(0, 8)
              .map(([key, value]) => (
                <span key={key} className="tag">
                  {key}: {String(value)}
                </span>
              ))}
          </div>
          <p className="sourceBody">{truncate(source.canonical_text || source.raw_text || 'No body available.', 2600)}</p>
        </article>
      </div>
    )
  }

  const { hit, source, chunks } = inspector
  return (
    <div className="inspectorStack scrollArea scrollAreaTall">
      <article className="inspectorCard">
        <p className="cardTitle">{hit.source_title}</p>
        <div className="sourceMeta">
          <span>{hit.source_type}</span>
          <span>{hit.memory_scope}</span>
          <span>{source.uri}</span>
        </div>
        <div className="tagRow">
          <span className="tag">Score: {hit.score.toFixed(3)}</span>
          <span className="tag">Chunk {hit.citation.chunk_index + 1}</span>
          {hit.heading_path.map((item) => (
            <span key={item} className="tag">
              {item}
            </span>
          ))}
        </div>
        <p className="sourceBody">{truncate(source.canonical_text || source.raw_text || 'No body available.', 1100)}</p>
      </article>
      {chunks.length ? (
        chunks.map((chunk) => (
          <article key={chunk.id} className="contextCard">
            <p className="cardTitle">{chunk.heading_path.join(' / ') || `Chunk ${chunk.chunk_index + 1}`}</p>
            <div className="sourceMeta">
              <span>Chunk {chunk.chunk_index + 1}</span>
              <span>{chunk.token_count} tokens</span>
            </div>
            <p className="contextBody">{chunk.chunk_text}</p>
          </article>
        ))
      ) : (
        <div className="emptyState compactEmptyState">
          <p className="emptyMessage">No nearby chunks were returned.</p>
        </div>
      )}
    </div>
  )
}
