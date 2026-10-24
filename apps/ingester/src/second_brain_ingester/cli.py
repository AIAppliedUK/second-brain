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
from second_brain_core.embeddings import Embedder, build_embedder
from second_brain_core.logging import configure_logging, get_logger
from second_brain_core.repository import AuditRepository, ChunkRepository, SourceRepository
from second_brain_file_ingest import FileExtractionError, FileExtractor, LocalFileIngester
from second_brain_file_ingest.extractors import EXTRACTOR_VERSION
from second_brain_models import AuditEvent, SourceUpsert
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
    watch_parser.add_argument(
        "--exclude-scope",
        action="append",
        default=[],
        help="Skip this scope (repeatable); e.g. leave OneDrive to the power-gated watcher.",
    )
    file_parser = subparsers.add_parser("ingest-onenote")
    file_parser.add_argument("--since", default=None)
    return parser


def _selected_memory_roots(
    settings: Settings, scope: str | None = None, exclude: list[str] | None = None
) -> list[MemoryRoot]:
    roots = [root for root in settings.resolved_memory_roots() if root.scope not in (exclude or [])]
    if scope is None:
        return roots
    return [root for root in roots if root.scope == scope]


def remove_deleted_projects(
    parents: list[Path], roots: list[MemoryRoot], source_repo: SourceRepository
) -> int:
    """Purge indexed files of project folders that no longer exist under a parent."""
    removed = 0
    for parent in parents:
        # Unmounted, missing or empty parent: absence of folders proves nothing.
        if not parent.is_dir() or not any(child.is_dir() for child in parent.iterdir()):
            continue
        resolved = parent.resolve()
        keep = {root.scope for root in roots if resolved in root.path.resolve().parents}
        count = source_repo.delete_local_files_outside_scopes(str(resolved), keep)
        if count:
            logger.info(
                "Removed sources of deleted project folders",
                extra={"extras": {"parent": str(resolved), "removed": count}},
            )
        removed += count
    return removed


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
        # A recorded failure is only retried once the file's mtime or size changes.
        and existing.status in ("active", "failed")
        and existing.metadata.get("extractor_version") == EXTRACTOR_VERSION
    ):
        return "skipped"

    def fail(message: str) -> str:
        return _record_failure(
            memory_root, path, mtime, size_bytes, message, source_repo, audit_repo
        )

    try:
        extracted = ingester.extract_path(path)
    except FileNotFoundError:
        logger.info(
            "Skipping vanished file during ingest",
            extra={"extras": {"path": str(path.resolve()), "memory_scope": memory_root.scope}},
        )
        return "skipped"
    except FileExtractionError as exc:
        return fail(str(exc))
    except Exception as exc:  # third-party parsers raise all sorts; one file must not stop a pass
        return fail(f"Unexpected error extracting {path}: {type(exc).__name__}: {exc}")
    if (
        existing is not None
        and existing.content_hash == extracted.content_hash
        and existing.status == "active"
        and existing.metadata.get("extractor_version") == EXTRACTOR_VERSION
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
        return fail(event.message)
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
        return fail(f"Failed to persist {path}: {exc}")


def _record_failure(
    memory_root: MemoryRoot,
    path: Path,
    mtime: datetime,
    size_bytes: str,
    message: str,
    source_repo: SourceRepository,
    audit_repo: AuditRepository,
) -> str:
    resolved = str(path.resolve())
    try:
        source_repo.mark_failed(
            SourceUpsert(
                memory_scope=memory_root.scope,
                source_type="local_file",
                external_id=resolved,
                title=path.name,
                uri=path.resolve().as_uri(),
                created_at=mtime,
                updated_at=mtime,
                content_hash="",
                status="failed",
                metadata={
                    "memory_scope": memory_root.scope,
                    "path": resolved,
                    "size_bytes": size_bytes,
                    "extractor_version": EXTRACTOR_VERSION,
                    "error": message,
                },
            )
        )
    except Exception:
        logger.exception("Could not record failed file", extra={"extras": {"path": resolved}})
    audit_repo.add_event(
        AuditEvent(
            event_type="file_ingest",
            status="failed",
            message=message,
            metadata={"path": resolved, "memory_scope": memory_root.scope},
        )
    )
    logger.warning(
        "Skipping failed file ingest",
        extra={"extras": {"path": resolved, "memory_scope": memory_root.scope, "error": message}},
    )
    return "failed"


def reconcile_removed_sources(
    memory_root: MemoryRoot,
    discovered: set[Path],
    source_repo: SourceRepository,
) -> int:
    """Delete indexed files that were deleted, moved or are now ignored under this root."""
    if not memory_root.path.is_dir():
        # Unmounted or missing root: absence of files says nothing, so delete nothing.
        return 0
    indexed = source_repo.list_local_file_ids(memory_root.scope)
    if indexed and not discovered:
        logger.warning(
            "Root discovered no files; skipping removal of indexed sources",
            extra={"extras": {"memory_scope": memory_root.scope, "indexed": len(indexed)}},
        )
        return 0
    present = {str(path.resolve()) for path in discovered}
    stale = [source_id for external_id, source_id in indexed.items() if external_id not in present]
    removed = source_repo.delete_sources(stale)
    if removed:
        logger.info(
            "Removed stale sources",
            extra={"extras": {"memory_scope": memory_root.scope, "removed": removed}},
        )
    return removed


def _safe_process(
    memory_root: MemoryRoot,
    path: Path,
    ingester: LocalFileIngester,
    source_repo: SourceRepository,
    chunk_repo: ChunkRepository,
    audit_repo: AuditRepository,
) -> str:
    try:
        return process_local_file(memory_root, path, ingester, source_repo, chunk_repo, audit_repo)
    except Exception:
        # e.g. the database restarting mid-pass; log and let the next pass retry.
        logger.exception("Unhandled error processing file", extra={"extras": {"path": str(path)}})
        return "failed"


def _run_pass(
    roots: list[MemoryRoot],
    ingester: LocalFileIngester,
    source_repo: SourceRepository,
    chunk_repo: ChunkRepository,
    audit_repo: AuditRepository,
    summary: IngestSummary | None = None,
    progress_callback=None,
) -> None:
    discovered = ingester.discover_files(roots)
    if summary is not None:
        summary.total_files = len(discovered)
    seen: dict[str, set[Path]] = {root.scope: set() for root in roots}
    for memory_root, path in discovered:
        seen[memory_root.scope].add(path)
        result = _safe_process(memory_root, path, ingester, source_repo, chunk_repo, audit_repo)
        if summary is None:
            continue
        scope_stats = summary.per_scope.setdefault(memory_root.scope, ScopeIngestStats())
        scope_stats.discovered += 1
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
    for root in roots:
        try:
            reconcile_removed_sources(root, seen[root.scope], source_repo)
        except Exception:
            logger.exception("Failed to reconcile sources", extra={"extras": {"scope": root.scope}})


def _warn_unreadable_roots(roots: list[MemoryRoot]) -> None:
    for root in roots:
        if not root.path.is_dir():
            logger.warning(
                "Memory root is not readable inside this container and will not be indexed",
                extra={"extras": {"memory_scope": root.scope, "path": str(root.path)}},
            )


def ingest_files(
    settings: Settings,
    scope: str | None = None,
    progress_callback=None,
    embedder: Embedder | None = None,
) -> IngestSummary:
    database = Database(settings.db_dsn)
    source_repo = SourceRepository(database)
    chunk_repo = ChunkRepository(database)
    audit_repo = AuditRepository(database)
    ingester = LocalFileIngester(
        extractor=FileExtractor(),
        embedder=embedder or build_embedder(settings),
        chunking_config=ChunkingConfig(),
    )
    roots = _selected_memory_roots(settings, scope)
    _warn_unreadable_roots(roots)
    summary = IngestSummary(scope=scope)
    _run_pass(roots, ingester, source_repo, chunk_repo, audit_repo, summary, progress_callback)
    if scope is None:
        remove_deleted_projects(settings.project_parents, roots, source_repo)
    return summary


def watch_files(
    settings: Settings,
    interval: float,
    scope: str | None = None,
    exclude: list[str] | None = None,
) -> None:
    database = Database(settings.db_dsn)
    source_repo = SourceRepository(database)
    chunk_repo = ChunkRepository(database)
    audit_repo = AuditRepository(database)
    ingester = LocalFileIngester(
        extractor=FileExtractor(),
        embedder=build_embedder(settings),
        chunking_config=ChunkingConfig(),
    )
    _warn_unreadable_roots(_selected_memory_roots(settings, scope, exclude))
    logger.info(
        "Starting file watch",
        extra={
            "extras": {
                "interval_seconds": interval,
                "memory_roots": [
                    {"scope": root.scope, "path": str(root.path.resolve())}
                    for root in _selected_memory_roots(settings, scope, exclude)
                ],
            }
        },
    )
    try:
        while True:
            roots = _selected_memory_roots(settings, scope, exclude)
            _run_pass(roots, ingester, source_repo, chunk_repo, audit_repo)
            if scope is None:
                try:
                    remove_deleted_projects(settings.project_parents, roots, source_repo)
                except Exception:
                    logger.exception("Failed to remove deleted project folders")
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
        auto_open_browser=settings.onenote_auto_open_browser
        if auto_open_browser is None
        else auto_open_browser,
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
        build_embedder(settings),
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
        watch_files(settings, args.interval, args.scope, args.exclude_scope)
    else:
        sync_one_note(settings, args.since)


if __name__ == "__main__":
    main()
