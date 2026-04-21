import json
import time
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_one_note import (
    DeviceCodeAuthProvider,
    GraphClient,
    OneNoteIngester,
    RetryTransport,
)


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request_json(self, url, headers):
        self.calls.append(url)
        if "notebooks" in url:
            return {"value": [{"id": "n1", "displayName": "Notebook"}]}
        if "sections?" in url:
            return {"value": [{"id": "s1", "displayName": "Section"}]}
        if "sections/s1/pages" in url:
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
        return {"value": []}

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


def test_graph_client_encodes_since_filter():
    transport = FakeTransport()
    client = GraphClient("token", RetryTransport(transport, retries=1), "agent")

    client.list_pages_for_section("s1", since="2026-03-01T00:00:00Z")

    assert transport.calls[0].startswith(
        "https://graph.microsoft.com/v1.0/me/onenote/sections/s1/pages?"
    )
    assert "%24filter=lastModifiedDateTime+ge+2026-03-01T00%3A00%3A00Z" in transport.calls[0]


class ErrorTransport:
    def request_json(self, url, headers):
        raise HTTPError(
            url,
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":{"code":"BadRequest","message":"Detailed Graph error"}}'),
        )

    def request_text(self, url, headers):
        raise HTTPError(
            url,
            400,
            "Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":{"code":"BadRequest","message":"Detailed Graph error"}}'),
        )


class NotFoundTransport(FakeTransport):
    def request_text(self, url, headers):
        if "/me/onenote/pages/p1/content" in url:
            raise HTTPError(
                url,
                404,
                "Not Found",
                hdrs=None,
                fp=BytesIO(b'{"error":{"code":"ItemNotFound","message":"Not Found"}}'),
            )
        return super().request_text(url, headers)


class RateLimitTransport(FakeTransport):
    def request_json(self, url, headers):
        if "sections?" in url:
            return {"value": [{"id": "s1", "displayName": "Section"}]}
        if "sections/s1/pages" in url:
            return {
                "value": [
                    {
                        "id": "p1",
                        "title": "Rate limited page",
                        "parentNotebook": {"id": "n1"},
                        "parentSection": {"id": "s1"},
                        "links": {"oneNoteWebUrl": {"href": "https://example.test/p1"}},
                        "lastModifiedDateTime": "2025-01-01T00:00:00Z",
                    },
                    {
                        "id": "p2",
                        "title": "Recovered page",
                        "parentNotebook": {"id": "n1"},
                        "parentSection": {"id": "s1"},
                        "links": {"oneNoteWebUrl": {"href": "https://example.test/p2"}},
                        "lastModifiedDateTime": "2025-01-02T00:00:00Z",
                    },
                ]
            }
        return super().request_json(url, headers)

    def request_text(self, url, headers):
        if "/me/onenote/pages/p1/content" in url:
            raise HTTPError(
                url,
                429,
                "Too Many Requests",
                hdrs=None,
                fp=BytesIO(
                    b'{"error":{"code":"20166","message":"The app has issued too many requests on behalf of this user in a short time period."}}'
                ),
            )
        if "/me/onenote/pages/p2/content" in url:
            return "<html><body><h1>Recovered page</h1><p>Important note</p></body></html>"
        return super().request_text(url, headers)


def test_retry_transport_includes_graph_error_body():
    client = GraphClient("token", RetryTransport(ErrorTransport(), retries=1), "agent")

    try:
        client.list_pages_for_section("s1")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert "HTTP 400" in message
    assert "Detailed Graph error" in message
    assert "graph.microsoft.com" in message


def test_onenote_ingester_skips_missing_page_content():
    transport = NotFoundTransport()
    client = GraphClient("token", RetryTransport(transport, retries=1), "agent")

    documents, events = OneNoteIngester(
        client, DeterministicEmbedder(32), memory_scope="general"
    ).ingest()

    assert documents == []
    assert events == []


def test_onenote_ingester_continues_after_rate_limited_page():
    transport = RateLimitTransport()
    client = GraphClient("token", RetryTransport(transport, retries=1), "agent")

    progress = []
    documents, events = OneNoteIngester(
        client, DeterministicEmbedder(32), memory_scope="general", request_delay_seconds=0.0
    ).ingest(progress_callback=progress.append)

    assert len(documents) == 1
    assert documents[0].source.external_id == "p2"
    assert [event.status for event in events] == ["failed", "success"]
    assert progress == [1]


def test_onenote_ingester_lists_pages_per_section():
    transport = FakeTransport()
    client = GraphClient("token", RetryTransport(transport, retries=1), "agent")

    OneNoteIngester(client, DeterministicEmbedder(32), memory_scope="general", request_delay_seconds=0.0).ingest()

    assert any("sections/s1/pages" in call for call in transport.calls)
    assert not any("/me/onenote/pages?" in call for call in transport.calls)


class FakeAuthProvider(DeviceCodeAuthProvider):
    def __init__(self, *args, refresh_response=None, device_token_response=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.refresh_response = refresh_response or {}
        self.device_token_response = device_token_response or {}
        self.refresh_calls = 0
        self.device_code_calls = 0
        self.device_token_calls = 0
        self.opened_uris = []

    def _refresh_access_token(self, refresh_token: str):
        self.refresh_calls += 1
        return self.refresh_response

    def _request_device_code(self):
        self.device_code_calls += 1
        return {
            "device_code": "device-code",
            "expires_in": "900",
            "interval": "0",
            "message": "Use code ABC",
            "verification_uri": "https://login.microsoft.com/device",
            "verification_uri_complete": "https://login.microsoft.com/device?code=ABC123",
            "user_code": "ABC123",
        }

    def _request_token(self, device_code: str):
        self.device_token_calls += 1
        return self.device_token_response

    def _open_verification_uri(self, device_code):
        verification_uri = device_code.get("verification_uri_complete") or device_code.get(
            "verification_uri"
        )
        if verification_uri:
            self.opened_uris.append(verification_uri)


def _write_token_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_device_code_provider_reuses_valid_cached_access_token(tmp_path):
    cache_path = tmp_path / "onenote-token.json"
    _write_token_cache(
        cache_path,
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "scopes": ["offline_access", "Notes.Read.All", "User.Read"],
            "access_token": "cached-access-token",
            "refresh_token": "cached-refresh-token",
            "expires_at": time.time() + 3600,
        },
    )
    provider = FakeAuthProvider(
        tenant_id="tenant",
        client_id="client",
        scopes=["offline_access", "Notes.Read.All", "User.Read"],
        token_cache_path=cache_path,
    )

    access_token = provider.get_access_token()

    assert access_token == "cached-access-token"
    assert provider.refresh_calls == 0
    assert provider.device_code_calls == 0


def test_device_code_provider_refreshes_and_updates_cache(tmp_path):
    cache_path = tmp_path / "onenote-token.json"
    _write_token_cache(
        cache_path,
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "scopes": ["offline_access", "Notes.Read.All", "User.Read"],
            "access_token": "expired-access-token",
            "refresh_token": "cached-refresh-token",
            "expires_at": time.time() - 10,
        },
    )
    provider = FakeAuthProvider(
        tenant_id="tenant",
        client_id="client",
        scopes=["offline_access", "Notes.Read.All", "User.Read"],
        token_cache_path=cache_path,
        refresh_response={
            "access_token": "fresh-access-token",
            "refresh_token": "fresh-refresh-token",
            "expires_in": "1800",
        },
    )

    access_token = provider.get_access_token()

    cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    assert access_token == "fresh-access-token"
    assert provider.refresh_calls == 1
    assert provider.device_code_calls == 0
    assert cached_payload["access_token"] == "fresh-access-token"
    assert cached_payload["refresh_token"] == "fresh-refresh-token"


def test_device_code_provider_falls_back_to_device_code_when_refresh_fails(tmp_path, capsys):
    cache_path = tmp_path / "onenote-token.json"
    _write_token_cache(
        cache_path,
        {
            "tenant_id": "tenant",
            "client_id": "client",
            "scopes": ["offline_access", "Notes.Read.All", "User.Read"],
            "access_token": "expired-access-token",
            "refresh_token": "stale-refresh-token",
            "expires_at": time.time() - 10,
        },
    )
    provider = FakeAuthProvider(
        tenant_id="tenant",
        client_id="client",
        scopes=["offline_access", "Notes.Read.All", "User.Read"],
        token_cache_path=cache_path,
        refresh_response={},
        device_token_response={
            "access_token": "device-access-token",
            "refresh_token": "device-refresh-token",
            "expires_in": "1800",
        },
    )

    access_token = provider.get_access_token()

    captured = capsys.readouterr()
    assert access_token == "device-access-token"
    assert provider.refresh_calls == 1
    assert provider.device_code_calls == 1
    assert provider.device_token_calls == 1
    assert "Use code ABC" in captured.out


def test_device_code_provider_auto_opens_browser_when_login_is_needed(tmp_path):
    cache_path = tmp_path / "onenote-token.json"
    provider = FakeAuthProvider(
        tenant_id="tenant",
        client_id="client",
        scopes=["offline_access", "Notes.Read.All", "User.Read"],
        token_cache_path=cache_path,
        device_token_response={
            "access_token": "device-access-token",
            "refresh_token": "device-refresh-token",
            "expires_in": "1800",
        },
    )

    provider.get_access_token()

    assert provider.opened_uris == ["https://login.microsoft.com/device?code=ABC123"]


def test_device_code_provider_invokes_device_code_callback(tmp_path):
    cache_path = tmp_path / "onenote-token.json"
    captured = []
    provider = FakeAuthProvider(
        tenant_id="tenant",
        client_id="client",
        scopes=["offline_access", "Notes.Read.All", "User.Read"],
        token_cache_path=cache_path,
        auto_open_browser=False,
        on_device_code=captured.append,
        device_token_response={
            "access_token": "device-access-token",
            "refresh_token": "device-refresh-token",
            "expires_in": "1800",
        },
    )

    access_token = provider.get_access_token()

    assert access_token == "device-access-token"
    assert provider.opened_uris == []
    assert len(captured) == 1
    assert captured[0]["user_code"] == "ABC123"
    assert captured[0]["verification_uri"] == "https://login.microsoft.com/device"
