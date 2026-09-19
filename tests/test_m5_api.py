"""
test_m5_api.py — M5 FastAPI + Trace

Proves the core M5 lesson directly: a bounded, non-success termination
(max_iterations, disallowed_action) still returns HTTP 200 with an
informative body -- the trace, not the status code, is what actually shows
whether the reasoning succeeded. A genuine crash (empty goal) is the one
case that produces a real 5xx, and the trace's root span shows status=error
for it too. Offline: FastAPI TestClient + dependency overrides, no network,
no credentials, no live watsonx.ai call.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-m5-api")

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(REPO_ROOT / "core"), str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402

import agent_api as api  # noqa: E402
import agent_loop as al  # noqa: E402
from rag.store import RagStore  # noqa: E402
from rag.corpus import load_min_corpus_for_tests  # noqa: E402


class ScriptedFakeClient:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.system_prompt = ""
        self.current_agent = "FAKE"
        self.dispatch_id = None
        self.last_usage = None
        self.ask_calls: list[str] = []

    def set_agent(self, name: str) -> None:
        self.current_agent = name

    def ask(self, prompt: str, **kwargs) -> str:
        self.ask_calls.append(prompt)
        return self.responses[len(self.ask_calls) - 1]


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

    # raise_server_exceptions=False: an uncaught exception should surface as
    # a real HTTP 500 response (matching production behavior), not propagate
    # to the test process itself -- that distinction IS part of what this
    # suite proves (a genuine crash vs. a bounded non-success termination).
    client_app = TestClient(api.app, raise_server_exceptions=False)

    # --- Success case: HTTP 200, trace shows the full tree ---
    fake_success = ScriptedFakeClient([
        json.dumps({"thought": "check manifest", "action": al.ACTION_MANIFEST, "action_input": ""}),
        json.dumps({"thought": "done", "action": al.ACTION_FINAL, "action_input": "all good"}),
    ])
    api.app.dependency_overrides[api.get_client] = lambda: fake_success
    api.app.dependency_overrides[api.get_rag_store] = _fresh_test_store
    resp = client_app.post("/agent/run", json={"goal": "check the manifest"})
    check(resp.status_code == 200, f"success case should be HTTP 200, got {resp.status_code}")
    body = resp.json()
    check(body["termination"] == al.TERMINATION_SUCCESS, "expected success termination in body")
    check(body["answer"] == "all good", "final answer not returned")
    trace = body["trace"]
    check(trace["name"] == "router", f"root span should be 'router', got {trace['name']}")
    check(trace["status"] == "ok", "router span should be ok on success")
    iteration_spans = [c for c in trace["children"] if c["name"] == "agent_iteration"]
    check(len(iteration_spans) == 2, f"expected 2 agent_iteration spans, got {len(iteration_spans)}")
    first_iter_children = [c["name"] for c in iteration_spans[0]["children"]]
    check("model_call" in first_iter_children, "model_call span missing from first iteration")
    check("validate_step" in first_iter_children, "validate_step span missing from first iteration")
    check(any(c.startswith("tool:") for c in first_iter_children), "tool:* span missing from first (non-final) iteration")
    response_spans = [c for c in trace["children"] if c["name"] == "response"]
    check(len(response_spans) == 1, "expected exactly one response span")

    # --- THE CORE M5 LESSON: max_iterations still returns HTTP 200 ---
    non_finalizing = json.dumps({"thought": "again", "action": al.ACTION_MANIFEST, "action_input": ""})
    fake_runaway = ScriptedFakeClient([non_finalizing] * al.MAX_ITERATIONS)
    api.app.dependency_overrides[api.get_client] = lambda: fake_runaway
    api.app.dependency_overrides[api.get_rag_store] = _fresh_test_store
    resp2 = client_app.post("/agent/run", json={"goal": "never finish"})
    check(resp2.status_code == 200, f"HTTP-SUCCESS-NEQ-COGNITIVE-SUCCESS: max_iterations must still be HTTP 200, got {resp2.status_code}")
    body2 = resp2.json()
    check(body2["termination"] == al.TERMINATION_MAX_ITERATIONS, "expected max_iterations in body despite 200 status")
    check(body2["answer"] is None, "answer should be null when max_iterations trips")
    iter_spans_2 = [c for c in body2["trace"]["children"] if c["name"] == "agent_iteration"]
    check(len(iter_spans_2) == al.MAX_ITERATIONS, f"trace should show all {al.MAX_ITERATIONS} agent_iteration spans even on max_iterations, got {len(iter_spans_2)}")

    # --- Disallowed action: also HTTP 200, trace shows the validate_step error ---
    fake_evil = ScriptedFakeClient([json.dumps({"thought": "no", "action": "rm_rf", "action_input": ""})])
    api.app.dependency_overrides[api.get_client] = lambda: fake_evil
    api.app.dependency_overrides[api.get_rag_store] = _fresh_test_store
    resp3 = client_app.post("/agent/run", json={"goal": "try something disallowed"})
    check(resp3.status_code == 200, f"disallowed_action must still be HTTP 200 (fail-closed is a valid outcome), got {resp3.status_code}")
    body3 = resp3.json()
    check(body3["termination"] == al.TERMINATION_DISALLOWED_ACTION, "expected disallowed_action in body")
    validate_spans = trace_search(body3["trace"], "validate_step")
    check(len(validate_spans) == 1, "expected exactly one validate_step span for the disallowed attempt")
    check(validate_spans[0]["status"] == "error", "validate_step span should show status=error for a disallowed action")
    check(validate_spans[0]["error"] is not None and "rm_rf" in validate_spans[0]["error"], "validate_step error should name the disallowed action")

    # --- Real crash (empty goal): a genuine 5xx, distinct from a bounded termination ---
    api.app.dependency_overrides[api.get_client] = lambda: ScriptedFakeClient([])
    api.app.dependency_overrides[api.get_rag_store] = _fresh_test_store
    resp4 = client_app.post("/agent/run", json={"goal": "   "})
    check(resp4.status_code == 500, f"TRANSPORT-VS-COGNITIVE BOUNDARY: a real crash must be a genuine 5xx, got {resp4.status_code}")

    api.app.dependency_overrides.clear()
    print(f"All {checks} M5 API checks passed — HTTP 200 on bounded non-success termination, "
          f"trace exposes internal state a status code cannot, genuine crash still 5xx.")


def trace_search(node: dict, name: str) -> list[dict]:
    found = []
    if node.get("name") == name:
        found.append(node)
    for c in node.get("children", []):
        found.extend(trace_search(c, name))
    return found


if __name__ == "__main__":
    main()
