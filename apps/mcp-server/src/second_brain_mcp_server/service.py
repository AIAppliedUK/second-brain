from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from second_brain_core import ChunkingConfig, chunk_document
from second_brain_core.repository import ChunkRepository, SourceRepository
from second_brain_core.retrieval import HybridRetriever
from second_brain_models import (
    AuditEvent,
    ChunkUpsert,
    GetChunkContextRequest,
    GetSourceRequest,
    ListSourcesRequest,
    RememberRequest,
    SearchMemoryRequest,
    SearchRequest,
    SourceUpsert,
)


class MCPService:
    def __init__(
        self,
        retriever: HybridRetriever,
        source_repository: SourceRepository,
        chunk_repository: ChunkRepository,
        embedder,
        audit_repository=None,
        default_memory_scope: str | None = None,
    ) -> None:
        self.retriever = retriever
        self.source_repository = source_repository
        self.chunk_repository = chunk_repository
        self.embedder = embedder
        self.audit_repository = audit_repository
        self.default_memory_scope = default_memory_scope
        self.chunking_config = ChunkingConfig()

    def _resolve_memory_scopes(self, request: SearchMemoryRequest) -> list[str] | None:
        scopes = list(request.filters.memory_scopes or [])
        if request.memory_scope:
            scopes.append(request.memory_scope)
        if not scopes and self.default_memory_scope:
            scopes.append(self.default_memory_scope)
        return list(dict.fromkeys(scopes)) or None

    def _resolve_write_memory_scope(self, request: RememberRequest) -> str:
        return request.memory_scope or self.default_memory_scope or "general"

    def _build_memory_text(self, request: RememberRequest, memory_scope: str) -> str:
        title = request.title or self._default_memory_title(request)
        lines = [f"# {title}", "", "## Memory Record", f"Kind: {request.memory_kind}"]
        if request.project:
            lines.append(f"Project: {request.project}")
        if request.agent_id:
            lines.append(f"Agent: {request.agent_id}")
        if request.session_id:
            lines.append(f"Session: {request.session_id}")
        if request.run_id:
            lines.append(f"Run: {request.run_id}")
        if request.issue_refs:
            lines.append(f"Issues: {', '.join(request.issue_refs)}")
        if request.tags:
            lines.append(f"Tags: {', '.join(request.tags)}")
        if request.significance:
            lines.append(f"Significance: {request.significance}")
        lines.append(f"Memory scope: {memory_scope}")
        if request.happened_at:
            lines.append(f"Happened at: {request.happened_at.isoformat()}")
        if request.summary:
            lines.extend(["", "## Summary", request.summary])
        lines.extend(["", "## Details", request.body.strip()])
        return "\n".join(lines).strip()

    def _default_memory_title(self, request: RememberRequest) -> str:
        happened_at = request.happened_at or datetime.now(UTC)
        prefix = request.project or request.memory_kind.replace("_", " ").title()
        return f"{prefix} memory {happened_at.date().isoformat()}"

    def _parse_memory_sections(self, text: str) -> list[tuple[list[str], str]]:
        sections: list[tuple[list[str], str]] = []
        headings: list[str] = []
        buffer: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                if buffer:
                    sections.append((headings.copy(), "\n".join(buffer).strip()))
                    buffer = []
                level = len(stripped) - len(stripped.lstrip("#"))
                heading_text = stripped[level:].strip()
                headings = headings[: max(level - 1, 0)]
                headings.append(heading_text)
                continue
            buffer.append(line)
        if buffer:
            sections.append((headings.copy(), "\n".join(buffer).strip()))
        return sections or [([], text)]

    def _build_memory_metadata(self, request: RememberRequest, memory_scope: str) -> dict:
        happened_at = request.happened_at.isoformat() if request.happened_at else None
        metadata = {
            "memory_scope": memory_scope,
            "memory_kind": request.memory_kind,
            "project": request.project,
            "agent_id": request.agent_id,
            "session_id": request.session_id,
            "run_id": request.run_id,
            "significance": request.significance,
            "happened_at": happened_at,
            "happened_on": happened_at[:10] if happened_at else None,
            "tags": request.tags,
            "tags_text": ", ".join(request.tags),
            "issue_refs": request.issue_refs,
            "issue_refs_text": ", ".join(request.issue_refs),
            **request.metadata,
        }
        return {key: value for key, value in metadata.items() if value not in (None, "", [], {})}

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

    def remember(self, request: RememberRequest) -> dict:
        memory_scope = self._resolve_write_memory_scope(request)
        happened_at = request.happened_at or datetime.now(UTC)
        title = request.title or self._default_memory_title(request)
        canonical_text = self._build_memory_text(request, memory_scope)
        metadata = self._build_memory_metadata(request, memory_scope)
        external_id = request.external_id or str(UUID(bytes=hashlib.sha256(
            f"{memory_scope}:{request.source_type}:{title}:{canonical_text}".encode("utf-8")
        ).digest()[:16], version=4))
        source = SourceUpsert(
            memory_scope=memory_scope,
            source_type=request.source_type,
            external_id=external_id,
            title=title,
            uri=f"memory://{memory_scope}/{request.source_type}/{external_id}",
            container_lineage=[
                part
                for part in ["agent-memory", request.project, request.memory_kind]
                if part
            ],
            created_at=happened_at,
            updated_at=happened_at,
            content_hash=hashlib.sha256(canonical_text.encode("utf-8")).hexdigest(),
            metadata=metadata,
            raw_text=canonical_text,
            canonical_text=canonical_text,
        )
        persisted_source = self.source_repository.upsert_source(source)
        chunk_tuples = chunk_document(
            canonical_text,
            self._parse_memory_sections(canonical_text),
            self.chunking_config,
        )
        chunks = [
            ChunkUpsert(
                source_id=persisted_source.id,
                memory_scope=memory_scope,
                chunk_index=index,
                heading_path=heading_path,
                chunk_text=chunk_text,
                token_count=len(chunk_text.split()),
                metadata=metadata,
                embedding=self.embedder.embed(chunk_text),
            )
            for index, (heading_path, chunk_text) in enumerate(chunk_tuples)
        ]
        self.chunk_repository.replace_chunks(persisted_source.id, chunks)
        if self.audit_repository is not None:
            self.audit_repository.add_event(
                AuditEvent(
                    source_id=persisted_source.id,
                    event_type="agent_memory_write",
                    status="success",
                    message=f"Stored agent memory '{title}'",
                    metadata={
                        "memory_scope": memory_scope,
                        "source_type": request.source_type,
                        "memory_kind": request.memory_kind,
                        "project": request.project,
                        "chunk_count": len(chunks),
                    },
                )
            )
        return {
            "source_id": str(persisted_source.id),
            "memory_scope": memory_scope,
            "source_type": request.source_type,
            "title": title,
            "uri": persisted_source.uri,
            "chunk_count": len(chunks),
            "metadata": metadata,
        }
