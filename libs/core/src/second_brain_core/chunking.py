from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChunkingConfig:
    target_words: int = 220
    overlap_words: int = 40


def _split_words(text: str) -> list[str]:
    return [part for part in text.split() if part]


def chunk_document(
    text: str, heading_map: list[tuple[list[str], str]], config: ChunkingConfig
) -> list[tuple[list[str], str]]:
    chunks: list[tuple[list[str], str]] = []
    for heading_path, section_text in heading_map:
        words = _split_words(section_text)
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + config.target_words, len(words))
            chunk_words = words[start:end]
            chunks.append((heading_path, " ".join(chunk_words).strip()))
            if end == len(words):
                break
            start = max(end - config.overlap_words, start + 1)
    return chunks
