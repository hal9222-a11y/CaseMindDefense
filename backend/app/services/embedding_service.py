from __future__ import annotations

import hashlib
import math
import os
from functools import lru_cache
from typing import Iterable


DEFAULT_DIMENSIONS = int(os.getenv("CASEMIND_EMBEDDING_DIMENSIONS", "384"))
SEMANTIC_MODEL_NAME = os.getenv(
    "CASEMIND_EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)


def _fallback_embed_text(
    text: str,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> list[float]:
    vec = [0.0] * dimensions

    for token in (text or "").lower().split():
        h = hashlib.sha256(token.encode("utf-8")).digest()
        vec[h[0] % dimensions] += 1.0

    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


@lru_cache(maxsize=1)
def _load_sentence_transformer():
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(SEMANTIC_MODEL_NAME)
    except Exception:
        return None


def embedding_model_name() -> str:
    model = _load_sentence_transformer()
    if model is None:
        return f"fallback-hash-{DEFAULT_DIMENSIONS}d"
    return SEMANTIC_MODEL_NAME


def embedding_dimension(vec: Iterable[float] | None) -> int:
    if vec is None:
        return 0
    return len(list(vec))


def embed_text(text: str, dimensions: int = DEFAULT_DIMENSIONS) -> list[float]:
    cleaned = (text or "").strip()

    if not cleaned:
        return []

    model = _load_sentence_transformer()

    if model is None:
        return _fallback_embed_text(cleaned, dimensions=dimensions)

    try:
        vec = model.encode(cleaned, normalize_embeddings=True)
        return [float(x) for x in vec]
    except Exception:
        return _fallback_embed_text(cleaned, dimensions=dimensions)


def serialize_embedding(vec: list[float]) -> str:
    return ",".join(f"{x:.6f}" for x in vec)


def deserialize_embedding(raw: str) -> list[float]:
    if not raw:
        return []

    values: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            values.append(float(part))

    return values


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0

    if len(a) != len(b):
        return 0.0

    return sum(x * y for x, y in zip(a, b))
