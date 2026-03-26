from pathlib import Path

from second_brain_core.config import MemoryRoot
from second_brain_core.embeddings import DeterministicEmbedder
from second_brain_file_ingest import FileExtractionError, FileExtractor, LocalFileIngester


def test_local_file_ingester_builds_canonical_document_for_markdown(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text(
        "# Heading\n\nThis is a note about retrieval.\n\n## Details\n\nCitations matter."
    )
    ingester = LocalFileIngester(FileExtractor(), DeterministicEmbedder(32))
    document, event = ingester.ingest_path(
        path, memory_scope="project:test", root_path=tmp_path
    )
    assert document is not None
    assert document.source.memory_scope == "project:test"
    assert document.source.source_type == "local_file"
    assert len(document.chunks) >= 1
    assert document.chunks[0].memory_scope == "project:test"
    assert document.chunks[0].heading_path == ["Heading"]
    assert event.status == "success"


def test_local_file_ingester_logs_failures_without_document(tmp_path: Path):
    path = tmp_path / "notes.bin"
    path.write_bytes(b"\x00\x01")
    ingester = LocalFileIngester(FileExtractor(), DeterministicEmbedder(32))
    document, event = ingester.ingest_path(path, memory_scope="general", root_path=tmp_path)
    assert document is None
    assert event.status == "failed"


def test_discover_files_returns_scoped_roots(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    ingester = LocalFileIngester(FileExtractor(), DeterministicEmbedder(32))
    discovered = ingester.discover_files([MemoryRoot(scope="project:test", path=tmp_path)])
    assert discovered == [(MemoryRoot(scope="project:test", path=tmp_path), path)]


def test_discover_files_skips_virtualenv_and_cache_dirs(tmp_path: Path):
    kept = tmp_path / "docs" / "guide.md"
    skipped = tmp_path / ".venv" / "notes.md"
    kept.parent.mkdir(parents=True)
    skipped.parent.mkdir(parents=True)
    kept.write_text("keep me")
    skipped.write_text("skip me")
    ingester = LocalFileIngester(FileExtractor(), DeterministicEmbedder(32))
    discovered = ingester.discover_files([MemoryRoot(scope="project:test", path=tmp_path)])
    assert discovered == [(MemoryRoot(scope="project:test", path=tmp_path), kept)]


def test_discover_files_skips_generated_dirs_and_volume_state(tmp_path: Path):
    kept_result = tmp_path / ".claude" / "sprint-state" / "results" / "summary.md"
    skipped_volume = tmp_path / "docker" / "volume" / "state" / "ses" / "message.txt"
    skipped_target = tmp_path / "backend" / "target" / "surefire-reports" / "TEST-report.xml"
    skipped_dist = tmp_path / "ui" / "dist" / "assets" / "app.js"
    skipped_review = tmp_path / ".claude" / "sprint-state" / "reviews" / "note.md"
    skipped_playwright = tmp_path / "ui" / "playwright-report" / "index.html"
    skipped_results = tmp_path / "ui" / "test-results" / "results.json"

    for path in [
        kept_result,
        skipped_volume,
        skipped_target,
        skipped_dist,
        skipped_review,
        skipped_playwright,
        skipped_results,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")

    ingester = LocalFileIngester(FileExtractor(), DeterministicEmbedder(32))
    discovered = ingester.discover_files([MemoryRoot(scope="project:test", path=tmp_path)])

    assert discovered == [(MemoryRoot(scope="project:test", path=tmp_path), kept_result)]


def test_local_file_ingester_supports_code_files_as_plain_text(tmp_path: Path):
    path = tmp_path / "Example.kt"
    path.write_text("class Example {\n    fun greet() = \"hello\"\n}\n")
    ingester = LocalFileIngester(FileExtractor(), DeterministicEmbedder(32))
    document, event = ingester.ingest_path(
        path, memory_scope="project:kmp", root_path=tmp_path
    )
    assert document is not None
    assert document.source.memory_scope == "project:kmp"
    assert "greet" in document.chunks[0].chunk_text
    assert event.status == "success"


def test_file_extractor_raises_file_extraction_error_for_invalid_pdf(tmp_path: Path):
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"AAAAA this is not a real pdf")
    extractor = FileExtractor()
    try:
        extractor.extract(path)
    except FileExtractionError as exc:
        assert "Failed to extract PDF" in str(exc)
    else:
        raise AssertionError("Expected invalid PDF extraction to fail")
