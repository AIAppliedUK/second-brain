from __future__ import annotations

from uuid import UUID

from second_brain_core.repository import ChunkRepository, SourceRepository
from second_brain_core.retrieval import HybridRetriever
from second_brain_models import (
    GetChunkContextRequest,
    GetSourceRequest,
    ListSourcesRequest,
    SearchMemoryRequest,
    SearchRequest,
)


class MCPService:
    def __init__(
        self,
        retriever: HybridRetriever,
        source_repository: SourceRepository,
        chunk_repository: ChunkRepository,
        default_memory_scope: str | None = None,
    ) -> None:
        self.retriever = retriever
        self.source_repository = source_repository
        self.chunk_repository = chunk_repository
        self.default_memory_scope = default_memory_scope

    def _resolve_memory_scopes(self, request: SearchMemoryRequest) -> list[str] | None:
        scopes = list(request.filters.memory_scopes or [])
        if request.memory_scope:
            scopes.append(request.memory_scope)
        if not scopes and self.default_memory_scope:
            scopes.append(self.default_memory_scope)
        return list(dict.fromkeys(scopes)) or None

    def search_memory(self, request: SearchMemoryRequest) -> dict:
        filters = request.filters.model_copy(
            update={"memory_scopes": self._resolve_memory_scopes(request)}
        )
        response = self.retriever.search(
            SearchRequest(query=request.query, limit=request.limit, filters=filters)
        )
        return response.model_dump(mode="json")

    def get_source(self, request: GetSourceRequest) -> dict:
        source = self.source_repository.get_source(UUID(request.source_id))
        if source is None:
            raise ValueError("Source not found")
        return source.model_dump(mode="json")

    def get_chunk_context(self, request: GetChunkContextRequest) -> dict:
        chunks = self.chunk_repository.get_chunk_context(
            UUID(request.chunk_id), before=request.before, after=request.after
        )
        return {"chunks": [chunk.model_dump(mode="json") for chunk in chunks]}

    def list_sources(self, request: ListSourcesRequest) -> dict:
        sources = self.source_repository.list_sources(
            limit=request.limit,
            source_type=request.source_type,
            memory_scope=request.memory_scope or self.default_memory_scope,
        )
        return {"sources": [source.model_dump(mode="json") for source in sources]}
