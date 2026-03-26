from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime
from pathlib import Path

from second_brain_core.chunking import ChunkingConfig
from second_brain_core.config import MemoryRoot, Settings
from second_brain_core.db import Database
from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_core.logging import configure_logging, get_logger
from second_brain_core.repository import AuditRepository, ChunkRepository, SourceRepository
from second_brain_file_ingest import FileExtractionError, FileExtractor, LocalFileIngester
from second_brain_models import AuditEvent
from second_brain_one_note import (
    DeviceCodeAuthProvider,
    GraphClient,
    OneNoteIngester,
    RetryTransport,
)
from second_brain_one_note.client import UrlLibTransport

logger = get_logger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Second brain ingestion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("ingest-files")
    watch_parser = subparsers.add_parser("watch-files")
    watch_parser.add_argument("--interval", type=float, default=2.0)
    file_parser = subparsers.add_parser("ingest-onenote")
    file_parser.add_argument("--since", default=None)
    return parser


def _file_stats(path: Path) -> tuple[datetime, str]:
    stat = path.stat()
    return datetime.fromtimestamp(stat.st_mtime, tz=UTC), str(stat.st_size)


def process_local_file(
    memory_root: MemoryRoot,
    path: Path,
    ingester: LocalFileIngester,
    source_repo: SourceRepository,
    chunk_repo: ChunkRepository,
    audit_repo: AuditRepository,
) -> str:
    existing = source_repo.get_source_by_identity(
        memory_scope=memory_root.scope,
        source_type="local_file",
        external_id=str(path.resolve()),
    )
    try:
        mtime, size_bytes = _file_stats(path)
    except FileNotFoundError:
        logger.info(
            "Skipping vanished file during ingest",
            extra={"extras": {"path": str(path.resolve()), "memory_scope": memory_root.scope}},
        )
        return "skipped"
    if (
        existing is not None
        and existing.updated_at == mtime
        and str(existing.metadata.get("size_bytes")) == size_bytes
        and existing.status == "active"
    ):
        return "skipped"

    try:
        extracted = ingester.extract_path(path)
    except FileNotFoundError:
        logger.info(
            "Skipping vanished file during ingest",
            extra={"extras": {"path": str(path.resolve()), "memory_scope": memory_root.scope}},
        )
        return "skipped"
    except FileExtractionError as exc:
        audit_repo.add_event(
            AuditEvent(
                event_type="file_ingest",
                status="failed",
                message=str(exc),
                metadata={"path": str(path.resolve()), "memory_scope": memory_root.scope},
            )
        )
        logger.warning(
            "Skipping failed file ingest",
            extra={"extras": {"path": str(path.resolve()), "memory_scope": memory_root.scope}},
        )
        return "failed"
    if (
        existing is not None
        and existing.content_hash == extracted.content_hash
        and existing.status == "active"
    ):
        return "skipped"

    try:
        document, event = ingester.ingest_path(
            path,
            memory_scope=memory_root.scope,
            root_path=memory_root.path,
            extracted=extracted,
        )
    except FileNotFoundError:
        logger.info(
            "Skipping vanished file during ingest",
            extra={"extras": {"path": str(path.resolve()), "memory_scope": memory_root.scope}},
        )
        return "skipped"
    if document is None:
        audit_repo.add_event(event)
        logger.warning("Skipping failed file ingest", extra={"extras": event.metadata})
        return "failed"

    persisted_source = source_repo.upsert_source(document.source)
    persisted_chunks = [
        chunk.model_copy(
            update={
                "source_id": persisted_source.id,
                "memory_scope": persisted_source.memory_scope,
            }
        )
        for chunk in document.chunks
    ]
    chunk_repo.replace_chunks(persisted_source.id, persisted_chunks)
    audit_repo.add_event(event.model_copy(update={"source_id": persisted_source.id}))
    logger.info("Ingested file", extra={"extras": event.metadata})
    return "ingested"


def ingest_files(settings: Settings) -> None:
    database = Database(settings.db_dsn)
    source_repo = SourceRepository(database)
    chunk_repo = ChunkRepository(database)
    audit_repo = AuditRepository(database)
    ingester = LocalFileIngester(
        extractor=FileExtractor(),
        embedder=DeterministicEmbedder(settings.embedding_dimension),
        chunking_config=ChunkingConfig(),
    )
    for memory_root, path in ingester.discover_files(settings.resolved_memory_roots()):
        process_local_file(memory_root, path, ingester, source_repo, chunk_repo, audit_repo)


def watch_files(settings: Settings, interval: float) -> None:
    database = Database(settings.db_dsn)
    source_repo = SourceRepository(database)
    chunk_repo = ChunkRepository(database)
    audit_repo = AuditRepository(database)
    ingester = LocalFileIngester(
        extractor=FileExtractor(),
        embedder=DeterministicEmbedder(settings.embedding_dimension),
        chunking_config=ChunkingConfig(),
    )
    logger.info(
        "Starting file watch",
        extra={
            "extras": {
                "interval_seconds": interval,
                "memory_roots": [
                    {"scope": root.scope, "path": str(root.path.resolve())}
                    for root in settings.resolved_memory_roots()
                ],
            }
        },
    )
    try:
        while True:
            for memory_root, path in ingester.discover_files(settings.resolved_memory_roots()):
                process_local_file(memory_root, path, ingester, source_repo, chunk_repo, audit_repo)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Stopped file watch")


def ingest_onenote(settings: Settings, since: str | None) -> None:
    token_provider = DeviceCodeAuthProvider(
        tenant_id=settings.onenote_tenant_id,
        client_id=settings.onenote_client_id,
        scopes=settings.onenote_scopes,
        token_cache_path=settings.onenote_token_cache_path,
        auto_open_browser=settings.onenote_auto_open_browser,
        timeout_seconds=settings.onenote_timeout_seconds,
    )
    graph = GraphClient(
        access_token=token_provider.get_access_token(),
        transport=RetryTransport(UrlLibTransport()),
        user_agent=settings.onenote_user_agent,
    )
    ingester = OneNoteIngester(
        graph,
        DeterministicEmbedder(settings.embedding_dimension),
        memory_scope=settings.onenote_memory_scope,
    )
    database = Database(settings.db_dsn)
    source_repo = SourceRepository(database)
    chunk_repo = ChunkRepository(database)
    audit_repo = AuditRepository(database)
    documents, events = ingester.ingest(since=since)
    for document, event in zip(documents, events, strict=True):
        persisted_source = source_repo.upsert_source(document.source)
        persisted_chunks = [
            chunk.model_copy(
                update={
                    "source_id": persisted_source.id,
                    "memory_scope": persisted_source.memory_scope,
                }
            )
            for chunk in document.chunks
        ]
        chunk_repo.replace_chunks(persisted_source.id, persisted_chunks)
        audit_repo.add_event(event.model_copy(update={"source_id": persisted_source.id}))
    logger.info("Completed OneNote sync", extra={"extras": {"count": len(documents)}})


def main() -> None:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args()
    settings = Settings()
    if args.command == "ingest-files":
        ingest_files(settings)
    elif args.command == "watch-files":
        watch_files(settings, args.interval)
    else:
        ingest_onenote(settings, args.since)


if __name__ == "__main__":
    main()
