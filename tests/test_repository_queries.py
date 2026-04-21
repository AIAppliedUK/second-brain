from datetime import UTC, datetime
from contextlib import contextmanager

from second_brain_core.repository import SourceRepository, build_lexical_query, build_vector_query


class _FakeCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[str, str] | tuple[str] | None]] = []
        self.rowcount = 0

    def execute(self, sql: str, params=None):
        self.statements.append((sql, params))
        normalized = sql.lstrip()
        if normalized.startswith("DELETE FROM audit_log"):
            self.rowcount = 2
        elif normalized.startswith("DELETE FROM chunks"):
            self.rowcount = 3
        elif normalized.startswith("DELETE FROM sources"):
            self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()
        self.committed = False

    def cursor(self, *args, **kwargs):
        return self.cursor_obj

    def commit(self):
        self.committed = True


class _FakeDatabase:
    def __init__(self) -> None:
        self.connection_obj = _FakeConnection()

    @contextmanager
    def connection(self):
        yield self.connection_obj


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


def test_delete_memory_scope_removes_scope_data():
    database = _FakeDatabase()
    repository = SourceRepository(database)  # type: ignore[arg-type]

    deleted = repository.delete_memory_scope("project:alpha")

    assert deleted == {
        "deleted_audit_events": 2,
        "deleted_chunks": 3,
        "deleted_sources": 1,
    }
    assert database.connection_obj.committed is True
    assert database.connection_obj.cursor_obj.statements[0][0].lstrip().startswith("DELETE FROM audit_log")
    assert database.connection_obj.cursor_obj.statements[1][0].lstrip().startswith("DELETE FROM chunks")
    assert database.connection_obj.cursor_obj.statements[2][0].lstrip().startswith("DELETE FROM sources")
