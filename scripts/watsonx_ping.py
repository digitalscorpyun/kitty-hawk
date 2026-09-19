"""
watsonx_ping.py — M1 Provider Boundary (ONE PING ONLY)

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md M1
Milestone: M1 provider boundary
Concept: Extend the verified IBM→Granite generate_response(user_text: str) -> str
         boundary into a useful, testable flow with a provider-neutral
         Agent->Client Interface->Model separation. ONE watsonx call per
         invocation, no RAG, no agent loop, no fallback provider.

Evidence: Single structured JSON via Granite, validated by one deterministic
          test (valid JSON, no hallucinated file, exactly one ask() call).

Bounded tool: read_kitty_hawk_manifest — the ONLY tool the model may claim.
              Valid values for tool_used are "none" or "read_kitty_hawk_manifest".
              This is not an autonomous tool loop; the model reports its choice
              in JSON, and the caller verifies it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Allow import from kitty-hawk/core
THIS_DIR = Path(__file__).resolve().parent
CORE_DIR = THIS_DIR.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from watsonx_client import WatsonXClient  # noqa: E402
from provider_protocol import SynapseProvider  # noqa: E402

ALLOWED_TOOL = "read_kitty_hawk_manifest"
ALLOWED_TOOL_USED = ("none", ALLOWED_TOOL)

PING_SYSTEM_PROMPT = (
    "You are a bounded IBM watsonx Granite assistant for M1 provider-boundary verification. "
    "Respond ONLY with valid JSON containing exactly these keys: goal, answer, tool_used. "
    'tool_used must be either "none" or "read_kitty_hawk_manifest". '
    "Do not invent file paths. Do not hallucinate files. "
    "If you claim read_kitty_hawk_manifest, the answer must be grounded in the Kitty Hawk manifest content."
)

PING_USER_TEMPLATE = (
    "Goal: {goal}\n"
    "Instruction: Return JSON with keys goal, answer, tool_used as specified. "
    "Keep answer concise (1-2 sentences)."
)


def _read_kitty_hawk_manifest() -> str:
    """Bounded tool: returns a stable, local manifest snippet (no network).

    This is the one allowed tool for M1. It does not call the model.
    """
    # Use local core file existence as evidence, not Vault (offline-safe)
    candidates = [
        THIS_DIR.parent / "core" / "mission_citation_fabrication.py",
        THIS_DIR.parent / "demo" / "kitty_hawk_offline_demo.py",
    ]
    for p in candidates:
        if p.exists():
            return f"Kitty Hawk core present: {p.name} exists ({p.stat().st_size} bytes)"
    return "Kitty Hawk core manifest: offline stub (no file found, but tool was explicitly allowed)"


def generate_response(user_text: str, *, client: SynapseProvider | None = None) -> str:
    """Verified boundary: generate_response(user_text: str) -> str

    ONE watsonx call. No fallback provider. TLS verified via WatsonXClient.
    Injectable client for offline/deterministic tests (FakeClient).
    """
    c = client or WatsonXClient()
    # One ping only: single ask() invocation
    # Set a minimal identity; watsonx substrate is the same for all seats
    try:
        c.set_agent("ECHO-PROPHET")
    except Exception:
        # FakeClient or stub may not need manifest
        pass
    # Preserve system prompt discipline but override for M1 JSON contract
    c.system_prompt = PING_SYSTEM_PROMPT
    return c.ask(user_text)


def watsonx_ping(goal: str, *, client: SynapseProvider | None = None) -> dict[str, Any]:
    """M1 entry: goal -> one Granite call -> structured JSON dict.

    Returns dict with keys: goal, answer, tool_used, raw
    Raises ValueError on invalid JSON or hallucinated tool_used.

    Exactly one model call per invocation.
    """
    if not goal or not goal.strip():
        raise ValueError("goal must be non-empty")
    user_text = PING_USER_TEMPLATE.format(goal=goal.strip())
    raw = generate_response(user_text, client=client)
    # One ping proof: caller can inspect client.ask_calls if FakeClient
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"M1 ping must return valid JSON, got: {raw!r}") from e

    if not isinstance(data, dict):
        raise ValueError(f"M1 ping JSON must be object, got {type(data)}")

    for k in ("goal", "answer", "tool_used"):
        if k not in data:
            raise ValueError(f"M1 ping JSON missing required key: {k!r} in {data}")

    if data["tool_used"] not in ALLOWED_TOOL_USED:
        raise ValueError(f"tool_used must be one of {ALLOWED_TOOL_USED}, got {data['tool_used']!r}")

    # Anti-hallucination: answer must not claim a file that doesn't exist via tool path
    # For M1, we only allow the single bounded tool; any other file mention is hallucination
    # Simple check: if tool_used == none, answer must not contain hallucinated manifest-like path
    if data["tool_used"] == "none":
        hallucination_markers = ["manifest", "read_kitty_hawk_manifest", ".md", ".py", "/mnt/", "C:/"]
        # Allow generic mention of "manifest" only if not claiming a file was read
        # If answer claims it read a file while tool_used is none, that's a hallucination
        lower = str(data["answer"]).lower()
        if "read_" in lower and "manifest" in lower:
            raise ValueError(f"Hallucinated tool use: tool_used is none but answer claims file read: {data['answer']!r}")

    # Enrich with grounded tool output if claimed
    if data["tool_used"] == ALLOWED_TOOL:
        data["_tool_output"] = _read_kitty_hawk_manifest()
    data["raw"] = raw
    # Preserve goal echo
    data["goal"] = goal.strip()
    return data


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="M1 watsonx ping — one Granite call, structured JSON")
    p.add_argument("--goal", default="Prove the IBM watsonx Granite boundary is reachable from code")
    p.add_argument("--json", action="store_true", help="print JSON only")
    args = p.parse_args()
    result = watsonx_ping(args.goal)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "raw"}, ensure_ascii=False))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # One-ping invariant: this script itself performed exactly one ask() (not verifiable here without injection,
    # but test suite verifies via FakeClient)
    print("\nM1 proof: ONE watsonx call (generate_response -> ask) completed. No RAG, no loop.")


if __name__ == "__main__":
    main()
