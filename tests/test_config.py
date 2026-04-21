from pathlib import Path

from second_brain_core.config import (
    Settings,
    _candidate_env_files,
    add_configured_memory_root,
    configured_memory_roots,
    remove_configured_memory_root,
    serialize_memory_roots,
)


def test_candidate_env_files_include_working_directory(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    nested = workspace / "nested" / "repo"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    candidates = _candidate_env_files()

    assert candidates[0] == nested / ".env"
    assert workspace / ".env" in candidates


def test_settings_include_mcp_transport_defaults(monkeypatch):
    monkeypatch.delenv("SECOND_BRAIN_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("SECOND_BRAIN_MCP_HOST", raising=False)
    monkeypatch.delenv("SECOND_BRAIN_MCP_PORT", raising=False)
    monkeypatch.delenv("SECOND_BRAIN_MCP_STREAMABLE_HTTP_PATH", raising=False)
    monkeypatch.delenv("SECOND_BRAIN_MCP_SSE_MOUNT_PATH", raising=False)

    settings = Settings()

    assert settings.mcp_transport == "stdio"
    assert settings.mcp_host == "127.0.0.1"
    assert settings.mcp_port == 8000
    assert settings.mcp_streamable_http_path == "/mcp"
    assert settings.mcp_sse_mount_path == "/"


def test_memory_root_serialization_round_trip(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = workspace / ".env"
    env_file.write_text("SECOND_BRAIN_MEMORY_ROOTS=project:one|/tmp/one\n", encoding="utf-8")
    monkeypatch.chdir(workspace)

    roots = configured_memory_roots()

    assert serialize_memory_roots(roots) == "project:one|/tmp/one"


def test_add_configured_memory_root_updates_env_file(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = workspace / ".env"
    env_file.write_text("SECOND_BRAIN_MEMORY_ROOTS=project:one|/tmp/one\n", encoding="utf-8")
    monkeypatch.chdir(workspace)

    roots = add_configured_memory_root("project:two", "/tmp/two")

    assert [root.scope for root in roots] == ["project:one", "project:two"]
    updated = env_file.read_text(encoding="utf-8")
    assert "project:two|/tmp/two" in updated


def test_remove_configured_memory_root_updates_env_file(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = workspace / ".env"
    env_file.write_text(
        "SECOND_BRAIN_MEMORY_ROOTS=project:one|/tmp/one;project:two|/tmp/two\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)

    roots = remove_configured_memory_root("project:one")

    assert [root.scope for root in roots] == ["project:two"]
    updated = env_file.read_text(encoding="utf-8")
    assert "project:one|/tmp/one" not in updated
