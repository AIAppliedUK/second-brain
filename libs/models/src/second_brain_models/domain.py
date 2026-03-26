from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SourceUpsert(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    memory_scope: str = "general"
    source_type: str
    external_id: str
    title: str
    uri: str
    container_lineage: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    content_hash: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_html: str | None = None
    raw_text: str | None = None
    canonical_text: str | None = None
    status: str = "active"


class SourceRecord(SourceUpsert):
    ingested_at: datetime | None = None
    deleted_at: datetime | None = None


class SourceSummary(BaseModel):
    id: UUID
    memory_scope: str = "general"
    source_type: str
    title: str
    uri: str
    container_lineage: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    ingested_at: datetime | None = None
    status: str
    chunk_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkUpsert(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    memory_scope: str = "general"
    chunk_index: int
    heading_path: list[str] = Field(default_factory=list)
    chunk_text: str
    token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: list[float]


class ChunkRecord(ChunkUpsert):
    lexical_score: float | None = None
    vector_score: float | None = None
    combined_score: float | None = None
    source: SourceRecord | None = None


class AuditEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_id: UUID | None = None
    event_type: str
    status: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class CanonicalDocument(BaseModel):
    source: SourceUpsert
    chunks: list[ChunkUpsert]


class SearchFilters(BaseModel):
    memory_scopes: list[str] | None = None
    source_types: list[str] | None = None
    containers: list[str] | None = None
    metadata_matches: dict[str, str] = Field(default_factory=dict)
    updated_after: datetime | None = None
    updated_before: datetime | None = None


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    lexical_limit: int = 25
    vector_limit: int = 25
    filters: SearchFilters = Field(default_factory=SearchFilters)


class SearchCitation(BaseModel):
    source_id: UUID
    chunk_id: UUID
    memory_scope: str = "general"
    title: str
    uri: str
    source_type: str
    heading_path: list[str]
    chunk_index: int


class SearchHit(BaseModel):
    chunk_id: UUID
    source_id: UUID
    memory_scope: str = "general"
    score: float
    lexical_score: float | None = None
    vector_score: float | None = None
    chunk_text: str
    source_title: str
    source_uri: str
    source_type: str
    heading_path: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    citation: SearchCitation


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
