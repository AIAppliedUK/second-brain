from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


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
    onenote_tenant_id: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_ONENOTE_TENANT_ID", "common")
    )
    onenote_client_id: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_ONENOTE_CLIENT_ID", "")
    )
    onenote_scopes: list[str] = field(
        default_factory=lambda: _split_csv(
            os.getenv("SECOND_BRAIN_ONENOTE_SCOPES", "offline_access,Notes.Read,User.Read")
        )
    )
    onenote_redirect_uri: str = field(
        default_factory=lambda: os.getenv("SECOND_BRAIN_ONENOTE_REDIRECT_URI", "http://localhost")
    )
    onenote_timeout_seconds: int = field(
        default_factory=lambda: int(os.getenv("SECOND_BRAIN_ONENOTE_TIMEOUT_SECONDS", "30"))
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
