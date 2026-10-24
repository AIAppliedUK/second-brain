from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .config import Settings

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class Embedder(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]: ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


class DeterministicEmbedder:
    """Hashed bag-of-words vectors. Not semantic: use only for tests and offline dev."""

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        buckets = [0.0] * self.dimension
        counts = Counter(token.lower() for token in TOKEN_PATTERN.findall(text))
        if not counts:
            return buckets
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            buckets[index] += sign * float(count)
        norm = math.sqrt(sum(value * value for value in buckets))
        if norm == 0:
            return buckets
        return [value / norm for value in buckets]

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class FastEmbedEmbedder:
    """Local ONNX sentence embeddings via fastembed; no network access after model download."""

    def __init__(
        self, model_name: str, dimension: int, batch_size: int = 32, threads: int | None = None
    ) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size
        # ONNX Runtime defaults to one thread per host core, ignoring container CPU limits.
        self._model = TextEmbedding(model_name=model_name, threads=threads)

    def embed(self, text: str) -> list[float]:
        # English bge models expect this instruction on queries (not passages);
        # fastembed's query_embed does not add it for them.
        if "bge-" in self.model_name and "-en" in self.model_name:
            text = f"Represent this sentence for searching relevant passages: {text}"
        vector = next(iter(self._model.query_embed(text)))
        return self._checked(vector.tolist())

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        return [
            self._checked(vector.tolist())
            for vector in self._model.passage_embed(list(texts), batch_size=self.batch_size)
        ]

    def _checked(self, vector: list[float]) -> list[float]:
        if len(vector) != self.dimension:
            raise ValueError(
                f"{self.model_name} produced {len(vector)}-d vectors but "
                f"SECOND_BRAIN_EMBEDDING_DIMENSION is {self.dimension}"
            )
        return vector


class FastEmbedReranker:
    """Local cross-encoder: scores (query, passage) pairs jointly, so it ranks far more
    precisely than comparing two independently computed embeddings."""

    def __init__(self, model_name: str, threads: int | None = None) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model_name = model_name
        self._model = TextCrossEncoder(model_name=model_name, threads=threads)

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        return [float(score) for score in self._model.rerank(query, list(passages))]


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "deterministic":
        return DeterministicEmbedder(settings.embedding_dimension)
    if settings.embedding_provider == "fastembed":
        return FastEmbedEmbedder(
            settings.embedding_model,
            settings.embedding_dimension,
            threads=settings.model_threads or None,
        )
    raise ValueError(f"Unknown SECOND_BRAIN_EMBEDDING_PROVIDER: {settings.embedding_provider}")


def build_reranker(settings: Settings) -> FastEmbedReranker | None:
    if not settings.reranker_model or settings.embedding_provider == "deterministic":
        return None
    return FastEmbedReranker(settings.reranker_model, threads=settings.model_threads or None)
