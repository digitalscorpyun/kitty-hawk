"""
m1_evaluation.py — M2 Evaluation Baseline (ONE PING evaluated)

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md M2
Milestone: M2 evaluation baseline (Chip Ch 3-4: define "correct" before complexity)
Concept: Exact/schema checks, latency threshold, failure-case list for M1.
         Captures baseline trace so HTTP 200 != cognitive success is provable.
         Prompt/context small by design; trace is the future M5 MLflow span.

Evidence: Baseline trace dict + deterministic evaluation functions validated offline.

Trace shape (M5-ready):
  request -> watsonx_ping -> validator -> response
  with latency_ms, ask_calls, schema_ok, cognitive_success, http_success
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sys

THIS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = THIS_DIR.parent / "scripts"
CORE_DIR = THIS_DIR.parent / "core"
for p in (str(SCRIPTS_DIR), str(CORE_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from watsonx_ping import ALLOWED_TOOL_USED, watsonx_ping  # noqa: E402

# M1 failure-case registry — the list that proves "correct" was defined before complexity
M1_FAILURE_CASES: list[dict[str, str]] = [
    {"id": "FC-M1-01", "category": "malformed_json", "description": "Model returns non-JSON string", "expected": "ValueError: valid JSON"},
    {"id": "FC-M1-02", "category": "missing_keys", "description": "JSON missing required keys goal/answer/tool_used", "expected": "ValueError: missing key"},
    {"id": "FC-M1-03", "category": "invalid_tool", "description": "tool_used not in (none, read_kitty_hawk_manifest)", "expected": "ValueError: tool_used"},
    {"id": "FC-M1-04", "category": "hallucinated_tool_use", "description": "tool_used==none but answer claims file read", "expected": "ValueError: Hallucinated"},
    {"id": "FC-M1-05", "category": "empty_goal", "description": "Empty/whitespace goal", "expected": "ValueError: goal must be non-empty"},
    {"id": "FC-M1-06", "category": "empty_model_response", "description": "Model returns empty string", "expected": "ValueError: valid JSON"},
]

DEFAULT_LATENCY_THRESHOLD_MS = 2000  # offline FakeClient < 10ms; live Granite < 15000ms is still cognitive success if schema ok


@dataclass(frozen=True)
class M1Evaluation:
    passed: bool  # cognitive_success
    http_success: bool  # transport succeeded (ask returned string)
    cognitive_success: bool  # all semantic checks passed
    schema_ok: bool
    one_ping_ok: bool
    latency_ok: bool
    latency_ms: float
    ask_calls: int
    tool_used: str | None
    reason: str
    failure_case_id: str | None = None

    def to_trace(self, goal: str, raw_response: str | None = None) -> dict[str, Any]:
        """M5-ready trace: one ping's execution tree."""
        return {
            "goal": goal,
            "request": {"goal": goal, "allowed_tools": list(ALLOWED_TOOL_USED)},
            "model": {"raw": raw_response, "tool_used": self.tool_used, "ask_calls": self.ask_calls},
            "validator": {
                "schema_ok": self.schema_ok,
                "one_ping_ok": self.one_ping_ok,
                "latency_ok": self.latency_ok,
                "latency_ms": self.latency_ms,
                "cognitive_success": self.cognitive_success,
            },
            "response": {"passed": self.passed, "reason": self.reason, "http_success": self.http_success},
            "thresholds": {"latency_ms": DEFAULT_LATENCY_THRESHOLD_MS},
            "failure_case_id": self.failure_case_id,
        }


def evaluate_schema(result: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, f"result must be dict, got {type(result)}"
    for k in ("goal", "answer", "tool_used", "raw"):
        if k not in result:
            return False, f"missing key {k!r}"
    if result.get("tool_used") not in ALLOWED_TOOL_USED:
        return False, f"tool_used {result.get('tool_used')!r} not in {ALLOWED_TOOL_USED}"
    try:
        json.loads(result.get("raw", ""))
    except Exception as e:
        return False, f"raw not valid JSON: {e}"
    if not isinstance(result.get("answer"), str) or not result["answer"].strip():
        return False, "answer must be non-empty string"
    return True, "schema ok"


def evaluate_one_ping(client: Any) -> tuple[bool, str]:
    calls = getattr(client, "ask_calls", None)
    if calls is None:
        return False, "client has no ask_calls (cannot verify one-ping invariant)"
    n = len(calls)
    if n != 1:
        return False, f"expected exactly 1 ask() call, got {n}"
    return True, "one ping ok"


def evaluate_latency(latency_ms: float, threshold_ms: float = DEFAULT_LATENCY_THRESHOLD_MS) -> tuple[bool, str]:
    if latency_ms > threshold_ms:
        return False, f"latency {latency_ms:.1f}ms > threshold {threshold_ms}ms"
    return True, f"latency {latency_ms:.1f}ms ok"


def evaluate_exact(result: dict[str, Any], expected_tool_used: str | None = None) -> tuple[bool, str]:
    """Exact check: when caller knows expected tool_used, enforce it."""
    if expected_tool_used is None:
        return True, "no expected_tool_used to check"
    if result.get("tool_used") != expected_tool_used:
        return False, f"exact tool_used mismatch: expected {expected_tool_used!r}, got {result.get('tool_used')!r}"
    return True, "exact ok"


def capture_baseline_trace(goal: str, *, client: Any, threshold_ms: float = DEFAULT_LATENCY_THRESHOLD_MS, expected_tool_used: str | None = None) -> tuple[M1Evaluation, dict[str, Any]]:
    """Run one ping and evaluate it, returning (evaluation, trace).

    HTTP success = ask() returned a string (transport ok).
    Cognitive success = schema + one_ping + latency + exact all ok.
    """
    start = time.perf_counter()
    http_success = False
    raw_response: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    try:
        # Call the real M1 boundary; watsonx_ping will raise on schema failure
        result = watsonx_ping(goal, client=client)
        raw_response = result.get("raw")
        http_success = True
    except Exception as e:
        error = str(e)
        # Try to capture raw if FakeClient stashed it
        raw_response = getattr(client, "ask_calls", [None])[-1] if getattr(client, "ask_calls", None) else None
        if isinstance(raw_response, str) and len(raw_response) > 500:
            raw_response = raw_response[:500]
        http_success = error is None

    latency_ms = (time.perf_counter() - start) * 1000.0
    # Evaluate even on error path
    if result is not None:
        schema_ok, schema_reason = evaluate_schema(result)
        tool_used = result.get("tool_used")
        exact_ok, exact_reason = evaluate_exact(result, expected_tool_used)
    else:
        schema_ok, schema_reason = False, error or "no result"
        tool_used = None
        exact_ok, exact_reason = False, "no result for exact"

    one_ping_ok, one_ping_reason = evaluate_one_ping(client)
    latency_ok, latency_reason = evaluate_latency(latency_ms, threshold_ms)

    cognitive_success = schema_ok and one_ping_ok and latency_ok and exact_ok
    passed = cognitive_success and http_success

    if not passed:
        reasons = []
        if not http_success:
            reasons.append(f"http_failure: {error}")
        if not schema_ok:
            reasons.append(f"schema: {schema_reason}")
        if not one_ping_ok:
            reasons.append(f"one_ping: {one_ping_reason}")
        if not latency_ok:
            reasons.append(f"latency: {latency_reason}")
        if not exact_ok:
            reasons.append(f"exact: {exact_reason}")
        reason = "; ".join(reasons)
    else:
        reason = "baseline ok: schema+one_ping+latency+exact all passed"

    ev = M1Evaluation(
        passed=passed,
        http_success=http_success,
        cognitive_success=cognitive_success,
        schema_ok=schema_ok,
        one_ping_ok=one_ping_ok,
        latency_ok=latency_ok,
        latency_ms=latency_ms,
        ask_calls=len(getattr(client, "ask_calls", [])),
        tool_used=tool_used,
        reason=reason,
    )
    trace = ev.to_trace(goal, raw_response)
    return ev, trace


def baseline_report(goal: str, *, client: Any) -> dict[str, Any]:
    """Convenience: one-ping baseline report for logging/teaching."""
    ev, trace = capture_baseline_trace(goal, client=client)
    return {
        "milestone": "M2 evaluation baseline",
        "concept": "define correct before complexity: schema/exact/latency/failure-cases; HTTP 200 != cognitive success",
        "goal": goal,
        "evaluation": asdict(ev),
        "trace": trace,
        "failure_cases": M1_FAILURE_CASES,
        "invariant": "exactly one ask() call per invocation (M5 trace condition)",
    }
