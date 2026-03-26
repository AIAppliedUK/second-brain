import json
import sys
from uuid import uuid4

from second_brain_models import (
    SearchCitation,
    SearchFilters,
    SearchHit,
    SearchResponse,
)
from second_brain_retriever import cli


class FakeRetriever:
    def __init__(self):
        self.request = None

    def search(self, request):
        self.request = request
        return SearchResponse(
            query=request.query,
            hits=[
                SearchHit(
                    chunk_id=uuid4(),
                    source_id=uuid4(),
                    memory_scope="general",
                    score=1.0,
                    lexical_score=1.0,
                    vector_score=0.5,
                    chunk_text="hello world",
                    source_title="Example",
                    source_uri="file:///tmp/example.md",
                    source_type="local_file",
                    citation=SearchCitation(
                        source_id=uuid4(),
                        chunk_id=uuid4(),
                        memory_scope="general",
                        title="Example",
                        uri="file:///tmp/example.md",
                        source_type="local_file",
                        heading_path=[],
                        chunk_index=0,
                    ),
                )
            ],
        )


class StubSettings:
    db_dsn = "dsn"
    embedding_dimension = 8


def test_retriever_cli_builds_memory_scope_filters(monkeypatch, capsys):
    fake_retriever = FakeRetriever()

    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "Settings", lambda: StubSettings())
    monkeypatch.setattr(cli, "Database", lambda dsn: object())
    monkeypatch.setattr(cli, "ChunkRepository", lambda database: object())
    monkeypatch.setattr(cli, "DeterministicEmbedder", lambda dimension: object())
    monkeypatch.setattr(
        cli,
        "HybridRetriever",
        lambda chunk_repository, embedder: fake_retriever,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "second_brain_retriever.cli",
            "tenant context",
            "--limit",
            "2",
            "--memory-scope",
            "general",
            "--memory-scope",
            "project:ai-recruitment",
        ],
    )

    cli.main()

    assert fake_retriever.request is not None
    assert fake_retriever.request.query == "tenant context"
    assert fake_retriever.request.limit == 2
    assert fake_retriever.request.filters == SearchFilters(
        memory_scopes=["general", "project:ai-recruitment"]
    )

    output = json.loads(capsys.readouterr().out)
    assert output["query"] == "tenant context"
    assert output["hits"][0]["source_title"] == "Example"
