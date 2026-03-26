from datetime import UTC, datetime

from second_brain_core.repository import build_lexical_query, build_vector_query


def test_lexical_query_uses_tsvector_and_filters():
    bundle = build_lexical_query(
        query="hybrid retrieval",
        embedding_dimension=256,
        limit=5,
        filters={
            "memory_scopes": ["project:alpha"],
            "source_types": ["local_file"],
            "containers": ["Projects"],
            "metadata_matches": {"project": "alpha"},
            "updated_after": datetime(2024, 1, 1, tzinfo=UTC),
        },
    )
    assert "websearch_to_tsquery" in bundle.sql
    assert "ts_rank_cd" in bundle.sql
    assert "c.tsv @@" in bundle.sql
    assert "c.memory_scope = ANY" in bundle.sql
    assert "s.source_type = ANY" in bundle.sql
    assert "c.metadata ->>" in bundle.sql


def test_vector_query_uses_pgvector_similarity():
    bundle = build_vector_query(
        query_embedding=[0.1, 0.2, 0.3],
        limit=7,
        filters={"metadata_matches": {"team": "core"}},
    )
    assert "c.embedding <=>" in bundle.sql
    assert "::vector" in bundle.sql
    assert bundle.params["limit"] == 7
    assert bundle.params["embedding"].startswith("[")
