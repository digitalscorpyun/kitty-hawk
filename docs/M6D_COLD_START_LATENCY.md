# M6d — Cold-start rebuild latency (local measurement)

**Date:** 2026-10-02
**Purpose:** M6.0 decision 5 provisionally chose rebuild-on-cold-start for RAG persistence and
required the latency to be measured and recorded before that choice is treated as final.
**Scope:** local workstation only. No AWS resource, no network call, no live watsonx.ai call.

## What was measured

A fresh Python process, five runs, each timing:

1. `import chromadb`
2. `load_controlled_corpus()`
3. `RagStore()` construction (ephemeral Chroma client)
4. `add_documents(...)` over the loaded corpus (chunk, embed, index)
5. One `retrieve("bounded agent loop")` call

**Environment:** Python 3.10.19, chromadb 1.5.9, Windows 11, warm disk cache.

**Corpus:** the synthetic fallback corpus, because the optional `KITTY_HAWK_VAULT_*`
environment variables were unset. That is 3 documents, 30,286 characters, 101 chunks. This is
what any clone without the author's local notes sees.

## Results (milliseconds)

| Run | import chromadb | corpus load | client init | index (101 chunks) | first query |
|---|---|---|---|---|---|
| 1 | 2662 | 0.6 | 387 | 136 | 12.2 |
| 2 | 3328 | 0.8 | 352 | 183 | 9.9 |
| 3 | 3531 | 0.9 | 316 | 126 | 10.3 |
| 4 | 3359 | 0.9 | 304 | 131 | 9.1 |
| 5 | 2658 | 0.4 | 328 | 144 | 10.2 |

- **Rebuild (client init + index):** about 440 to 530 ms.
- **`import chromadb`:** about 2.7 to 3.5 s. This is not rebuild work, but it is part of any
  cold start and is the largest single cost measured.
- Every run returned a grounded retrieval (`reason: ok`).

## Limitations (NOT_YET_MODELED)

- **Not a Lambda or API Gateway number.** Memory size, CPU allocation, package size and
  platform cold-start behavior are unmeasured and cannot be inferred from this machine.
- **Full app import not measured.** FastAPI, SQLAlchemy and the rest of `core/agent_api.py`
  were not included.
- **Real corpus not measured.** The Vault-backed corpus is larger than the synthetic one.
  Which corpus a deployed copy would index is an open decision.
- **Five runs, one machine, warm cache.** Fine for order of magnitude, not for a latency
  budget.

## Reading against the M6.0 gate

The rebuild step is sub-second for this corpus; the chromadb import dominates. Whether that is
"cheap/fast enough" is not decided by this document. Per M6.0 decision 5, if it is not, the
decision returns to the operator for an external-persistence call rather than adding
infrastructure silently.

The measurement script was a one-off and is intentionally not part of the repository.
