from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from second_brain_core import ChunkingConfig, chunk_document
from second_brain_core.config import MemoryRoot
from second_brain_core.embeddings import Embedder
from second_brain_models import AuditEvent, CanonicalDocument, ChunkUpsert, SourceUpsert

from .extractors import ExtractedContent, FileExtractionError, FileExtractor
from .mermaid import enrich_mermaid_blocks


def _parse_markdown_sections(text: str) -> list[tuple[list[str], str]]:
    text = enrich_mermaid_blocks(text)
    sections: list[tuple[list[str], str]] = []
    headings: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if buffer:
                sections.append((headings.copy(), "\n".join(buffer).strip()))
                buffer = []
            level = len(stripped) - len(stripped.lstrip("#"))
            heading_text = stripped[level:].strip()
            headings = headings[: max(level - 1, 0)]
            headings.append(heading_text)
        else:
            buffer.append(line)
    if buffer:
        sections.append((headings.copy(), "\n".join(buffer).strip()))
    return sections or [([], text)]


# A chunk is worth indexing only if it has at least one real word (2+ letters);
# this drops markdown rules, empty table rows and number-only spreadsheet fragments.
_SEARCHABLE_WORD = re.compile(r"[^\W\d_]{2,}")


def _has_searchable_words(text: str) -> bool:
    return _SEARCHABLE_WORD.search(text) is not None


def _default_sections(text: str) -> list[tuple[list[str], str]]:
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    return [([], block) for block in blocks] or [([], text)]


class LocalFileIngester:
    ignored_directory_names = {
        ".build",
        # Claude Code agent state (sprint logs, reviews, worktrees): churns constantly
        # and buries the project's own documents in search results.
        ".claude",
        ".git",
        ".venv",
        ".next",
        ".pnpm-store",
        "__pycache__",
        ".cache",
        ".gradle",
        ".idea",
        ".pytest_cache",
        ".ruff_cache",
        ".turbo",
        "build",
        "coverage",
        "node_modules",
        "out",
        ".mypy_cache",
    }
    ignored_path_markers = {
        ".cache",
        ".next",
        ".turbo",
        "build",
        "coverage",
        "target",
        "dist",
        "test-results",
        "playwright-report",
    }
    ignored_path_prefixes = {
        ("docker", "volume", "state"),
        ("volume", "state"),
    }

    def __init__(
        self,
        extractor: FileExtractor,
        embedder: Embedder,
        chunking_config: ChunkingConfig | None = None,
    ) -> None:
        self.extractor = extractor
        self.embedder = embedder
        self.chunking_config = chunking_config or ChunkingConfig()

    def discover_files(self, roots: list[MemoryRoot]) -> list[tuple[MemoryRoot, Path]]:
        files: list[tuple[MemoryRoot, Path]] = []
        for root in roots:
            if not root.path.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root.path):
                current_dir = Path(dirpath)
                if self._is_ignored_relative_path(root.path, current_dir):
                    dirnames[:] = []
                    continue
                dirnames[:] = [
                    dirname
                    for dirname in dirnames
                    if dirname not in self.ignored_directory_names
                    and not dirname.endswith(".egg-info")
                    and not self._is_ignored_relative_path(root.path, current_dir / dirname)
                ]
                for filename in filenames:
                    # "~$Name.docx" are Office owner/lock files, never real documents.
                    if filename.startswith("~$"):
                        continue
                    path = current_dir / filename
                    if (
                        path.suffix.lower() in self.extractor.supported_suffixes
                        and not self._is_ignored_relative_path(root.path, path)
                        and not self._is_empty(path)
                    ):
                        files.append((root, path))
        return sorted(files, key=lambda item: str(item[1]))

    @staticmethod
    def _is_empty(path: Path) -> bool:
        try:
            return path.stat().st_size == 0
        except OSError:
            return True

    def _is_ignored_relative_path(self, root_path: Path, path: Path) -> bool:
        try:
            parts = path.resolve().relative_to(root_path.resolve()).parts
        except ValueError:
            return False
        if any(marker in parts for marker in self.ignored_path_markers):
            return True
        return any(parts[: len(prefix)] == prefix for prefix in self.ignored_path_prefixes)

    def extract_path(self, path: Path) -> ExtractedContent:
        return self.extractor.extract(path)

    def ingest_path(
        self,
        path: Path,
        memory_scope: str,
        root_path: Path | None = None,
        extracted: ExtractedContent | None = None,
    ) -> tuple[CanonicalDocument | None, AuditEvent]:
        try:
            extracted = extracted or self.extractor.extract(path)
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            sections = (
                _parse_markdown_sections(extracted.text)
                if path.suffix.lower() == ".md"
                else _default_sections(extracted.text)
            )
            chunk_tuples = [
                (heading_path, chunk_text)
                for heading_path, chunk_text in chunk_document(
                    extracted.text, sections, self.chunking_config
                )
                if _has_searchable_words(chunk_text)
            ]
            if not chunk_tuples:
                raise FileExtractionError(f"No searchable text found in {path}")
            embeddings = self.embedder.embed_many([chunk_text for _, chunk_text in chunk_tuples])
            container_parts = (
                list(path.resolve().relative_to(root_path.resolve()).parts[:-1])
                if root_path is not None and path.resolve().is_relative_to(root_path.resolve())
                else list(path.resolve().relative_to(path.anchor).parts[:-1])
            )
            source = SourceUpsert(
                memory_scope=memory_scope,
                source_type="local_file",
                external_id=str(path.resolve()),
                title=path.name,
                uri=path.resolve().as_uri(),
                container_lineage=container_parts,
                created_at=mtime,
                updated_at=mtime,
                content_hash=extracted.content_hash,
                metadata={
                    "memory_scope": memory_scope,
                    "path": str(path.resolve()),
                    "suffix": path.suffix.lower(),
                    "modified_at": mtime.isoformat(),
                    **extracted.metadata,
                },
                raw_text=extracted.text,
                canonical_text=extracted.text,
            )
            chunks = [
                ChunkUpsert(
                    source_id=source.id,
                    memory_scope=memory_scope,
                    chunk_index=index,
                    heading_path=heading_path,
                    chunk_text=chunk_text,
                    token_count=len(chunk_text.split()),
                    metadata={"path": str(path.resolve()), "memory_scope": memory_scope},
                    embedding=embedding,
                )
                for index, ((heading_path, chunk_text), embedding) in enumerate(
                    zip(chunk_tuples, embeddings, strict=True)
                )
            ]
            return CanonicalDocument(source=source, chunks=chunks), AuditEvent(
                source_id=source.id,
                event_type="file_ingest",
                status="success",
                message=f"Ingested {path}",
                metadata={
                    "path": str(path.resolve()),
                    "chunk_count": len(chunks),
                    "memory_scope": memory_scope,
                },
            )
        except FileExtractionError as exc:
            return None, AuditEvent(
                event_type="file_ingest",
                status="failed",
                message=str(exc),
                metadata={"path": str(path.resolve()), "memory_scope": memory_scope},
            )
