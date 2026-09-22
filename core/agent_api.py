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

NOT_YET_MODELED (explicit, per gameplan Section 6a; updated for M6c):
    - M6c (see the route decorator below): this endpoint now requires a
      valid bearer token (auth.verify_api_key, KITTY_HAWK_API_KEY) --
      fail-closed if unset/empty, constant-time comparison, rejection
      happens before Tracer construction or run_agent_loop is ever
      called. Still not modeled: rate-limiting (unchanged since M5),
      authorization/roles (one endpoint, binary allowed/not-allowed
      only), the AWS API Gateway auth mechanism (M6.0's open item,
      deferred to M6d), key rotation/secrets-manager integration, and
      multiple/per-caller credentials (one shared token only).
    - MLflow library integration is a separate comparison path
      (core/mlflow_comparison.py), not wired into this endpoint.
    - The endpoint itself is still synchronous (FastAPI's def, not async
      def) -- that is a distinct concern from M6a's async *trace export*,
      which this file now performs via trace_export.AsyncTraceExporter.
    - M6b (see the exporter wiring below): sampled traces are persisted via
      trace_store.make_sql_sink -- a real SQLAlchemy-backed sink, default
      local SQLite (KITTY_HAWK_TRACE_DB_URL unset), swappable to Postgres
      by setting that env var to a Postgres URL with no code change here.
      No AWS resource is chosen, provisioned, or billed by this wiring
      (M6.0's RDS question stays open, deferred to M6d). No delivery
      guarantee: a process crash or sink failure between response and
      background write silently loses that trace (an accepted, bounded
      risk per the M6.0 architecture decision record in the gameplan, not
      solved by new infrastructure here -- unchanged since M6a).
"""
from __future__ import annotations

import os
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
from sqlalchemy import create_engine  # noqa: E402

from agent_loop import run_agent_loop, MAX_ITERATIONS, DEFAULT_TIMEOUT_SECONDS  # noqa: E402
from auth import verify_api_key  # noqa: E402
from provider_protocol import SynapseProvider  # noqa: E402
from rag.store import RagStore  # noqa: E402
from trace import Tracer  # noqa: E402
from trace_export import (  # noqa: E402
    AsyncTraceExporter,
    DEFAULT_SUCCESS_SAMPLE_RATE,
    make_rate_sampler,
    should_keep_full,
)
from trace_store import make_sql_sink  # noqa: E402

_DEFAULT_TRACE_DB_URL = f"sqlite:///{REPO_ROOT / 'kitty_hawk_traces.db'}"
_success_sampler = make_rate_sampler(DEFAULT_SUCCESS_SAMPLE_RATE)
_trace_engine = None  # lazily created once per process, see _get_trace_engine below

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


def _get_trace_engine():
    """One SQLAlchemy engine (and its connection pool) per process, created
    lazily on first use and reused across requests -- not recreated per
    request, which would otherwise open a fresh pool (and, on SQLite, a
    fresh file handle) on every call. Pool sizing/behavior under concurrent
    load is otherwise untouched (NOT_YET_MODELED, M6b scope)."""
    global _trace_engine
    if _trace_engine is None:
        _trace_engine = create_engine(os.environ.get("KITTY_HAWK_TRACE_DB_URL", _DEFAULT_TRACE_DB_URL))
    return _trace_engine


def get_trace_exporter() -> AsyncTraceExporter:
    """Real default: persists sampled/kept traces via trace_store's
    SQLAlchemy sink to a local SQLite file. KITTY_HAWK_TRACE_DB_URL
    overrides the target -- pointing it at a Postgres URL swaps the durable
    backend with no code change here, proving the sink is built against the
    SQLAlchemy abstraction with Postgres as the intended database class.
    This wiring does not choose, provision, or bill any hosted production
    service (M6.0's RDS question stays open). Offline tests override this
    dependency with an in-memory sink so they can assert on export calls
    directly, without touching disk."""
    return AsyncTraceExporter(sink=make_sql_sink(_get_trace_engine()))


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


@app.post("/agent/run", response_model=RunResponse, dependencies=[Depends(verify_api_key)])
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
