from uuid import uuid4

from second_brain_mcp_server.service import MCPService
from second_brain_models import (
    GetSourceRequest,
    ListSourcesRequest,
    SearchMemoryRequest,
    SearchResponse,
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

    def list_sources(self, limit=25, source_type=None, memory_scope=None):
        return [self.summary]


class FakeChunkRepository:
    def get_chunk_context(self, chunk_id, before, after):
        return []


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
    service = MCPService(FakeRetriever(), FakeSourceRepository(source), FakeChunkRepository())
    assert (
        service.search_memory(SearchMemoryRequest(query="hello", limit=1)).get("query") == "query"
    )
    assert service.get_source(GetSourceRequest(source_id=str(source.id)))["title"] == "Notes"
    payload = service.list_sources(ListSourcesRequest(limit=5))
    assert "sources" in payload
    assert payload["sources"][0]["chunk_count"] == 2
    assert "raw_text" not in payload["sources"][0]
