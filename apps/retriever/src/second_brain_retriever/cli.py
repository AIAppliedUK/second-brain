from __future__ import annotations

import argparse
import json

from second_brain_core.config import Settings
from second_brain_core.db import Database
from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_core.logging import configure_logging
from second_brain_core.repository import ChunkRepository
from second_brain_core.retrieval import HybridRetriever
from second_brain_models import SearchFilters, SearchRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the second brain")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--memory-scope",
        action="append",
        dest="memory_scopes",
        help=(
            "Restrict retrieval to one or more memory scopes. "
            "Repeat the flag to search multiple scopes."
        ),
    )
    args = parser.parse_args()
    configure_logging()
    settings = Settings()
    retriever = HybridRetriever(
        chunk_repository=ChunkRepository(Database(settings.db_dsn)),
        embedder=DeterministicEmbedder(settings.embedding_dimension),
    )
    response = retriever.search(
        SearchRequest(
            query=args.query,
            limit=args.limit,
            filters=SearchFilters(memory_scopes=args.memory_scopes),
        )
    )
    print(json.dumps(response.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
