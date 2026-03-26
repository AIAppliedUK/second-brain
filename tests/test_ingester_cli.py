from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from second_brain_core.config import MemoryRoot
from second_brain_ingester.cli import process_local_file
from second_brain_models import (
    AuditEvent,
    CanonicalDocument,
    ChunkUpsert,
    SourceRecord,
    SourceUpsert,
)


class FakeIngester:
    def __init__(self, content_hash: str, path: Path):
        self.content_hash = content_hash
        self.path = path

    def extract_path(self, path: Path):
        assert path == self.path
        return type(
            "Extracted",
            (),
            {"content_hash": self.content_hash},
        )()

    def ingest_path(
        self,
        path: Path,
        memory_scope: str,
        root_path: Path | None = None,
        extracted=None,
    ):
        source = SourceUpsert(
            id=uuid4(),
            memory_scope=memory_scope,
            source_type="local_file",
            external_id=str(path.resolve()),
            title=path.name,
            uri=path.resolve().as_uri(),
            container_lineage=[],
            content_hash=self.content_hash,
            metadata={"path": str(path.resolve())},
            raw_text="text",
            canonical_text="text",
        )
        chunks = [
            ChunkUpsert(
                source_id=source.id,
                memory_scope=memory_scope,
                chunk_index=0,
                heading_path=[],
                chunk_text="text",
                token_count=1,
                metadata={},
                embedding=[0.1, 0.2],
            )
        ]
        return CanonicalDocument(source=source, chunks=chunks), AuditEvent(
            source_id=source.id,
            event_type="file_ingest",
            status="success",
            message="ingested",
            metadata={"path": str(path.resolve())},
        )


class FakeSourceRepository:
    def __init__(self, existing: SourceRecord | None, persisted: SourceRecord | None = None):
        self.existing = existing
        self.persisted = persisted or existing

    def get_source_by_identity(self, memory_scope: str, source_type: str, external_id: str):
        return self.existing

    def upsert_source(self, source: SourceUpsert):
        return self.persisted or SourceRecord(**source.model_dump())


class FakeChunkRepository:
    def __init__(self):
        self.calls = []

    def replace_chunks(self, source_id, chunks):
        self.calls.append((source_id, chunks))


class FakeAuditRepository:
    def __init__(self):
        self.events = []

    def add_event(self, event):
        self.events.append(event)


def test_process_local_file_skips_when_mtime_and_size_match(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("hello")
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    existing = SourceRecord(
        id=uuid4(),
        memory_scope="project:test",
        source_type="local_file",
        external_id=str(path.resolve()),
        title=path.name,
        uri=path.resolve().as_uri(),
        content_hash="same",
        metadata={"size_bytes": str(path.stat().st_size)},
        updated_at=mtime,
    )
    result = process_local_file(
        MemoryRoot(scope="project:test", path=tmp_path),
        path,
        FakeIngester("same", path),
        FakeSourceRepository(existing),
        FakeChunkRepository(),
        FakeAuditRepository(),
    )
    assert result == "skipped"


def test_process_local_file_replaces_chunks_with_persisted_source_id(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("hello updated")
    existing = SourceRecord(
        id=uuid4(),
        memory_scope="project:test",
        source_type="local_file",
        external_id=str(path.resolve()),
        title=path.name,
        uri=path.resolve().as_uri(),
        content_hash="old",
        metadata={"size_bytes": "1"},
    )
    persisted = existing.model_copy(update={"id": uuid4(), "content_hash": "new"})
    chunk_repo = FakeChunkRepository()
    audit_repo = FakeAuditRepository()
    result = process_local_file(
        MemoryRoot(scope="project:test", path=tmp_path),
        path,
        FakeIngester("new", path),
        FakeSourceRepository(existing, persisted),
        chunk_repo,
        audit_repo,
    )
    assert result == "ingested"
    assert chunk_repo.calls[0][0] == persisted.id
    assert chunk_repo.calls[0][1][0].source_id == persisted.id
    assert audit_repo.events[0].source_id == persisted.id


def test_process_local_file_skips_if_file_disappears_before_stat(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("hello")
    path.unlink()
    chunk_repo = FakeChunkRepository()
    audit_repo = FakeAuditRepository()
    result = process_local_file(
        MemoryRoot(scope="project:test", path=tmp_path),
        path,
        FakeIngester("same", path),
        FakeSourceRepository(None),
        chunk_repo,
        audit_repo,
    )
    assert result == "skipped"
    assert chunk_repo.calls == []
    assert audit_repo.events == []
