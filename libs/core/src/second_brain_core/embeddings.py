from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class DeterministicEmbedder:
    """A tiny local embedding baseline that avoids external services in v1."""

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
