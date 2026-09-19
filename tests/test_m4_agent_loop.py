"""
test_m4_agent_loop.py — M4 Bounded Agent/Tool Loop

Proves: the loop terminates via all four states (success, max_iterations,
timeout, disallowed_action), never executes a disallowed action, and the
two real tools (manifest read, RAG retrieval) actually ground their
observations rather than being stubbed. Offline: FakeClient + a real
ephemeral Chroma store over the deterministic test corpus. No network,
no credentials.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-m4-loop")

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(REPO_ROOT / "core"), str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import agent_loop as al  # noqa: E402
from rag.store import RagStore  # noqa: E402
from rag.corpus import load_min_corpus_for_tests  # noqa: E402


class ScriptedFakeClient:
    """Returns one scripted response per ask() call, in order. Raises if
    asked more times than scripted -- an unbounded loop calling this more
    than expected fails loudly instead of silently reusing the last response."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.system_prompt = ""
        self.current_agent = "FAKE"
        self.dispatch_id = None
        self.last_usage = None
        self.model_id = "OFFLINE-M4-FAKE"
        self.ask_calls: list[str] = []

    def set_agent(self, name: str) -> None:
        self.current_agent = name

    def ask(self, prompt: str, **kwargs) -> str:
        self.ask_calls.append(prompt)
        if len(self.ask_calls) > len(self.responses):
            raise AssertionError(
                f"FakeClient asked {len(self.ask_calls)} times but only "
                f"{len(self.responses)} responses were scripted -- loop is not bounded as expected"
            )
        return self.responses[len(self.ask_calls) - 1]


class SlowFakeClient:
    """Sleeps past the loop's timeout budget on its first call, to prove the
    timeout path actually trips rather than only being reachable in theory."""

    def __init__(self, sleep_seconds: float, final_response: str):
        self.sleep_seconds = sleep_seconds
        self.final_response = final_response
        self.system_prompt = ""
        self.current_agent = "FAKE"
        self.dispatch_id = None
        self.last_usage = None
        self.ask_calls: list[str] = []

    def set_agent(self, name: str) -> None:
        self.current_agent = name

    def ask(self, prompt: str, **kwargs) -> str:
        self.ask_calls.append(prompt)
        time.sleep(self.sleep_seconds)
        return self.final_response


def _fresh_test_store() -> RagStore:
    store = RagStore(persist_path=None)
    store.add_documents(load_min_corpus_for_tests())
    return store


def main() -> None:
    checks = 0

    def check(v: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not v:
            raise AssertionError(label)

    # --- Success: one tool call, then final_answer ---
    store = _fresh_test_store()
    fake_success = ScriptedFakeClient([
        json.dumps({
            "thought": "I should check the manifest first.",
            "action": al.ACTION_MANIFEST,
            "action_input": "",
        }),
        json.dumps({
            "thought": "That's enough to answer.",
            "action": al.ACTION_FINAL,
            "action_input": "Kitty Hawk core is present.",
        }),
    ])
    result = al.run_agent_loop("Check the manifest", client=fake_success, rag_store=store)
    check(result["termination"] == al.TERMINATION_SUCCESS, f"expected success, got {result['termination']}")
    check(result["answer"] == "Kitty Hawk core is present.", "final answer not captured")
    check(result["iterations_used"] == 2, f"expected 2 iterations, got {result['iterations_used']}")
    check(len(result["trajectory"]) == 2, "trajectory should have exactly 2 steps")
    check("Kitty Hawk" in result["trajectory"][0]["observation"], "manifest tool observation not grounded")

    # --- Max iterations: model never finalizes, loop must still stop ---
    store2 = _fresh_test_store()
    non_finalizing_step = json.dumps({
        "thought": "Let me check the manifest again.",
        "action": al.ACTION_MANIFEST,
        "action_input": "",
    })
    fake_runaway = ScriptedFakeClient([non_finalizing_step] * al.MAX_ITERATIONS)
    result2 = al.run_agent_loop("Never finish", client=fake_runaway, rag_store=store2)
    check(result2["termination"] == al.TERMINATION_MAX_ITERATIONS, f"expected max_iterations, got {result2['termination']}")
    check(result2["answer"] is None, "answer should be None when max_iterations trips")
    check(result2["iterations_used"] == al.MAX_ITERATIONS, f"expected {al.MAX_ITERATIONS} iterations used")
    check(len(fake_runaway.ask_calls) == al.MAX_ITERATIONS, "MAX_ITERATIONS BOUND: loop called ask() more times than the cap")

    # --- Disallowed action: fails closed, does not execute anything ---
    store3 = _fresh_test_store()
    fake_evil = ScriptedFakeClient([
        json.dumps({
            "thought": "I will use a tool that was never allowlisted.",
            "action": "delete_everything",
            "action_input": "",
        }),
        json.dumps({"thought": "unreachable", "action": al.ACTION_FINAL, "action_input": "should never get here"}),
    ])
    result3 = al.run_agent_loop("Try something disallowed", client=fake_evil, rag_store=store3)
    check(result3["termination"] == al.TERMINATION_DISALLOWED_ACTION, f"expected disallowed_action, got {result3['termination']}")
    check(result3["answer"] is None, "answer must be None on a disallowed-action termination")
    check(len(fake_evil.ask_calls) == 1, "FAIL-CLOSED: loop must stop on the first disallowed action, not continue")

    # --- Retrieval tool actually grounds context from the real corpus ---
    store4 = _fresh_test_store()
    fake_retrieve = ScriptedFakeClient([
        json.dumps({
            "thought": "Let me retrieve context about Kitty Hawk.",
            "action": al.ACTION_RETRIEVE,
            "action_input": "kitty hawk capstone",
        }),
        json.dumps({
            "thought": "Now I can answer.",
            "action": al.ACTION_FINAL,
            "action_input": "Kitty Hawk is the capstone.",
        }),
    ])
    result4 = al.run_agent_loop("What is the capstone?", client=fake_retrieve, rag_store=store4)
    check(result4["termination"] == al.TERMINATION_SUCCESS, "retrieval-then-finalize case should succeed")
    obs = result4["trajectory"][0]["observation"]
    check("RETRIEVAL FAILURE" not in obs, f"retrieval should have found grounded context, got: {obs!r}")
    check("kitty" in obs.lower() or "hawk" in obs.lower(), "retrieved context not actually grounded in the corpus")

    # --- Timeout: a slow model call must still produce a bounded, reported termination ---
    fake_slow = SlowFakeClient(sleep_seconds=0.2, final_response=json.dumps({
        "thought": "slow", "action": al.ACTION_FINAL, "action_input": "too late",
    }))
    store5 = _fresh_test_store()
    result5 = al.run_agent_loop("Time me out", client=fake_slow, rag_store=store5, timeout_seconds=0.05, max_iterations=5)
    check(result5["termination"] == al.TERMINATION_TIMEOUT, f"expected timeout, got {result5['termination']}")
    check(result5["answer"] is None, "answer must be None on a timeout termination")

    # --- Malformed JSON from the model is a real error, not a bounded state ---
    store6 = _fresh_test_store()
    fake_bad_json = ScriptedFakeClient(["not json at all"])
    try:
        al.run_agent_loop("Bad json", client=fake_bad_json, rag_store=store6)
        check(False, "malformed step JSON should have raised ValueError")
    except ValueError as e:
        check("valid JSON" in str(e), f"wrong error for malformed step JSON: {e}")

    # --- Empty goal rejected ---
    store7 = _fresh_test_store()
    try:
        al.run_agent_loop("   ", client=ScriptedFakeClient([]), rag_store=store7)
        check(False, "empty goal should have raised ValueError")
    except ValueError as e:
        check("goal" in str(e), f"wrong error for empty goal: {e}")

    # --- Allowlist is exactly the three documented actions, no more ---
    check(set(al.ALLOWED_ACTIONS) == {al.ACTION_MANIFEST, al.ACTION_RETRIEVE, al.ACTION_FINAL}, "ALLOWED_ACTIONS drifted from documented tools")

    print(f"All {checks} M4 agent-loop checks passed — bounded ReAct loop verified "
          f"(success, max_iterations, disallowed_action fail-closed, timeout, grounded retrieval).")


if __name__ == "__main__":
    main()
