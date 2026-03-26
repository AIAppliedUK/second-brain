from __future__ import annotations

from second_brain_core.config import Settings
from second_brain_core.db import Database
from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_core.logging import configure_logging
from second_brain_core.repository import ChunkRepository, SourceRepository
from second_brain_core.retrieval import HybridRetriever

from .server import build_mcp_server
from .service import MCPService


def main() -> None:
    configure_logging()
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
    server = build_mcp_server(service, settings.mcp_server_name)
    server.run()


if __name__ == "__main__":
    main()
