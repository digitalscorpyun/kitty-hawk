"""
agent_api.py — M5 FastAPI boundary over the M4 agent loop, with a trace

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md M5
Milestone: M5 FastAPI + observability
Concept: Expose the agentic loop behind a clean HTTP API boundary, and
         prove HTTP success != cognitive success -- a request can return
         200 while the underlying reasoning process failed to converge,
         timed out, or was refused for attempting a disallowed action.
         The trace (see trace.py), not the status code, is what actually
         shows which of those happened.

Execution tree this endpoint produces (per the gameplan's own spec):
    router -> agent_iteration (x1-3) -> model_call -> validate_step -> tool:<name>
                                                                     -> response

"router" wraps the whole request; each "agent_iteration" is one M4 loop
turn; "model_call" and "validate_step" are always present per iteration;
"tool:<name>" only appears when a real tool (not final_answer) was chosen.

NOT_YET_MODELED (explicit, per gameplan Section 6a; updated for M6a):
    - No auth/rate-limiting on this endpoint -- it is a reliability/
      observability demonstration, not a hardened public API (M6c).
    - MLflow library integration is a separate comparison path
      (core/mlflow_comparison.py), not wired into this endpoint.
    - The endpoint itself is still synchronous (FastAPI's def, not async
      def) -- that is a distinct concern from M6a's async *trace export*,
      which this file now performs via trace_export.AsyncTraceExporter.
    - M6a (see the exporter wiring below): sampled traces are persisted to
      a local JSONL file, asynchronously, decoupled from the request/
      response cycle. This is a placeholder sink, not the durable backend
      -- M6b replaces it with Postgres without changing the sampling/async
      logic. No delivery guarantee: a process crash or sink failure between
      response and background write silently loses that trace (an accepted,
      bounded risk per the M6.0 architecture decision record in the
      gameplan, not solved by new infrastructure here).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(THIS_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi import Depends, FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent_loop import run_agent_loop, MAX_ITERATIONS, DEFAULT_TIMEOUT_SECONDS  # noqa: E402
from provider_protocol import SynapseProvider  # noqa: E402
from rag.store import RagStore  # noqa: E402
from trace import Tracer  # noqa: E402
from trace_export import (  # noqa: E402
    AsyncTraceExporter,
    DEFAULT_SUCCESS_SAMPLE_RATE,
    make_local_jsonl_sink,
    make_rate_sampler,
    should_keep_full,
)

_DEFAULT_TRACE_PATH = REPO_ROOT / "kitty_hawk_traces.jsonl"
_success_sampler = make_rate_sampler(DEFAULT_SUCCESS_SAMPLE_RATE)

app = FastAPI(
    title="Kitty Hawk M5 — Bounded Agent Loop with Trace",
    description="Exposes the M4 bounded agent/tool loop over HTTP, returning the full execution trace alongside the result -- not just an HTTP status.",
)


def get_client() -> "SynapseProvider | None":
    """FastAPI dependency, real default: None tells run_agent_loop to build
    its own WatsonXClient. Offline tests override this dependency with a
    FakeClient via app.dependency_overrides -- the request/response schema
    never exposes client injection, since a real HTTP caller must never be
    able to swap in a fake model."""
    return None


def get_rag_store() -> "RagStore | None":
    """Real default: None tells run_agent_loop to build its own ephemeral
    RagStore over the controlled corpus. Offline tests override this with a
    store pre-loaded from the deterministic test corpus."""
    return None


def get_trace_exporter() -> AsyncTraceExporter:
    """Real default: appends sampled/kept traces to a local JSONL file (see
    trace_export.make_local_jsonl_sink) -- a placeholder sink, not the
    durable backend M6b calls for. Offline tests override this dependency
    with an in-memory sink so they can assert on export calls directly,
    without touching disk."""
    return AsyncTraceExporter(sink=make_local_jsonl_sink(_DEFAULT_TRACE_PATH))


class RunRequest(BaseModel):
    goal: str
    max_iterations: int = MAX_ITERATIONS
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


class RunResponse(BaseModel):
    goal: str
    termination: str
    answer: str | None
    iterations_used: int
    elapsed_seconds: float
    trace: dict[str, Any] | None


@app.post("/agent/run", response_model=RunResponse)
def run(
    req: RunRequest,
    client: "SynapseProvider | None" = Depends(get_client),
    rag_store: "RagStore | None" = Depends(get_rag_store),
    exporter: AsyncTraceExporter = Depends(get_trace_exporter),
) -> RunResponse:
    """Always returns HTTP 200 on a bounded termination (success,
    max_iterations, timeout, disallowed_action) -- these are valid outcomes
    of a working system, not errors. A 5xx here would mean something
    actually crashed (e.g. the empty-goal ValueError), which is a distinct,
    real failure the trace's "router" span would also capture as status=error."""
    tracer = Tracer()
    with tracer.span("router", goal=req.goal):
        result = run_agent_loop(
            req.goal,
            client=client,
            rag_store=rag_store,
            max_iterations=req.max_iterations,
            timeout_seconds=req.timeout_seconds,
            tracer=tracer,
        )
        with tracer.span("response", termination=result["termination"]):
            pass  # the response span marks hand-off back to the HTTP layer itself

    trace_dict = tracer.to_dict()

    # M6a: sampling keyed on Kitty Hawk's own termination state (and any
    # real exception anywhere in the span tree), never on HTTP status -- a
    # bounded non-success termination is HTTP 200 above and must still be
    # kept at 100%. Export is fire-and-forget: the response returned below
    # never waits on it (see trace_export.AsyncTraceExporter). The caller
    # always receives the full trace inline regardless of this decision --
    # sampling controls what gets persisted, not what the caller sees.
    if should_keep_full(result["termination"], trace_dict) or _success_sampler():
        exporter.export(trace_dict)

    return RunResponse(
        goal=result["goal"],
        termination=result["termination"],
        answer=result["answer"],
        iterations_used=result["iterations_used"],
        elapsed_seconds=result["elapsed_seconds"],
        trace=trace_dict,
    )
