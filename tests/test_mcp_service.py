from uuid import uuid4

from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_mcp_server.service import MCPService
from second_brain_models import (
    GetSourceRequest,
    ListSourcesRequest,
    RememberRequest,
    SearchMemoryRequest,
    SearchResponse,
    SourceUpsert,
    SourceRecord,
    SourceSummary,
)


class FakeRetriever:
    def search(self, _request):
        return SearchResponse(query="query", hits=[])


class FakeSourceRepository:
    def __init__(self, source):
        self.source = source
        self.summary = SourceSummary(
            id=source.id,
            memory_scope=source.memory_scope,
            source_type=source.source_type,
            title=source.title,
            uri=source.uri,
            container_lineage=source.container_lineage,
            updated_at=source.updated_at,
            ingested_at=source.ingested_at,
            status=source.status,
            metadata=source.metadata,
            chunk_count=2,
        )

    def get_source(self, _source_id):
        return self.source

    def upsert_source(self, source: SourceUpsert):
        self.source = SourceRecord(**source.model_dump())
        return self.source

    def list_sources(self, limit=25, source_type=None, memory_scope=None):
        return [self.summary]


class FakeChunkRepository:
    def __init__(self):
        self.replaced = None

    def get_chunk_context(self, chunk_id, before, after):
        return []

    def replace_chunks(self, source_id, chunks):
        self.replaced = (source_id, chunks)


class FakeAuditRepository:
    def __init__(self):
        self.events = []

    def add_event(self, event):
        self.events.append(event)


def test_mcp_service_routes_requests():
    source = SourceRecord(
        id=uuid4(),
        source_type="local_file",
        external_id="f1",
        title="Notes",
        uri="file:///notes",
        content_hash="hash",
        metadata={},
    )
    service = MCPService(
        FakeRetriever(),
        FakeSourceRepository(source),
        FakeChunkRepository(),
        DeterministicEmbedder(32),
    )
    assert (
        service.search_memory(SearchMemoryRequest(query="hello", limit=1)).get("query") == "query"
    )
    assert service.get_source(GetSourceRequest(source_id=str(source.id)))["title"] == "Notes"
    payload = service.list_sources(ListSourcesRequest(limit=5))
    assert "sources" in payload
    assert payload["sources"][0]["chunk_count"] == 2
    assert "raw_text" not in payload["sources"][0]


def test_mcp_service_can_store_agent_memory():
    source = SourceRecord(
        id=uuid4(),
        source_type="local_file",
        external_id="seed",
        title="Seed",
        uri="file:///seed",
        content_hash="hash",
        metadata={},
    )
    chunk_repo = FakeChunkRepository()
    audit_repo = FakeAuditRepository()
    service = MCPService(
        FakeRetriever(),
        FakeSourceRepository(source),
        chunk_repo,
        DeterministicEmbedder(32),
        audit_repository=audit_repo,
        default_memory_scope="project:second-brain",
    )

    payload = service.remember(
        RememberRequest(
            title="Daily progress",
            body="Implemented issue 42 and found the ingestion path was skipping markdown headings.",
            summary="Issue 42 landed with one ingestion finding.",
            memory_kind="activity",
            project="second-brain",
            issue_refs=["#42"],
            tags=["ingestion", "github"],
            significance="high",
            agent_id="codex",
        )
    )

    assert payload["memory_scope"] == "project:second-brain"
    assert payload["source_type"] == "agent_memory"
    assert chunk_repo.replaced is not None
    _, chunks = chunk_repo.replaced
    assert len(chunks) >= 1
    assert chunks[0].metadata["memory_kind"] == "activity"
    assert chunks[0].metadata["project"] == "second-brain"
    assert audit_repo.events[0].event_type == "agent_memory_write"
