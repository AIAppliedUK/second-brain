from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock, Thread
from time import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from second_brain_core.config import (
    Settings,
    add_configured_memory_root,
    configured_memory_roots,
    remove_configured_memory_root,
)
from second_brain_core.db import Database
from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_core.repository import AuditRepository, ChunkRepository, SourceRepository
from second_brain_core.retrieval import HybridRetriever
from second_brain_ingester.cli import IngestSummary, ingest_files, sync_one_note
from second_brain_mcp_server.service import MCPService
from second_brain_models import (
    GetChunkContextRequest,
    GetSourceRequest,
    ListSourcesRequest,
    SearchRequest,
    SearchMemoryRequest,
)


@dataclass(slots=True)
class IngestStatus:
    state: str = "idle"
    started_at: float | None = None
    finished_at: float | None = None
    scope: str | None = None
    error: str | None = None
    total_files: int = 0
    processed_files: int = 0
    ingested_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    per_scope: dict[str, dict] | None = None


class ScopeCreateRequest(BaseModel):
    scope: str = Field(min_length=1)
    path: str = Field(min_length=1)


class IngestRequest(BaseModel):
    scope: str | None = None


class OneNoteSyncRequest(BaseModel):
    since: str | None = None


@dataclass(slots=True)
class OneNoteSyncStatus:
    state: str = "idle"
    started_at: float | None = None
    finished_at: float | None = None
    since: str | None = None
    error: str | None = None
    pages_synced: int = 0
    auth_message: str | None = None
    verification_uri: str | None = None
    verification_uri_complete: str | None = None
    user_code: str | None = None
    interval: int | None = None
    expires_in: int | None = None


def create_app() -> FastAPI:
    settings = Settings()
    database = Database(settings.db_dsn)
    embedder = DeterministicEmbedder(settings.embedding_dimension)
    chunk_repository = ChunkRepository(database)
    source_repository = SourceRepository(database)
    audit_repository = AuditRepository(database)
    retriever = HybridRetriever(chunk_repository, embedder)
    service = MCPService(
        retriever,
        source_repository,
        chunk_repository,
        embedder,
        audit_repository=audit_repository,
        default_memory_scope=settings.default_memory_scope,
    )

    app = FastAPI(
        title="second-brain API",
        description="HTTP API for second-brain retrieval, ingestion, and source inspection.",
    )
    ingest_lock = Lock()
    ingest_status = IngestStatus()
    onenote_lock = Lock()
    onenote_status = OneNoteSyncStatus()
    frontend_dist_dir = Path(
        os.getenv("SECOND_BRAIN_FRONTEND_DIST_DIR", str(Path.cwd() / "apps/web/dist"))
    ).expanduser()
    frontend_assets_dir = frontend_dist_dir / "assets"
    browse_root = (Path.home() / "projects") if (Path.home() / "projects").exists() else Path.home()
    if frontend_assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=frontend_assets_dir), name="assets")

    def build_scope_payload() -> dict:
        configured = {root.scope: root for root in configured_memory_roots()}
        combined: dict[str, dict] = {
            root.scope: {
                "memory_scope": root.scope,
                "path": str(root.path),
                "configured": True,
                "ingested": False,
                "source_count": 0,
                "source_type_count": 0,
                "last_updated_at": None,
            }
            for root in configured.values()
        }

        for row in source_repository.list_memory_scopes():
            entry = combined.setdefault(
                row["memory_scope"],
                {
                    "memory_scope": row["memory_scope"],
                    "path": None,
                    "configured": False,
                    "ingested": False,
                    "source_count": 0,
                    "source_type_count": 0,
                    "last_updated_at": None,
                },
            )
            entry["ingested"] = True
            entry["source_count"] = row["source_count"]
            entry["source_type_count"] = row["source_type_count"]
            entry["last_updated_at"] = row["last_updated_at"]

        scopes = sorted(
            combined.values(),
            key=lambda item: (
                not item["configured"],
                not item["ingested"],
                item["memory_scope"].lower(),
            ),
        )
        return {
            "default_memory_scope": settings.default_memory_scope,
            "scopes": scopes,
        }

    def scope_source_counts() -> dict[str, int]:
        return {
            row["memory_scope"]: row["source_count"]
            for row in source_repository.list_memory_scopes()
        }

    def apply_summary(summary: IngestSummary) -> None:
        counts = scope_source_counts()
        per_scope = summary.to_dict()["per_scope"]
        for scope_name, stats in per_scope.items():
            stats["indexed_total"] = counts.get(scope_name, 0)
        ingest_status.scope = summary.scope
        ingest_status.total_files = summary.total_files
        ingest_status.processed_files = summary.processed_files
        ingest_status.ingested_files = summary.ingested_files
        ingest_status.skipped_files = summary.skipped_files
        ingest_status.failed_files = summary.failed_files
        ingest_status.per_scope = per_scope

    def run_ingest_job(scope: str | None) -> None:
        with ingest_lock:
            ingest_status.state = "running"
            ingest_status.started_at = time()
            ingest_status.finished_at = None
            ingest_status.scope = scope
            ingest_status.error = None
            ingest_status.total_files = 0
            ingest_status.processed_files = 0
            ingest_status.ingested_files = 0
            ingest_status.skipped_files = 0
            ingest_status.failed_files = 0
            ingest_status.per_scope = {}
        try:
            summary = ingest_files(
                Settings(),
                scope=scope,
                progress_callback=lambda current: apply_summary(current),
            )
            with ingest_lock:
                apply_summary(summary)
                ingest_status.state = "completed"
                ingest_status.finished_at = time()
        except Exception as exc:  # pragma: no cover - defensive path
            with ingest_lock:
                ingest_status.state = "failed"
                ingest_status.finished_at = time()
                ingest_status.error = str(exc)

    def run_onenote_sync_job(since: str | None) -> None:
        def capture_device_code(device_code: dict) -> None:
            with onenote_lock:
                onenote_status.state = "auth_required"
                onenote_status.auth_message = device_code.get("message")
                onenote_status.verification_uri = device_code.get("verification_uri")
                onenote_status.verification_uri_complete = device_code.get(
                    "verification_uri_complete"
                )
                onenote_status.user_code = device_code.get("user_code")
                onenote_status.interval = int(device_code.get("interval", 0) or 0)
                onenote_status.expires_in = int(device_code.get("expires_in", 0) or 0)

        def capture_progress(pages_synced: int) -> None:
            with onenote_lock:
                onenote_status.pages_synced = pages_synced

        with onenote_lock:
            onenote_status.state = "running"
            onenote_status.started_at = time()
            onenote_status.finished_at = None
            onenote_status.since = since
            onenote_status.error = None
            onenote_status.pages_synced = 0
            onenote_status.auth_message = None
            onenote_status.verification_uri = None
            onenote_status.verification_uri_complete = None
            onenote_status.user_code = None
            onenote_status.interval = None
            onenote_status.expires_in = None
        try:
            synced_pages = sync_one_note(
                settings,
                since,
                on_device_code=capture_device_code,
                auto_open_browser=False,
                on_progress=capture_progress,
            )
            with onenote_lock:
                onenote_status.state = "completed"
                onenote_status.finished_at = time()
                onenote_status.pages_synced = synced_pages
        except Exception as exc:  # pragma: no cover - defensive path
            with onenote_lock:
                onenote_status.state = "failed"
                onenote_status.finished_at = time()
                onenote_status.error = str(exc)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        if (frontend_dist_dir / "index.html").exists():
            return FileResponse(frontend_dist_dir / "index.html")
        raise HTTPException(
            status_code=404,
            detail="Frontend build not found. Build apps/web before serving the root page.",
        )

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/scopes")
    def list_scopes() -> dict:
        return build_scope_payload()

    @app.get("/api/directories")
    def list_directories(path: str | None = None) -> dict:
        current = Path(path).expanduser() if path else browse_root
        try:
            current = current.resolve()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Folder not found") from exc
        if browse_root not in current.parents and current != browse_root:
            raise HTTPException(status_code=400, detail="Path is outside the allowed root")
        if not current.exists() or not current.is_dir():
            raise HTTPException(status_code=404, detail="Folder not found")

        directories = sorted(
            [
                child
                for child in current.iterdir()
                if child.is_dir() and not child.name.startswith(".")
            ],
            key=lambda item: item.name.lower(),
        )
        parent = str(current.parent) if current != browse_root else None
        return {
            "root": str(browse_root),
            "current": str(current),
            "parent": parent,
            "directories": [{"name": directory.name, "path": str(directory)} for directory in directories],
        }

    @app.post("/api/scopes")
    def create_scope(payload: ScopeCreateRequest) -> dict:
        if not Path(payload.path).expanduser().exists():
            raise HTTPException(status_code=400, detail="Folder path does not exist")
        add_configured_memory_root(payload.scope, payload.path)
        return build_scope_payload()

    def _delete_scope(scope: str) -> dict:
        with ingest_lock:
            if ingest_status.state == "running":
                raise HTTPException(status_code=409, detail="Cannot delete a scope while ingest is running")

        source_repository.delete_memory_scope(scope)
        remove_configured_memory_root(scope)
        with ingest_lock:
            if ingest_status.scope == scope:
                ingest_status.scope = None
            if ingest_status.per_scope and scope in ingest_status.per_scope:
                ingest_status.per_scope.pop(scope, None)
        return build_scope_payload()

    @app.delete("/api/scopes")
    def delete_scope(scope: str = Query(min_length=1)) -> dict:
        return _delete_scope(scope)

    @app.delete("/api/scopes/{scope}")
    def delete_scope_legacy(scope: str) -> dict:
        return _delete_scope(scope)

    @app.get("/api/ingest")
    def get_ingest_status() -> dict:
        with ingest_lock:
            return asdict(ingest_status)

    @app.get("/api/onenote/sync")
    def get_onenote_sync_status() -> dict:
        with onenote_lock:
            return asdict(onenote_status)

    @app.get("/api/ingest/failures")
    def get_ingest_failures(
        limit: int = Query(default=8, ge=1, le=25),
        memory_scope: str | None = None,
    ) -> dict:
        return {
            "failures": audit_repository.list_recent_failures(
                event_type="file_ingest",
                limit=limit,
                memory_scope=memory_scope,
            )
        }

    @app.post("/api/ingest")
    def trigger_ingest(payload: IngestRequest) -> dict:
        with ingest_lock:
            if ingest_status.state == "running":
                raise HTTPException(status_code=409, detail="An ingest is already running")
            thread = Thread(target=run_ingest_job, args=(payload.scope,), daemon=True)
            thread.start()
            return {"accepted": True, "scope": payload.scope}

    @app.post("/api/onenote/sync")
    def trigger_onenote_sync(payload: OneNoteSyncRequest) -> dict:
        with onenote_lock:
            if onenote_status.state in {"running", "auth_required"}:
                raise HTTPException(status_code=409, detail="A OneNote sync is already running")
            thread = Thread(target=run_onenote_sync_job, args=(payload.since,), daemon=True)
            thread.start()
            return {"accepted": True, "since": payload.since}

    @app.get("/api/search")
    def search(
        query: str = Query(min_length=1),
        limit: int = Query(default=12, ge=1, le=25),
        memory_scope: str | None = None,
        source_type: list[str] | None = Query(default=None),
    ) -> dict:
        if memory_scope is None:
            response = retriever.search(
                SearchRequest(
                    query=query,
                    limit=limit,
                    filters={"source_types": source_type or []},
                )
            )
            return response.model_dump(mode="json")
        return service.search_memory(
            SearchMemoryRequest(
                query=query,
                limit=limit,
                memory_scope=memory_scope,
                filters={"source_types": source_type or []},
            )
        )

    @app.get("/api/sources")
    def list_sources(
        limit: int = Query(default=24, ge=1, le=100),
        memory_scope: str | None = None,
        source_type: str | None = None,
    ) -> dict:
        return service.list_sources(
            ListSourcesRequest(limit=limit, memory_scope=memory_scope, source_type=source_type)
        )

    @app.get("/api/sources/{source_id}")
    def get_source(source_id: str) -> dict:
        try:
            return service.get_source(GetSourceRequest(source_id=source_id))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/chunks/{chunk_id}/context")
    def get_chunk_context(
        chunk_id: str,
        before: int = Query(default=1, ge=0, le=10),
        after: int = Query(default=1, ge=0, le=10),
    ) -> dict:
        return service.get_chunk_context(
            GetChunkContextRequest(chunk_id=chunk_id, before=before, after=after)
        )

    @app.get("/api/activity")
    def recent_activity(
        limit: int = Query(default=18, ge=1, le=50),
        memory_scope: str | None = None,
    ) -> dict:
        return {
            "recent_sources": [
                source.model_dump(mode="json")
                for source in source_repository.list_sources(limit=limit, memory_scope=memory_scope)
            ],
            "recent_memories": [
                source.model_dump(mode="json")
                for source in source_repository.list_sources(
                    limit=limit,
                    memory_scope=memory_scope,
                    source_type="agent_memory",
                )
            ],
        }

    return app
