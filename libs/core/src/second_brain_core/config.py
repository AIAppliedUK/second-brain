from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, load_dotenv


def _candidate_env_files() -> list[Path]:
    candidates: list[Path] = []
    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        candidates.append(parent / ".env")
    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        candidate = parent / ".env"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def load_local_env() -> Path | None:
    for candidate in _candidate_env_files():
        if candidate.exists():
            load_dotenv(candidate, override=False)
            return candidate
    return None


load_local_env()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _default_onenote_token_cache_path() -> Path:
    return Path.home() / ".second-brain" / "onenote-token.json"


def _parse_bool(value: str, default: bool = False) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(slots=True)
class MemoryRoot:
    scope: str
    path: Path


def _parse_memory_roots(value: str) -> list[MemoryRoot]:
    roots: list[MemoryRoot] = []
    for item in [part.strip() for part in value.split(";") if part.strip()]:
        if "|" not in item:
            continue
        scope, raw_path = item.split("|", 1)
        roots.append(MemoryRoot(scope=scope.strip(), path=Path(raw_path.strip()).expanduser()))
    return roots


def local_env_path() -> Path | None:
    for candidate in _candidate_env_files():
        if candidate.exists():
            return candidate
    return None


def read_local_env() -> dict[str, str]:
    env_path = local_env_path()
    if env_path is None:
        return {}
    return {
        key: value
        for key, value in dotenv_values(env_path).items()
        if key is not None and value is not None
    }


def serialize_memory_roots(roots: list[MemoryRoot]) -> str:
    return ";".join(f"{root.scope}|{root.path.expanduser()}" for root in roots)


def write_local_env_value(key: str, value: str) -> Path:
    env_path = local_env_path()
    if env_path is None:
        env_path = Path.cwd() / ".env"
        lines: list[str] = []
    else:
        lines = env_path.read_text(encoding="utf-8").splitlines()

    new_lines: list[str] = []
    replaced = False
    prefix = f"{key}="
    for line in lines:
        if line.startswith(prefix):
            if not replaced:
                new_lines.append(f"{key}={value}")
                replaced = True
            continue
        new_lines.append(line)
    if not replaced:
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    os.environ[key] = value
    return env_path


def configured_memory_roots() -> list[MemoryRoot]:
    env = read_local_env()
    return _parse_memory_roots(env.get("SECOND_BRAIN_MEMORY_ROOTS", ""))


def add_configured_memory_root(scope: str, path: str) -> list[MemoryRoot]:
    roots = configured_memory_roots()
    normalized_scope = scope.strip()
    normalized_path = Path(path.strip()).expanduser()
    updated = False
    for root in roots:
        if root.scope == normalized_scope:
            root.path = normalized_path
            updated = True
            break
    if not updated:
        roots.append(MemoryRoot(scope=normalized_scope, path=normalized_path))
    write_local_env_value("SECOND_BRAIN_MEMORY_ROOTS", serialize_memory_roots(roots))
    return roots


def remove_configured_memory_root(scope: str) -> list[MemoryRoot]:
    roots = configured_memory_roots()
    normalized_scope = scope.strip()
    updated_roots = [root for root in roots if root.scope != normalized_scope]
    write_local_env_value("SECOND_BRAIN_MEMORY_ROOTS", serialize_memory_roots(updated_roots))
    return updated_roots


@dataclass(slots=True)
class Settings:
    db_dsn: str = field(
        default_factory=lambda: os.getenv(
            "SECOND_BRAIN_DB_DSN",
            "postgresql://second_brain:second_brain@127.0.0.1:5432/second_brain",
        )
    )
    embedding_dimension: int = field(
        default_factory=lambda: int(os.getenv("SECOND_BRAIN_EMBEDDING_DIMENSION", "256"))
    )
    file_roots: list[Path] = field(
        default_factory=lambda: [
            Path(item) for item in _split_csv(os.getenv("SECOND_BRAIN_FILE_ROOTS", "./sample-data"))
        ]
    )
    default_memory_scope: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_DEFAULT_MEMORY_SCOPE", "general")
    )
    memory_roots: list[MemoryRoot] = field(
        default_factory=lambda: _parse_memory_roots(os.getenv("SECOND_BRAIN_MEMORY_ROOTS", ""))
    )
    mcp_server_name: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_MCP_SERVER_NAME", "second-brain")
    )
    mcp_transport: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_MCP_TRANSPORT", "stdio")
    )
    mcp_host: str = field(default_factory=lambda: os.getenv("SECOND_BRAIN_MCP_HOST", "127.0.0.1"))
    mcp_port: int = field(default_factory=lambda: int(os.getenv("SECOND_BRAIN_MCP_PORT", "8000")))
    mcp_streamable_http_path: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_MCP_STREAMABLE_HTTP_PATH", "/mcp")
    )
    mcp_sse_mount_path: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_MCP_SSE_MOUNT_PATH", "/")
    )
    onenote_tenant_id: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_ONENOTE_TENANT_ID", "common")
    )
    onenote_client_id: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_ONENOTE_CLIENT_ID", "")
    )
    onenote_scopes: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("SECOND_BRAIN_ONENOTE_SCOPES", "offline_access,Notes.Read.All,User.Read")
        )
    )
    onenote_token_cache_path: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "SECOND_BRAIN_ONENOTE_TOKEN_CACHE_PATH",
                str(_default_onenote_token_cache_path()),
            )
        ).expanduser()
    )
    onenote_auto_open_browser: bool = field(
        default_factory=lambda: _parse_bool(
            os.getenv("SECOND_BRAIN_ONENOTE_AUTO_OPEN_BROWSER", "true"),
            default=True,
        )
    )
    onenote_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("SECOND_BRAIN_ONENOTE_TIMEOUT_SECONDS", "30"))
    )
    onenote_request_delay_seconds: float = field(
        default_factory=lambda: float(os.getenv("SECOND_BRAIN_ONENOTE_REQUEST_DELAY_SECONDS", "0.5"))
    )
    onenote_user_agent: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_ONENOTE_USER_AGENT", "second-brain/0.1.0")
    )
    onenote_memory_scope: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_ONENOTE_MEMORY_SCOPE", "general")
    )

    def resolved_memory_roots(self) -> list[MemoryRoot]:
        if self.memory_roots:
            return self.memory_roots
        return [MemoryRoot(scope=self.default_memory_scope, path=path) for path in self.file_roots]
