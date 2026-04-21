from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .domain import SearchFilters


class SearchMemoryRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=25)
    memory_scope: str | None = None
    filters: SearchFilters = Field(default_factory=SearchFilters)


class GetSourceRequest(BaseModel):
    source_id: str


class GetChunkContextRequest(BaseModel):
    chunk_id: str
    before: int = Field(default=1, ge=0, le=10)
    after: int = Field(default=1, ge=0, le=10)


class ListSourcesRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)
    source_type: str | None = None
    memory_scope: str | None = None


class RememberRequest(BaseModel):
    body: str = Field(min_length=1)
    title: str | None = None
    memory_scope: str | None = None
    source_type: str = "agent_memory"
    external_id: str | None = None
    memory_kind: str = "episodic"
    summary: str | None = None
    project: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    significance: str | None = None
    happened_at: datetime | None = None
    tags: list[str] = Field(default_factory=list)
    issue_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
