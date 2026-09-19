"""
corpus.py — M3 controlled corpus (no whole-system crawl)

Controlled sources, per gameplan:
  - agentic_ai_systems_engineering_syllabus.md (author's private Vault)
  - ibm_watsonx_cohesive_trajectory_gameplan.md (author's private Vault)
  - kitty-hawk README / core manifest (local, always present)

No Pinecone, no hunting. This public repository ships with no personal
filesystem paths: the two Vault sources are optional and resolved only
from environment variables (KITTY_HAWK_VAULT_SYLLABUS,
KITTY_HAWK_VAULT_GAMEPLAN) that are unset on any clone but the author's
own. If unset, absent, or unreadable, fallback to deterministic synthetic
stubs that preserve the exact retrieval contract -- this is the path
every other clone (including CI) actually exercises.
"""
from __future__ import annotations

import os
from pathlib import Path

VAULT_SYLLABUS = Path(os.environ["KITTY_HAWK_VAULT_SYLLABUS"]) if os.environ.get("KITTY_HAWK_VAULT_SYLLABUS") else None
VAULT_GAMEPLAN = Path(os.environ["KITTY_HAWK_VAULT_GAMEPLAN"]) if os.environ.get("KITTY_HAWK_VAULT_GAMEPLAN") else None
KITTY_README = Path(__file__).parent.parent / "README.md"

SYNTHETIC_SYLLABUS = """# Agentic AI Systems Engineering Syllabus
Kitty Hawk is the public capstone target per syllabus. Seven-week imagined syllabus covers FAISS/Chroma/Pinecone, LangGraph/CrewAI, retrieval and context construction, bounded agent loops, and observability. The syllabus provides lab shape for a watsonx → provider boundary → RAG → bounded tool/agent loop → observability/governance → deployment trajectory.
"""

SYNTHETIC_GAMEPLAN = """# IBM watsonx Cohesive Trajectory Gameplan
Spine = IBM watsonx / Granite. Capstone = Kitty Hawk. Kitty Hawk is your only system with fail-closed not_reviewed/not_authorized states. M1 provider boundary -> M2 evaluation -> M3 retrieval / context construction -> M4 bounded agent/tool loop -> M5 FastAPI + MLflow observability -> M6 production/deployment.
"""

def _read_or_fallback(path: Path | None, fallback: str, fallback_name: str) -> tuple[str, str, bool]:
    """Returns (text, source, is_real). path is None on any clone without the
    optional KITTY_HAWK_VAULT_* env vars set -- i.e. every clone but the author's."""
    if path is not None:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8"), str(path), True
        except Exception:
            pass
    return fallback, f"synthetic:{fallback_name}", False

def load_controlled_corpus() -> list[tuple[str, str]]:
    """Load controlled corpus as list of (text, source). Small by design (M3)."""
    docs: list[tuple[str, str]] = []
    text, src, _ = _read_or_fallback(VAULT_SYLLABUS, SYNTHETIC_SYLLABUS, "agentic_ai_systems_engineering_syllabus.md")
    docs.append((text, src))
    text2, src2, _ = _read_or_fallback(VAULT_GAMEPLAN, SYNTHETIC_GAMEPLAN, "ibm_watsonx_cohesive_trajectory_gameplan.md")
    docs.append((text2, src2))
    # Local Kitty Hawk doc — always present
    try:
        if KITTY_README.exists():
            docs.append((KITTY_README.read_text(encoding="utf-8"), str(KITTY_README)))
        else:
            docs.append((SYNTHETIC_SYLLABUS, "synthetic:kitty-hawk/README.md"))
    except Exception:
        docs.append((SYNTHETIC_SYLLABUS, "synthetic:kitty-hawk/README.md"))
    return docs

def load_min_corpus_for_tests() -> list[tuple[str, str]]:
    """Tiny deterministic corpus for offline M3 tests (no Vault dependency)."""
    return [
        (SYNTHETIC_SYLLABUS, "synthetic:agentic_ai_systems_engineering_syllabus.md"),
        (SYNTHETIC_GAMEPLAN, "synthetic:ibm_watsonx_cohesive_trajectory_gameplan.md"),
        ("Kitty Hawk — governed 4-seat agentic workflow for AI citation-integrity incidents. Fail-closed not_reviewed/not_authorized. Offline demo with FakeClient.", "synthetic:kitty-hawk/README.md"),
    ]
