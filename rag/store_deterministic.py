"""
store.py — M3 deterministic local RAG (Chip Ch 6 context construction)

Pipeline: Document -> Chunk -> Embed -> Index (local, Chroma-shaped) -> Retrieve -> Context
No external embeddings, no network, deterministic and testable.

Embedding: deterministic hash-bucket bag-of-words -> 64-dim unit vector.
Index: in-memory list + numpy cosine (if available) else pure python.
Citation: source + chunk_id preserved for every retrieved chunk.
Failure case: low similarity below threshold -> retrieval failure marker.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import numpy as np  # type: ignore
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

DIM = 64
CHUNK_SIZE = 400
OVERLAP = 50
SIM_THRESHOLD = 0.12  # below this, retrieval is considered failure (M3 requirement)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    """Simple char-based chunking with overlap, preserves all content."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # try to break on paragraph/sentence boundary near end
        if end < len(text):
            for delim in ("\n\n", "\n", ". ", " "):
                idx = chunk.rfind(delim)
                if idx > chunk_size * 0.6:
                    chunk = chunk[: idx + len(delim)]
                    end = start + len(chunk)
                    break
        chunks.append(chunk.strip())
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if c]


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def deterministic_embed(text: str, dim: int = DIM) -> list[float]:
    """Deterministic bag-of-words hash embedding -> unit vector."""
    vec = [0.0] * dim
    for tok in _tokenize(text):
        # stable hash via sha256
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


def cosine_sim(a: list[float], b: list[float]) -> float:
    if HAS_NUMPY:
        import numpy as _np  # type: ignore
        va = _np.array(a)
        vb = _np.array(b)
        denom = _np.linalg.norm(va) * _np.linalg.norm(vb)
        if denom == 0:
            return 0.0
        return float(_np.dot(va, vb) / denom)
    # pure python
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    chunk_id: str


class RagStore:
    """Local index, Chroma-shaped API for M3 teaching."""

    def __init__(self, dim: int = DIM):
        self.dim = dim
        self.chunks: list[Chunk] = []
        self.embeddings: list[list[float]] = []

    @property
    def count(self) -> int:
        return len(self.chunks)

    def add_document(self, text: str, source: str) -> int:
        """Chunk + embed + index one document. Returns number of chunks added."""
        chunks = chunk_text(text)
        added = 0
        for i, c in enumerate(chunks):
            ch = Chunk(text=c, source=source, chunk_id=f"{source}#chunk-{i:03d}")
            emb = deterministic_embed(c, self.dim)
            self.chunks.append(ch)
            self.embeddings.append(emb)
            added += 1
        return added

    def add_documents(self, docs: list[tuple[str, str]]) -> int:
        """Docs as (text, source). Returns total chunks."""
        total = 0
        for text, source in docs:
            total += self.add_document(text, source)
        return total

    def retrieve(self, query: str, top_k: int = 3, threshold: float = SIM_THRESHOLD) -> dict[str, Any]:
        """Retrieve top_k chunks for query. Includes failure marker when below threshold."""
        if not self.chunks:
            return {"query": query, "results": [], "retrieval_failure": True, "reason": "empty index"}
        qemb = deterministic_embed(query, self.dim)
        scored: list[tuple[float, int]] = []
        for idx, emb in enumerate(self.embeddings):
            scored.append((cosine_sim(qemb, emb), idx))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:top_k]
        # Filter by threshold
        filtered = [(s, i) for s, i in top if s >= threshold]
        results = []
        for score, idx in filtered:
            ch = self.chunks[idx]
            results.append({"text": ch.text, "source": ch.source, "chunk_id": ch.chunk_id, "score": round(score, 4)})
        failure = len(results) == 0
        return {
            "query": query,
            "results": results,
            "retrieval_failure": failure,
            "reason": "below threshold" if failure else "ok",
            "top_raw_scores": [round(s, 4) for s, _ in top],
        }

    def to_context(self, retrieved: dict[str, Any], max_chars: int = 1200) -> str:
        """Build context string for downstream M4 loop from retrieved results."""
        if retrieved.get("retrieval_failure"):
            return f"[RETRIEVAL FAILURE] No grounded context for query: {retrieved.get('query')!r} (threshold {SIM_THRESHOLD})"
        parts = []
        for r in retrieved.get("results", []):
            parts.append(f"[Source: {r['source']} | {r['chunk_id']} | score {r['score']}]\n{r['text']}")
        ctx = "\n\n---\n\n".join(parts)
        if len(ctx) > max_chars:
            ctx = ctx[:max_chars] + "\n[truncated]"
        return ctx
