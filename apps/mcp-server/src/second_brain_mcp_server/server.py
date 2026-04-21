from __future__ import annotations

from second_brain_models import (
    GetChunkContextRequest,
    GetSourceRequest,
    ListSourcesRequest,
    RememberRequest,
    SearchMemoryRequest,
)

from .service import MCPService


def build_mcp_server(
    service: MCPService,
    server_name: str,
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError(
            "The MCP SDK is not installed. "
            "Install project dependencies before starting the stdio server."
        ) from exc

    server = FastMCP(
        server_name,
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
    )

    @server.tool()
    def search_memory(
        query: str,
        limit: int = 10,
        memory_scope: str | None = None,
        source_types: list[str] | None = None,
        metadata_matches: dict[str, str] | None = None,
    ) -> dict:
        return service.search_memory(
            SearchMemoryRequest.model_validate(
                {
                    "query": query,
                    "limit": limit,
                    "memory_scope": memory_scope,
                    "filters": {
                        "source_types": source_types or [],
                        "metadata_matches": metadata_matches or {},
                    },
                }
            )
        )

    @server.tool()
    def get_source(source_id: str) -> dict:
        return service.get_source(GetSourceRequest(source_id=source_id))

    @server.tool()
    def get_chunk_context(chunk_id: str, before: int = 1, after: int = 1) -> dict:
        return service.get_chunk_context(
            GetChunkContextRequest(chunk_id=chunk_id, before=before, after=after)
        )

    @server.tool()
    def list_sources(
        limit: int = 25,
        source_type: str | None = None,
        memory_scope: str | None = None,
    ) -> dict:
        return service.list_sources(
            ListSourcesRequest(limit=limit, source_type=source_type, memory_scope=memory_scope)
        )

    @server.tool()
    def remember(
        body: str,
        title: str | None = None,
        memory_scope: str | None = None,
        source_type: str = "agent_memory",
        external_id: str | None = None,
        memory_kind: str = "episodic",
        summary: str | None = None,
        project: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        significance: str | None = None,
        happened_at: str | None = None,
        tags: list[str] | None = None,
        issue_refs: list[str] | None = None,
        metadata: dict | None = None,
    ) -> dict:
        payload = {
            "body": body,
            "title": title,
            "memory_scope": memory_scope,
            "source_type": source_type,
            "external_id": external_id,
            "memory_kind": memory_kind,
            "summary": summary,
            "project": project,
            "agent_id": agent_id,
            "session_id": session_id,
            "run_id": run_id,
            "significance": significance,
            "happened_at": happened_at,
            "tags": tags or [],
            "issue_refs": issue_refs or [],
            "metadata": metadata or {},
        }
        return service.remember(RememberRequest.model_validate(payload))

    return server
