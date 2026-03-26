from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError


class FileExtractionError(RuntimeError):
    pass


@dataclass(slots=True)
class ExtractedContent:
    text: str
    metadata: dict[str, str]
    content_hash: str


class FileExtractor:
    plain_text_suffixes = {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".go",
        ".gradle",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".json",
        ".jsx",
        ".kt",
        ".kts",
        ".md",
        ".mjs",
        ".py",
        ".rb",
        ".rs",
        ".scala",
        ".sh",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
    supported_suffixes = plain_text_suffixes | {".pdf", ".docx"}

    def extract(self, path: Path) -> ExtractedContent:
        suffix = path.suffix.lower()
        if suffix not in self.supported_suffixes:
            raise FileExtractionError(f"Unsupported file type: {path.suffix}")
        raw_bytes = path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()
        if suffix in self.plain_text_suffixes:
            text = path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            try:
                reader = PdfReader(str(path))
                text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
            except (PdfReadError, PdfStreamError, OSError, ValueError) as exc:
                raise FileExtractionError(f"Failed to extract PDF {path}: {exc}") from exc
        else:
            try:
                text = self._extract_docx(path)
            except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
                raise FileExtractionError(f"Failed to extract DOCX {path}: {exc}") from exc
        if not text.strip():
            raise FileExtractionError(f"No extractable text found in {path}")
        return ExtractedContent(
            text=text.strip(),
            metadata={"suffix": suffix, "size_bytes": str(path.stat().st_size)},
            content_hash=content_hash,
        )

    def _extract_docx(self, path: Path) -> str:
        with zipfile.ZipFile(path) as archive:
            document = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        fragments: list[str] = []
        for segment in document.replace("</w:p>", "\n").split("<"):
            if segment.startswith("w:t") and ">" in segment:
                fragments.append(segment.split(">", 1)[1])
        return "".join(fragments).replace("&amp;", "&").strip()
