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
