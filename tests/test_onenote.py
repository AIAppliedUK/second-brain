from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_one_note import GraphClient, OneNoteIngester, RetryTransport


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request_json(self, url, headers):
        self.calls.append(url)
        if "notebooks" in url:
            return {"value": [{"id": "n1", "displayName": "Notebook"}]}
        if "sections" in url:
            return {"value": [{"id": "s1", "displayName": "Section"}]}
        return {
            "value": [
                {
                    "id": "p1",
                    "title": "Page",
                    "parentNotebook": {"id": "n1"},
                    "parentSection": {"id": "s1"},
                    "links": {"oneNoteWebUrl": {"href": "https://example.test/page"}},
                    "lastModifiedDateTime": "2025-01-01T00:00:00Z",
                }
            ]
        }

    def request_text(self, url, headers):
        self.calls.append(url)
        return "<html><body><h1>Page</h1><p>Important note</p></body></html>"


def test_onenote_ingester_preserves_identifiers_and_html():
    client = GraphClient("token", RetryTransport(FakeTransport(), retries=1), "agent")
    documents, events = OneNoteIngester(
        client, DeterministicEmbedder(32), memory_scope="general"
    ).ingest()
    assert len(documents) == 1
    source = documents[0].source
    assert source.memory_scope == "general"
    assert source.metadata["page_id"] == "p1"
    assert source.metadata["notebook_id"] == "n1"
    assert "Important note" in source.raw_text
    assert events[0].status == "success"
