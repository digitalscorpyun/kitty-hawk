"""rag — M3 Retrieval / Context Construction (Chip Ch 6)

Local Document -> Chunk -> Embed -> Index -> Retrieve -> Context.
Controlled corpus, no Pinecone/keys, offline deterministic.
"""
from .store import RagStore, Chunk, deterministic_embed, chunk_text  # noqa: F401
