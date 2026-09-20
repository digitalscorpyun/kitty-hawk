"""
test_m6a_sampling_export.py — M6a: sampling policy + async trace export

Proves the M6a lesson directly: sampling must key on Kitty Hawk's own
semantic termination state (and real exceptions), never on HTTP status --
a bounded non-success termination is HTTP 200 (M5) and must still be kept
at 100%. Separately proves async export is genuinely decoupled: a slow or
failing sink never blocks or breaks the request path. Offline: no network,
no credentials, no live watsonx.ai call. File I/O is confined to a temp
directory (make_local_jsonl_sink) or skipped entirely (in-memory sinks).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-m6a")

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
from trace_export import (  # noqa: E402
    AsyncTraceExporter,
    make_local_jsonl_sink,
    make_rate_sampler,
    should_keep_full,
)


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

    ok_trace = {"name": "router", "status": "ok", "children": [
        {"name": "response", "status": "ok", "children": []}
    ]}
    errored_trace = {"name": "router", "status": "ok", "children": [
        {"name": "validate_step", "status": "error", "children": []}
    ]}

    # --- should_keep_full: sampling gate keys on termination, not transport ---
    check(should_keep_full("max_iterations", ok_trace) is True,
          "max_iterations must be kept at 100% even with an all-ok trace (HTTP 200 case)")
    check(should_keep_full("timeout", ok_trace) is True,
          "timeout must be kept at 100% even with an all-ok trace (HTTP 200 case)")
    check(should_keep_full("disallowed_action", ok_trace) is True,
          "disallowed_action must be kept at 100% even with an all-ok trace (HTTP 200 case)")
    check(should_keep_full("success", ok_trace) is False,
          "a clean success termination with no error spans is NOT force-kept -- eligible for sampling")
    check(should_keep_full("success", errored_trace) is True,
          "a real exception anywhere in the span tree forces a keep, even under a 'success' termination")
    check(should_keep_full("success", None) is False,
          "a missing trace with a success termination must not force a keep")

    # --- make_rate_sampler: deterministic under an injected rng ---
    fixed_low = make_rate_sampler(0.5, rng=lambda: 0.1)
    fixed_high = make_rate_sampler(0.5, rng=lambda: 0.9)
    check(fixed_low() is True, "rng below the rate should sample in")
    check(fixed_high() is False, "rng at/above the rate should sample out")

    # --- AsyncTraceExporter: never blocks the caller ---
    def slow_sink(trace: dict) -> None:
        time.sleep(0.3)

    exporter_slow = AsyncTraceExporter(sink=slow_sink)
    t0 = time.monotonic()
    handle = exporter_slow.export({"name": "router"})
    elapsed = time.monotonic() - t0
    check(elapsed < 0.1, f"export() must return immediately, not block on a slow sink (took {elapsed:.3f}s)")
    handle.thread.join(timeout=2.0)
    check(handle.record.attempted is True, "background thread should have attempted the slow sink")
    check(handle.record.succeeded is True, "slow-but-successful sink should record success")

    # --- AsyncTraceExporter: sink failure is isolated, never propagates ---
    def failing_sink(trace: dict) -> None:
        raise RuntimeError("durable store unreachable")

    exporter_fail = AsyncTraceExporter(sink=failing_sink)
    try:
        handle2 = exporter_fail.export({"name": "router"})
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
        handle2 = None
    check(raised is False, "a failing sink must never raise into the caller's request path")
    handle2.thread.join(timeout=2.0)
    check(handle2.record.succeeded is False, "failing sink should record failure, not silently look successful")
    check(handle2.record.error is not None and "unreachable" in handle2.record.error,
          "failure record should carry the sink's own error message")

    # --- make_local_jsonl_sink: real (temp-dir) durability placeholder ---
    with tempfile.TemporaryDirectory() as tmp:
        jsonl_path = Path(tmp) / "traces.jsonl"
        sink = make_local_jsonl_sink(jsonl_path)
        sink({"name": "router", "termination": "success"})
        sink({"name": "router", "termination": "max_iterations"})
        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        check(len(lines) == 2, f"expected 2 appended JSON lines, got {len(lines)}")
        parsed = [json.loads(l) for l in lines]
        check(parsed[0]["termination"] == "success" and parsed[1]["termination"] == "max_iterations",
              "JSONL sink must preserve write order and content")

    # --- Integration: agent_api wires the sampling/export decision correctly ---
    client_app = TestClient(api.app, raise_server_exceptions=False)

    class RecordingExporter:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def export(self, trace: dict) -> None:
            self.calls.append(trace)

    recorder = RecordingExporter()
    api.app.dependency_overrides[api.get_trace_exporter] = lambda: recorder
    api.app.dependency_overrides[api.get_rag_store] = _fresh_test_store

    # Non-success termination: must always export, regardless of the success sampler.
    original_sampler = api._success_sampler
    api._success_sampler = lambda: False  # force "would-sample-out" for the success path
    non_finalizing = json.dumps({"thought": "again", "action": al.ACTION_MANIFEST, "action_input": ""})
    api.app.dependency_overrides[api.get_client] = lambda: ScriptedFakeClient([non_finalizing] * al.MAX_ITERATIONS)
    resp1 = client_app.post("/agent/run", json={"goal": "never finish"})
    check(resp1.status_code == 200, "max_iterations must still be HTTP 200 (M5 finding, unchanged by M6a)")
    check(len(recorder.calls) == 1, "max_iterations trace must be exported even though the success sampler would say no")
    check(resp1.json()["trace"] is not None, "caller must still receive the full trace inline regardless of export/sampling")

    # Success termination, sampler says no: must NOT export.
    recorder.calls.clear()
    fake_success = ScriptedFakeClient([
        json.dumps({"thought": "done", "action": al.ACTION_FINAL, "action_input": "all good"}),
    ])
    api.app.dependency_overrides[api.get_client] = lambda: fake_success
    resp2 = client_app.post("/agent/run", json={"goal": "quick success"})
    check(resp2.status_code == 200, "success case should be HTTP 200")
    check(len(recorder.calls) == 0, "a clean success trace must be sampled OUT when the sampler says no")
    check(resp2.json()["trace"] is not None, "caller must still receive the full trace inline even when it was sampled out of export")

    # Success termination, sampler says yes: must export.
    recorder.calls.clear()
    api._success_sampler = lambda: True
    fake_success2 = ScriptedFakeClient([
        json.dumps({"thought": "done", "action": al.ACTION_FINAL, "action_input": "all good again"}),
    ])
    api.app.dependency_overrides[api.get_client] = lambda: fake_success2
    resp3 = client_app.post("/agent/run", json={"goal": "quick success again"})
    check(len(recorder.calls) == 1, "a clean success trace must be exported when the sampler says yes")

    api._success_sampler = original_sampler
    api.app.dependency_overrides.clear()

    print(f"All {checks} M6a sampling/export checks passed — sampling keys on termination state "
          f"(not HTTP status), async export never blocks or leaks a sink failure into the request path.")


if __name__ == "__main__":
    main()
