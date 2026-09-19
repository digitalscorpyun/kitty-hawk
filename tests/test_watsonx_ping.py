"""
test_watsonx_ping.py — M1 deterministic test (ONE PING ONLY)

Proves: valid JSON, no hallucinated file, exactly one ask() call, no RAG/loop.
Offline: uses FakeClient, no credentials, no network.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-m1-ping")

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
CORE_DIR = THIS_DIR.parent / "core"
for p in (str(SCRIPTS_DIR), str(CORE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import watsonx_ping as wp  # noqa: E402


class FakeClient:
    def __init__(self, response: str):
        self.response = response
        self.system_prompt = ""
        self.current_agent = "FAKE"
        self.dispatch_id = None
        self.last_usage = None
        self.model_id = "OFFLINE-M1-FAKE"
        self.set_agent_calls: list[str] = []
        self.ask_calls: list[str] = []

    def set_agent(self, name: str) -> None:
        self.set_agent_calls.append(name)
        self.current_agent = name

    def ask(self, prompt: str, **kwargs) -> str:
        self.ask_calls.append(prompt)
        return self.response


def main() -> None:
    checks = 0

    def check(v: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not v:
            raise AssertionError(label)

    # --- Valid JSON, tool_used none, exactly one ping ---
    fake_ok = FakeClient(json.dumps({"goal": "x", "answer": "Granite boundary reachable", "tool_used": "none"}))
    result = wp.watsonx_ping("Prove the IBM watsonx Granite boundary is reachable", client=fake_ok)
    check(result["goal"] == "Prove the IBM watsonx Granite boundary is reachable", "goal echo failed")
    check(result["tool_used"] == "none", "tool_used should be none")
    check(result["answer"] == "Granite boundary reachable", "answer mismatch")
    check(len(fake_ok.ask_calls) == 1, f"ONE PING ONLY: expected 1 ask call, got {len(fake_ok.ask_calls)}")
    check(len(fake_ok.set_agent_calls) == 1, "expected 1 set_agent call")
    check(isinstance(fake_ok.ask_calls[0], str) and len(fake_ok.ask_calls[0]) > 0, "ask prompt not recorded")

    # Valid JSON parsing preserved
    check("raw" in result and json.loads(result["raw"]), "raw JSON not preserved/parseable")

    # --- Valid JSON, tool_used bounded manifest, exactly one ping, tool output grounded ---
    fake_tool = FakeClient(json.dumps({"goal": "x", "answer": "Used manifest", "tool_used": "read_kitty_hawk_manifest"}))
    result2 = wp.watsonx_ping("Check manifest", client=fake_tool)
    check(result2["tool_used"] == "read_kitty_hawk_manifest", "bounded tool not accepted")
    check("_tool_output" in result2 and "Kitty Hawk" in result2["_tool_output"], "bounded tool output not grounded")
    check(len(fake_tool.ask_calls) == 1, "ONE PING ONLY with tool claim still 1 call")

    # --- Invalid: hallucinated file while tool_used none should fail ---
    fake_hallucinate = FakeClient(json.dumps({"goal": "x", "answer": "I read read_kitty_hawk_manifest and found X", "tool_used": "none"}))
    try:
        wp.watsonx_ping("hallucination test", client=fake_hallucinate)
        check(False, "hallucinated answer with tool_used none should have raised")
    except ValueError as e:
        check("Hallucinated" in str(e) or "hallucination" in str(e).lower(), f"wrong error for hallucination: {e}")
        check(len(fake_hallucinate.ask_calls) == 1, "hallucination case still one ping before validation")

    # --- Invalid: malformed JSON should fail ---
    fake_bad = FakeClient("not json at all")
    try:
        wp.watsonx_ping("bad json", client=fake_bad)
        check(False, "malformed JSON should have raised")
    except ValueError as e:
        check("valid JSON" in str(e), f"wrong error for bad JSON: {e}")

    # --- Invalid: wrong tool_used should fail ---
    fake_wrong_tool = FakeClient(json.dumps({"goal": "x", "answer": "y", "tool_used": "evil_tool"}))
    try:
        wp.watsonx_ping("wrong tool", client=fake_wrong_tool)
        check(False, "invalid tool_used should have raised")
    except ValueError as e:
        check("tool_used" in str(e), f"wrong error for invalid tool: {e}")

    # --- Generate_response boundary is exactly one ask ---
    fake_gen = FakeClient("hello from granite")
    out = wp.generate_response("ping", client=fake_gen)
    check(out == "hello from granite", "generate_response passthrough failed")
    check(len(fake_gen.ask_calls) == 1, "generate_response must be exactly one ask")

    # --- No RAG, no loop: module does not import rag/bounded loop ---
    check(not hasattr(wp, "rag") and not hasattr(wp, "loop"), "M1 module must not expose rag/loop")

    print(f"All {checks} watsonx_ping M1 checks passed — ONE PING ONLY verified (valid JSON, no hallucination, exactly 1 ask).")


if __name__ == "__main__":
    main()
