from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass, field
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


@dataclass(slots=True)
class ScopeIngestStats:
    discovered: int = 0
    ingested: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(slots=True)
class IngestSummary:
    scope: str | None = None
    total_files: int = 0
    processed_files: int = 0
    ingested_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    per_scope: dict[str, ScopeIngestStats] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "ingested_files": self.ingested_files,
            "skipped_files": self.skipped_files,
            "failed_files": self.failed_files,
            "per_scope": {
                scope: {
                    "discovered": stats.discovered,
                    "ingested": stats.ingested,
                    "skipped": stats.skipped,
                    "failed": stats.failed,
                }
                for scope, stats in self.per_scope.items()
            },
        }


def _default_watch_interval() -> float:
    try:
        return float(os.getenv("SECOND_BRAIN_WATCH_INTERVAL_SECONDS", "15"))
    except ValueError:
        return 15.0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Second brain ingestion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ingest_parser = subparsers.add_parser("ingest-files")
    ingest_parser.add_argument("--scope", default=None)
    watch_parser = subparsers.add_parser("watch-files")
    watch_parser.add_argument("--interval", type=float, default=_default_watch_interval())
    watch_parser.add_argument("--scope", default=None)
    file_parser = subparsers.add_parser("ingest-onenote")
    file_parser.add_argument("--since", default=None)
    return parser


def _selected_memory_roots(settings: Settings, scope: str | None = None) -> list[MemoryRoot]:
    roots = settings.resolved_memory_roots()
    if scope is None:
        return roots
    return [root for root in roots if root.scope == scope]


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
    try:
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
    except Exception as exc:
        audit_repo.add_event(
            AuditEvent(
                event_type="file_ingest",
                status="failed",
                message=f"Failed to persist {path}: {exc}",
                metadata={"path": str(path.resolve()), "memory_scope": memory_root.scope},
            )
        )
        logger.warning(
            "Skipping failed file ingest",
            extra={"extras": {"path": str(path.resolve()), "memory_scope": memory_root.scope}},
        )
        return "failed"


def ingest_files(
    settings: Settings,
    scope: str | None = None,
    progress_callback=None,
) -> IngestSummary:
    database = Database(settings.db_dsn)
    source_repo = SourceRepository(database)
    chunk_repo = ChunkRepository(database)
    audit_repo = AuditRepository(database)
    ingester = LocalFileIngester(
        extractor=FileExtractor(),
        embedder=DeterministicEmbedder(settings.embedding_dimension),
        chunking_config=ChunkingConfig(),
    )
    discovered = ingester.discover_files(_selected_memory_roots(settings, scope))
    summary = IngestSummary(scope=scope, total_files=len(discovered))
    for memory_root, path in discovered:
        scope_stats = summary.per_scope.setdefault(memory_root.scope, ScopeIngestStats())
        scope_stats.discovered += 1
        result = process_local_file(memory_root, path, ingester, source_repo, chunk_repo, audit_repo)
        summary.processed_files += 1
        if result == "ingested":
            summary.ingested_files += 1
            scope_stats.ingested += 1
        elif result == "failed":
            summary.failed_files += 1
            scope_stats.failed += 1
        else:
            summary.skipped_files += 1
            scope_stats.skipped += 1
        if progress_callback is not None:
            progress_callback(summary)
    return summary


def watch_files(settings: Settings, interval: float, scope: str | None = None) -> None:
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
                    for root in _selected_memory_roots(settings, scope)
                ],
            }
        },
    )
    try:
        while True:
            for memory_root, path in ingester.discover_files(_selected_memory_roots(settings, scope)):
                process_local_file(memory_root, path, ingester, source_repo, chunk_repo, audit_repo)
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Stopped file watch")


def ingest_onenote(settings: Settings, since: str | None) -> None:
    sync_one_note(settings, since)


def sync_one_note(
    settings: Settings,
    since: str | None,
    *,
    on_device_code=None,
    auto_open_browser: bool | None = None,
    on_progress=None,
) -> int:
    token_provider = DeviceCodeAuthProvider(
        tenant_id=settings.onenote_tenant_id,
        client_id=settings.onenote_client_id,
        scopes=settings.onenote_scopes,
        token_cache_path=settings.onenote_token_cache_path,
        auto_open_browser=settings.onenote_auto_open_browser if auto_open_browser is None else auto_open_browser,
        timeout_seconds=settings.onenote_timeout_seconds,
        on_device_code=on_device_code,
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
        request_delay_seconds=settings.onenote_request_delay_seconds,
    )
    database = Database(settings.db_dsn)
    source_repo = SourceRepository(database)
    chunk_repo = ChunkRepository(database)
    audit_repo = AuditRepository(database)
    documents, events = ingester.ingest(since=since, progress_callback=on_progress)
    success_events = [event for event in events if event.status == "success"]
    for document, event in zip(documents, success_events, strict=True):
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
    for event in events:
        if event.status != "success":
            audit_repo.add_event(event)
    logger.info("Completed OneNote sync", extra={"extras": {"count": len(documents)}})
    return len(documents)


def main() -> None:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args()
    settings = Settings()
    if args.command == "ingest-files":
        ingest_files(settings, args.scope)
    elif args.command == "watch-files":
        watch_files(settings, args.interval, args.scope)
    else:
        sync_one_note(settings, args.since)


if __name__ == "__main__":
    main()
