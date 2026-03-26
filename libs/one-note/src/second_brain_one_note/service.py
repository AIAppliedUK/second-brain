from __future__ import annotations

from second_brain_core import ChunkingConfig, chunk_document
from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_models import AuditEvent, CanonicalDocument, ChunkUpsert, SourceUpsert

from .client import GraphClient
from .normalize import html_to_text


class OneNoteIngester:
    def __init__(
        self,
        graph_client: GraphClient,
        embedder: DeterministicEmbedder,
        memory_scope: str,
        chunking_config: ChunkingConfig | None = None,
    ) -> None:
        self.graph_client = graph_client
        self.embedder = embedder
        self.memory_scope = memory_scope
        self.chunking_config = chunking_config or ChunkingConfig()

    def ingest(self, since: str | None = None) -> tuple[list[CanonicalDocument], list[AuditEvent]]:
        notebooks = {item["id"]: item for item in self.graph_client.list_notebooks()}
        sections = {item["id"]: item for item in self.graph_client.list_sections()}
        pages = self.graph_client.list_pages(since=since)
        documents: list[CanonicalDocument] = []
        events: list[AuditEvent] = []
        for page in pages:
            html = self.graph_client.get_page_content(page["id"])
            text = html_to_text(html)
            notebook_id = page.get("parentNotebook", {}).get("id")
            section_id = page.get("parentSection", {}).get("id")
            lineage = [
                notebooks.get(notebook_id, {}).get("displayName", ""),
                sections.get(section_id, {}).get("displayName", ""),
                page.get("title", ""),
            ]
            source = SourceUpsert(
                memory_scope=self.memory_scope,
                source_type="onenote",
                external_id=page["id"],
                title=page.get("title", page["id"]),
                uri=page.get("links", {}).get("oneNoteWebUrl", {}).get("href", ""),
                container_lineage=[item for item in lineage if item],
                created_at=page.get("createdDateTime"),
                updated_at=page.get("lastModifiedDateTime"),
                content_hash=str(page.get("contentUrl", ""))
                + str(page.get("lastModifiedDateTime", "")),
                metadata={
                    "memory_scope": self.memory_scope,
                    "notebook_id": notebook_id,
                    "section_id": section_id,
                    "page_id": page["id"],
                },
                raw_html=html,
                raw_text=text,
                canonical_text=text,
            )
            chunk_tuples = chunk_document(
                text, [([page.get("title", "")], text)], self.chunking_config
            )
            chunks = [
                ChunkUpsert(
                    source_id=source.id,
                    memory_scope=self.memory_scope,
                    chunk_index=index,
                    heading_path=heading_path,
                    chunk_text=chunk_text,
                    token_count=len(chunk_text.split()),
                    metadata={"page_id": page["id"], "memory_scope": self.memory_scope},
                    embedding=self.embedder.embed(chunk_text),
                )
                for index, (heading_path, chunk_text) in enumerate(chunk_tuples)
            ]
            documents.append(CanonicalDocument(source=source, chunks=chunks))
            events.append(
                AuditEvent(
                    source_id=source.id,
                    event_type="onenote_sync",
                    status="success",
                    message=f"Synced OneNote page {page['id']}",
                    metadata={
                        "page_id": page["id"],
                        "chunk_count": len(chunks),
                        "memory_scope": self.memory_scope,
                    },
                )
            )
        return documents, events
