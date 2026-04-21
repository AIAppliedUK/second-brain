import sys
import types
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

openpyxl_module = types.ModuleType("openpyxl")
sys.modules.setdefault("openpyxl", openpyxl_module)

errors_module = types.ModuleType("pypdf.errors")


class _PdfReadError(Exception):
    pass


class _PdfStreamError(Exception):
    pass


errors_module.PdfReadError = _PdfReadError
errors_module.PdfStreamError = _PdfStreamError
pdf_module = types.ModuleType("pypdf")
pdf_module.PdfReader = lambda *args, **kwargs: types.SimpleNamespace(pages=[])
pdf_module.errors = errors_module
sys.modules.setdefault("pypdf", pdf_module)
sys.modules.setdefault("pypdf.errors", errors_module)

sys.modules.setdefault(
    "xlrd",
    types.SimpleNamespace(
        XL_CELL_NUMBER=2,
        open_workbook=lambda *args, **kwargs: None,
    ),
)

import second_brain_api.app as app_module
import second_brain_api.cli as cli_module
from second_brain_api.app import create_app


class _FakeDatabase:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self):
        yield None


class _FakeSourceRepository:
    def __init__(self, database) -> None:
        self.scopes = [
            {
                "memory_scope": "project:alpha",
                "source_count": 2,
                "source_type_count": 1,
                "last_updated_at": None,
            }
        ]

    def list_memory_scopes(self):
        return list(self.scopes)

    def delete_memory_scope(self, scope: str):
        self.scopes = [row for row in self.scopes if row["memory_scope"] != scope]
        return {"deleted_sources": 1, "deleted_chunks": 3, "deleted_audit_events": 2}


def test_api_health_endpoint():
    client = TestClient(create_app())
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_cli_defaults_to_web_proxy_port(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["second_brain_api"])
    args = cli_module._parse_args()

    assert args.port == 8090


def test_delete_scope_endpoint_removes_scope_and_data(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = workspace / ".env"
    env_file.write_text("SECOND_BRAIN_MEMORY_ROOTS=project:alpha|/tmp/alpha\n", encoding="utf-8")
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(app_module, "Database", _FakeDatabase)
    monkeypatch.setattr(app_module, "SourceRepository", _FakeSourceRepository)

    client = TestClient(create_app())
    response = client.delete("/api/scopes", params={"scope": "project:alpha"})

    assert response.status_code == 200
    assert response.json()["scopes"] == []
    assert "project:alpha|/tmp/alpha" not in env_file.read_text(encoding="utf-8")


def test_onenote_sync_endpoint_exposes_device_code_status(monkeypatch):
    started_threads = []

    class _FakeThread:
        def __init__(self, target, args=(), kwargs=None, daemon=None):
            self.target = target
            self.args = args
            self.kwargs = kwargs or {}
            self.daemon = daemon

        def start(self):
            started_threads.append(self)

    def fake_sync_one_note(
        settings,
        since,
        *,
        on_device_code=None,
        auto_open_browser=None,
        on_progress=None,
    ):
        assert auto_open_browser is False
        assert since == "2025-01-01T00:00:00Z"
        if on_device_code is not None:
            on_device_code(
                {
                    "message": "Use the code below to sign in.",
                    "verification_uri": "https://login.microsoftonline.com/device",
                    "verification_uri_complete": "https://login.microsoftonline.com/device?code=ABC123",
                    "user_code": "ABC123",
                    "interval": 5,
                    "expires_in": 900,
                }
            )
        return 7

    monkeypatch.setattr(app_module, "Thread", _FakeThread)
    monkeypatch.setattr(app_module, "sync_one_note", fake_sync_one_note)

    client = TestClient(create_app())
    response = client.post("/api/onenote/sync", json={"since": "2025-01-01T00:00:00Z"})

    assert response.status_code == 200
    assert response.json() == {"accepted": True, "since": "2025-01-01T00:00:00Z"}
    assert len(started_threads) == 1

    started_threads[0].target(*started_threads[0].args, **started_threads[0].kwargs)

    status = client.get("/api/onenote/sync")
    assert status.status_code == 200
    payload = status.json()
    assert payload["state"] == "completed"
    assert payload["since"] == "2025-01-01T00:00:00Z"
    assert payload["pages_synced"] == 7
    assert payload["auth_message"] == "Use the code below to sign in."
    assert payload["user_code"] == "ABC123"
