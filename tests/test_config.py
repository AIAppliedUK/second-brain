from pathlib import Path

from second_brain_core.config import Settings, _candidate_env_files


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
