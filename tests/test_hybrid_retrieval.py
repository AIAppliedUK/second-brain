from datetime import UTC, datetime
from uuid import uuid4

from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_core.retrieval import HybridRetriever
from second_brain_models import ChunkRecord, SearchRequest, SourceRecord


class FakeChunkRepository:
    def __init__(self, lexical_hits, vector_hits):
        self._lexical_hits = lexical_hits
        self._vector_hits = vector_hits

    def lexical_search(self, _query_bundle):
        return self._lexical_hits

    def vector_search(self, _query_bundle):
        return self._vector_hits


def _source() -> SourceRecord:
    return SourceRecord(
        id=uuid4(),
        source_type="local_file",
        external_id="file-1",
        title="Project Notes",
        uri="file:///notes.md",
        content_hash="hash",
        metadata={"project": "alpha"},
        container_lineage=["Projects", "Alpha"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        raw_text="text",
        canonical_text="text",
    )


def _chunk(source, lexical_score=None, vector_score=None, idx=0) -> ChunkRecord:
    return ChunkRecord(
        id=uuid4(),
        source_id=source.id,
        chunk_index=idx,
        heading_path=["Intro"],
        chunk_text="retrieval with provenance",
        token_count=3,
        metadata={"project": "alpha"},
        embedding=[],
        lexical_score=lexical_score,
        vector_score=vector_score,
        source=source,
    )


def test_hybrid_retrieval_merges_vector_and_lexical_hits():
    source = _source()
    shared = _chunk(source, lexical_score=0.7, idx=0)
    shared_vector = shared.model_copy(update={"vector_score": 0.9})
    lexical_only = _chunk(source, lexical_score=0.5, idx=1)
    vector_only = _chunk(source, vector_score=0.8, idx=2)
    retriever = HybridRetriever(
        FakeChunkRepository([shared, lexical_only], [shared_vector, vector_only]),
        DeterministicEmbedder(32),
    )
    response = retriever.search(SearchRequest(query="provenance", limit=3))
    assert response.hits[0].chunk_id == shared.id
    assert {hit.chunk_id for hit in response.hits} == {shared.id, lexical_only.id, vector_only.id}
    assert response.hits[0].citation.title == "Project Notes"
