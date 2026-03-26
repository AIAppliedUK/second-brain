from __future__ import annotations

from dataclasses import dataclass

from second_brain_models import SearchCitation, SearchHit, SearchRequest, SearchResponse

from .embeddings import DeterministicEmbedder
from .repository import ChunkRepository, build_lexical_query, build_vector_query


@dataclass(slots=True)
class RetrievalConfig:
    lexical_weight: float = 0.45
    vector_weight: float = 0.55


class HybridRetriever:
    def __init__(
        self,
        chunk_repository: ChunkRepository,
        embedder: DeterministicEmbedder,
        config: RetrievalConfig | None = None,
    ) -> None:
        self.chunk_repository = chunk_repository
        self.embedder = embedder
        self.config = config or RetrievalConfig()

    def search(self, request: SearchRequest) -> SearchResponse:
        filters = request.filters.model_dump()
        lexical_bundle = build_lexical_query(
            query=request.query,
            embedding_dimension=self.embedder.dimension,
            limit=request.lexical_limit,
            filters=filters,
        )
        lexical_hits = self.chunk_repository.lexical_search(lexical_bundle)
        vector_bundle = build_vector_query(
            query_embedding=self.embedder.embed(request.query),
            limit=request.vector_limit,
            filters=filters,
        )
        vector_hits = self.chunk_repository.vector_search(vector_bundle)
        merged = self._merge_hits(lexical_hits, vector_hits)
        results = [
            SearchHit(
                chunk_id=chunk.id,
                source_id=chunk.source_id,
                memory_scope=chunk.memory_scope,
                score=chunk.combined_score or 0.0,
                lexical_score=chunk.lexical_score,
                vector_score=chunk.vector_score,
                chunk_text=chunk.chunk_text,
                source_title=chunk.source.title if chunk.source else "",
                source_uri=chunk.source.uri if chunk.source else "",
                source_type=chunk.source.source_type if chunk.source else "",
                heading_path=chunk.heading_path,
                metadata=chunk.metadata,
                source_metadata=chunk.source.metadata if chunk.source else {},
                citation=SearchCitation(
                    source_id=chunk.source_id,
                    chunk_id=chunk.id,
                    memory_scope=chunk.memory_scope,
                    title=chunk.source.title if chunk.source else "",
                    uri=chunk.source.uri if chunk.source else "",
                    source_type=chunk.source.source_type if chunk.source else "",
                    heading_path=chunk.heading_path,
                    chunk_index=chunk.chunk_index,
                ),
            )
            for chunk in merged[: request.limit]
        ]
        return SearchResponse(query=request.query, hits=results)

    def _merge_hits(self, lexical_hits, vector_hits):
        merged = {}
        for rank, chunk in enumerate(lexical_hits, start=1):
            chunk.lexical_score = chunk.lexical_score or 0.0
            merged[chunk.id] = chunk
            merged[chunk.id].combined_score = self._rrf(rank, self.config.lexical_weight)
        for rank, chunk in enumerate(vector_hits, start=1):
            existing = merged.get(chunk.id)
            contribution = self._rrf(rank, self.config.vector_weight)
            if existing is None:
                chunk.vector_score = chunk.vector_score or 0.0
                chunk.combined_score = contribution
                merged[chunk.id] = chunk
                continue
            existing.vector_score = chunk.vector_score
            existing.combined_score = (existing.combined_score or 0.0) + contribution
        return sorted(
            merged.values(),
            key=lambda item: (
                item.combined_score or 0.0,
                item.lexical_score or 0.0,
                item.vector_score or 0.0,
            ),
            reverse=True,
        )

    @staticmethod
    def _rrf(rank: int, weight: float) -> float:
        return weight / (60 + rank)
