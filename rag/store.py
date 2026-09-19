"""
store.py — M3 true local Chroma collection (real chromadb)

Pipeline: Document -> Chunk -> Embed -> Index (local Chroma) -> Retrieve -> Context
Real chromadb collection, offline deterministic embedding, no network, no Pinecone.

Scaffold preserved at store_deterministic.py for teaching reference.
This file is the required M3 artifact: real chromadb, local/offline only.
"""
from __future__ import annotations

import re
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import chromadb
    from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    chromadb = None  # type: ignore

DIM = 64
CHUNK_SIZE = 400
OVERLAP = 50
SIM_THRESHOLD = 0.12
COLLECTION_NAME = "kitty_hawk_m3"

# --- Deterministic embedding (same as scaffold, offline) ---

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())

def deterministic_embed(text: str, dim: int = DIM) -> list[float]:
    vec = [0.0] * dim
    for tok in _tokenize(text):
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec

# Chroma embedding function wrapper (deterministic, offline)
if HAS_CHROMADB:
    class DeterministicHashEmbeddingFunction(EmbeddingFunction[Documents]):
        def __call__(self, input: Documents) -> Embeddings:
            return [deterministic_embed(t, DIM) for t in input]

        def name(self) -> str:
            return "deterministic_hash"

        # chromadb 1.5 compatibility
        def is_legacy(self) -> bool:
            return False

        def build_from_config(self, config: dict[str, Any]) -> "DeterministicHashEmbeddingFunction":
            return DeterministicHashEmbeddingFunction()

        def get_config(self) -> dict[str, Any]:
            return {}

        @staticmethod
        def validate_config(config: dict[str, Any]) -> None:
            return None
else:
    DeterministicHashEmbeddingFunction = None  # type: ignore

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
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

@dataclass(frozen=True)
class Chunk:
    text: str
    source: str
    chunk_id: str

class RagStore:
    """Real local Chroma-backed RAG store (Chroma-shaped API + true collection)."""

    def __init__(self, dim: int = DIM, persist_path: Path | None = None, collection_name: str = COLLECTION_NAME):
        if not HAS_CHROMADB:
            raise RuntimeError("chromadb not installed — install with pip install chromadb")
        self.dim = dim
        self._embed_fn = DeterministicHashEmbeddingFunction()
        if persist_path is not None:
            persist_path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(persist_path))
        else:
            # Ephemeral for tests / offline demo (no filesystem side-effects)
            self._client = chromadb.EphemeralClient()
        # Ensure fresh collection for this instance (tests need isolation)
        # If collection exists from prior instance with same name in PersistentClient, reuse it
        try:
            self._collection = self._client.get_collection(name=collection_name, embedding_function=self._embed_fn)  # type: ignore
        except Exception:
            self._collection = self._client.create_collection(
                name=collection_name,
                embedding_function=self._embed_fn,  # type: ignore
                metadata={"hnsw:space": "cosine"},
            )

    @property
    def count(self) -> int:
        return self._collection.count()

    def add_document(self, text: str, source: str) -> int:
        chunks = chunk_text(text)
        if not chunks:
            return 0
        ids: list[str] = []
        docs: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for i, c in enumerate(chunks):
            cid = f"{source}#chunk-{i:03d}"
            # Chroma id must be unique across collection; include hash of source+chunk
            uid = hashlib.sha256(cid.encode()).hexdigest()[:16] + f"-{i}"
            ids.append(uid)
            docs.append(c)
            metadatas.append({"source": source, "chunk_id": cid})
        # Chroma add
        self._collection.add(ids=ids, documents=docs, metadatas=metadatas)
        return len(chunks)

    def add_documents(self, docs: list[tuple[str, str]]) -> int:
        total = 0
        for text, source in docs:
            total += self.add_document(text, source)
        return total

    def retrieve(self, query: str, top_k: int = 3, threshold: float = SIM_THRESHOLD) -> dict[str, Any]:
        if self.count == 0:
            return {"query": query, "results": [], "retrieval_failure": True, "reason": "empty index", "top_raw_scores": []}
        # Chroma query
        res = self._collection.query(query_texts=[query], n_results=top_k, include=["documents", "metadatas", "distances"])
        # Chroma returns lists of lists (one per query)
        docs = (res.get("documents") or [[]])[0]  # type: ignore
        metas = (res.get("metadatas") or [[]])[0]  # type: ignore
        dists = (res.get("distances") or [[]])[0]  # type: ignore
        # Convert cosine distance to similarity: similarity = 1 - distance (for normalized vectors)
        scored: list[tuple[float, str, dict[str, Any], float]] = []  # similarity, text, meta, distance
        top_raw_scores: list[float] = []
        for doc, meta, dist in zip(docs, metas, dists):
            # Chroma cosine distance in [0,2]; for our normalized vectors it's in [0,2]
            sim = 1.0 - float(dist) if dist is not None else 0.0
            # Clamp -1..1
            sim = max(-1.0, min(1.0, sim))
            top_raw_scores.append(round(sim, 4))
            scored.append((sim, doc, meta, float(dist) if dist is not None else 0.0))
        # Filter by threshold
        filtered = [(s, d, m) for s, d, m, _ in scored if s >= threshold]
        results: list[dict[str, Any]] = []
        for sim, doc, meta in filtered:
            results.append({"text": doc, "source": meta.get("source", ""), "chunk_id": meta.get("chunk_id", ""), "score": round(float(sim), 4)})
        failure = len(results) == 0
        return {
            "query": query,
            "results": results,
            "retrieval_failure": failure,
            "reason": "below threshold" if failure else "ok",
            "top_raw_scores": top_raw_scores,
        }

    def to_context(self, retrieved: dict[str, Any], max_chars: int = 1200) -> str:
        if retrieved.get("retrieval_failure"):
            return f"[RETRIEVAL FAILURE] No grounded context for query: {retrieved.get('query')!r} (threshold {SIM_THRESHOLD})"
        parts: list[str] = []
        for r in retrieved.get("results", []):
            parts.append(f"[Source: {r['source']} | {r['chunk_id']} | score {r['score']}]\n{r['text']}")
        ctx = "\n\n---\n\n".join(parts)
        if len(ctx) > max_chars:
            ctx = ctx[:max_chars] + "\n[truncated]"
        return ctx

    def clear(self) -> None:
        """Delete all docs (test helper)."""
        try:
            # chroma 1.5: delete collection and recreate
            self._client.delete_collection(self._collection.name)
            self._collection = self._client.create_collection(
                name=self._collection.name,
                embedding_function=self._embed_fn,  # type: ignore
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            pass
