from __future__ import annotations

import argparse

from second_brain_core.config import Settings
from second_brain_core.db import Database
from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_core.logging import configure_logging
from second_brain_core.repository import ChunkRepository, SourceRepository
from second_brain_core.retrieval import HybridRetriever

from .server import build_mcp_server
from .service import MCPService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the second-brain MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        help="MCP transport to use. Defaults to SECOND_BRAIN_MCP_TRANSPORT or stdio.",
    )
    parser.add_argument(
        "--host",
        help="Host to bind for HTTP transports. Defaults to SECOND_BRAIN_MCP_HOST.",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port to bind for HTTP transports. Defaults to SECOND_BRAIN_MCP_PORT.",
    )
    parser.add_argument(
        "--streamable-http-path",
        help=(
            "HTTP path for streamable HTTP transport. "
            "Defaults to SECOND_BRAIN_MCP_STREAMABLE_HTTP_PATH."
        ),
    )
    parser.add_argument(
        "--sse-mount-path",
        help="Mount path for SSE transport. Defaults to SECOND_BRAIN_MCP_SSE_MOUNT_PATH.",
    )
    return parser.parse_args()


def main() -> None:
    configure_logging()
    args = _parse_args()
    settings = Settings()
    database = Database(settings.db_dsn)
    chunk_repository = ChunkRepository(database)
    source_repository = SourceRepository(database)
    retriever = HybridRetriever(
        chunk_repository, DeterministicEmbedder(settings.embedding_dimension)
    )
    service = MCPService(
        retriever,
        source_repository,
        chunk_repository,
        default_memory_scope=settings.default_memory_scope,
    )
    transport = args.transport or settings.mcp_transport
    server = build_mcp_server(
        service,
        settings.mcp_server_name,
        host=args.host or settings.mcp_host,
        port=args.port or settings.mcp_port,
        streamable_http_path=args.streamable_http_path or settings.mcp_streamable_http_path,
    )
    server.run(
        transport=transport,
        mount_path=args.sse_mount_path or settings.mcp_sse_mount_path,
    )


if __name__ == "__main__":
    main()
