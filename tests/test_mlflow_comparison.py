"""
test_mlflow_comparison.py — M5 comparison: trace.py (homegrown) vs. real MLflow

Proves the comparison directly, not just asserts it: the identical
agent_loop.run_agent_loop() instrumentation call-sites produce a
structurally equivalent execution tree whether backed by trace.Tracer
(in-memory, JSON, gone once the response is sent) or real MLflow
(persisted to a database backend, queryable after the fact by trace_id).

Uses a real local MLflow sqlite backend in a temp directory -- this is a
genuine MLflow write+read round trip, not a mock of MLflow's API. No
network, no watsonx.ai credentials; FakeClient throughout, matching every
other offline suite in this repository.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-mlflow-comparison")

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(REPO_ROOT / "core"), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import mlflow  # noqa: E402

import agent_loop as al  # noqa: E402
import mlflow_comparison as mc  # noqa: E402
from trace import Tracer  # noqa: E402
from rag.store import RagStore  # noqa: E402
from rag.corpus import load_min_corpus_for_tests  # noqa: E402

TMP_DB = Path(tempfile.mkdtemp()) / "mlflow_test.db"
TRACKING_URI = f"sqlite:///{TMP_DB.as_posix()}"
EXPERIMENT = "kitty-hawk-m5-comparison-test"


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


def _span_names(node: dict) -> list[str]:
    names = [node["name"]]
    for c in node.get("children", []):
        names.extend(_span_names(c))
    return names


def main() -> None:
    checks = 0

    def check(v: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not v:
            raise AssertionError(label)

    success_script = [
        json.dumps({"thought": "check manifest", "action": al.ACTION_MANIFEST, "action_input": ""}),
        json.dumps({"thought": "done", "action": al.ACTION_FINAL, "action_input": "all good"}),
    ]

    # --- Real MLflow write+read round trip ---
    fake1 = ScriptedFakeClient(list(success_script))
    result = mc.run_with_mlflow_trace(
        "check the manifest", client=fake1, rag_store=_fresh_test_store(),
        tracking_uri=TRACKING_URI, experiment_name=EXPERIMENT,
    )
    check(result["termination"] == al.TERMINATION_SUCCESS, f"expected success, got {result['termination']}")
    check(result["answer"] == "all good", "final answer not preserved through the MLflow-backed run")
    trace_id = result["mlflow_trace_id"]
    check(bool(trace_id), "run_with_mlflow_trace did not return a trace_id")

    mlflow.set_tracking_uri(TRACKING_URI)
    persisted = mlflow.get_trace(trace_id)
    check(persisted is not None, "PERSISTENCE: mlflow.get_trace() found nothing for a trace_id this run just returned")
    span_names = sorted(s.name for s in persisted.data.spans)
    expected = sorted([
        "agent_run", "agent_iteration", "agent_iteration",
        "model_call", "model_call", "validate_step", "validate_step",
        f"tool:{al.ACTION_MANIFEST}",
    ])
    check(span_names == expected, f"unexpected span set in persisted trace: {span_names}")

    root_span = next(s for s in persisted.data.spans if s.name == "agent_run")
    check(root_span.parent_id is None, "agent_run should be the trace's root span")
    check(root_span.outputs == {"termination": al.TERMINATION_SUCCESS, "answer": "all good"}, "root span outputs should carry the run's own termination/answer")

    tool_span = next(s for s in persisted.data.spans if s.name.startswith("tool:"))
    check(tool_span.outputs is not None and "observation_chars" in tool_span.outputs, "tool span should carry an output")

    # --- Structural equivalence: same instrumentation, same tree shape, different backend ---
    # NOTE (a real finding, not a test-writing convenience): trace.Tracer
    # enforces exactly one root span per instance. Calling run_agent_loop
    # with a bare, unwrapped Tracer() raises RuntimeError on the *second*
    # top-level agent_iteration span, because the first iteration already
    # claimed the root and popped off the stack. agent_api.py never hits
    # this because it always wraps the call in an outer "router" span
    # first -- the same constraint mlflow.start_span() has (see
    # run_with_mlflow_trace's own "agent_run" wrapper above, added for
    # exactly this reason). A fair comparison wraps both sides the same way.
    fake2 = ScriptedFakeClient(list(success_script))
    tracer = Tracer()
    with tracer.span("agent_run"):
        home_result = al.run_agent_loop("check the manifest", client=fake2, rag_store=_fresh_test_store(), tracer=tracer)
    check(home_result["termination"] == result["termination"], "homegrown and MLflow-backed runs should terminate the same way given the same script")
    home_tree = tracer.to_dict()
    home_names = sorted(_span_names(home_tree))
    check(home_names == span_names, f"STRUCTURAL EQUIVALENCE: homegrown tree {home_names} != MLflow tree {span_names}")

    # --- max_iterations: trace shows all iterations, root records the bounded termination ---
    non_finalizing = json.dumps({"thought": "again", "action": al.ACTION_MANIFEST, "action_input": ""})
    fake_runaway = ScriptedFakeClient([non_finalizing] * al.MAX_ITERATIONS)
    result2 = mc.run_with_mlflow_trace(
        "never finish", client=fake_runaway, rag_store=_fresh_test_store(),
        tracking_uri=TRACKING_URI, experiment_name=EXPERIMENT,
    )
    check(result2["termination"] == al.TERMINATION_MAX_ITERATIONS, "expected max_iterations")
    persisted2 = mlflow.get_trace(result2["mlflow_trace_id"])
    iter_spans2 = [s for s in persisted2.data.spans if s.name == "agent_iteration"]
    check(len(iter_spans2) == al.MAX_ITERATIONS, f"expected {al.MAX_ITERATIONS} agent_iteration spans in the persisted trace, got {len(iter_spans2)}")
    root2 = next(s for s in persisted2.data.spans if s.name == "agent_run")
    check(root2.outputs["termination"] == al.TERMINATION_MAX_ITERATIONS, "root span outputs should show the bounded termination, not just 'it ran'")

    # --- Disallowed action: fail-closed, persisted trace shows no tool span ran ---
    fake_evil = ScriptedFakeClient([json.dumps({"thought": "no", "action": "rm_rf", "action_input": ""})])
    result3 = mc.run_with_mlflow_trace(
        "try something disallowed", client=fake_evil, rag_store=_fresh_test_store(),
        tracking_uri=TRACKING_URI, experiment_name=EXPERIMENT,
    )
    check(result3["termination"] == al.TERMINATION_DISALLOWED_ACTION, "expected disallowed_action")
    persisted3 = mlflow.get_trace(result3["mlflow_trace_id"])
    span_names3 = [s.name for s in persisted3.data.spans]
    check(not any(n.startswith("tool:") for n in span_names3), "FAIL-CLOSED: no tool:* span should exist when the action was never allowlisted")
    check("validate_step" in span_names3, "validate_step span should still exist, recording the rejection")

    print(f"All {checks} MLflow-comparison checks passed — real MLflow write+read round trip, "
          f"structural equivalence with the homegrown tracer confirmed, bounded terminations "
          f"correctly persisted and queryable by trace_id.")


if __name__ == "__main__":
    main()
