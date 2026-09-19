"""
mlflow_comparison.py — M5 comparison: homegrown trace.py vs. real MLflow tracing

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md M5:
    "Use your own trace first, then compare to MLflow's mlflow.trace /
    autolog pattern from the IBM transcript."

This module answers that directly by running the *same*
agent_loop.run_agent_loop() through the *same* tracer call-sites already
written for M5 (_maybe_span in agent_loop.py) -- but backed by a real
MLflow trace instead of the homegrown Tracer from trace.py. Nothing in
agent_loop.py changes; only the object passed as `tracer=` changes, which
is itself the point: those instrumentation call-sites were backend-
agnostic by construction, and this proves it by swapping the backend.

Findings from actually doing this (observed while building, not asserted
in advance):

1. `mlflow.start_span()` (manual spans), not the `@mlflow.trace` decorator,
   is MLflow's own recommended method here. Per MLflow's own bundled
   instrumentation guide (`mlflow/assistant/skills/
   instrumenting-with-mlflow-tracing/references/python.md`), the decorator
   is for whole functions; manual spans are for "tracing code not wrapped
   in a function (e.g., script-level code, loop bodies)" and "dynamic span
   names computed at runtime" -- exactly this shape (a `for` loop producing
   per-iteration spans, and `tool:<action>` names only known once the model
   chooses an action).
2. That same guide explicitly warns against exactly the pattern this
   project's homegrown tracer uses for tool/model spans: recording a
   length (`observation_chars`, `prompt_chars`) instead of the actual
   content -- "A span that records {'matches': 20} instead of the actual
   documents is useless for debugging." That is a genuine trace.py
   limitation this comparison surfaced. It is named here, not silently
   fixed by rewriting M4/M5's already-committed instrumentation calls.
3. The local file-based tracking backend (`./mlruns`) is in "maintenance
   mode" for trace *reads* as of MLflow 3.16 -- `get_trace()` /
   `search_traces()` need a database backend (`sqlite:///...` here) to
   actually work, not just write. This module defaults to sqlite for
   exactly that reason.
4. Trace logging is asynchronous by default. Querying immediately after a
   run without `mlflow.flush_trace_async_logging()` can return nothing even
   though the write lands moments later -- this module flushes before
   returning, so a caller's very next `mlflow.get_trace(...)` call is safe.

NOT covered by this comparison (explicit, not hidden): MLflow's autolog
integrations (LangChain/OpenAI/etc.) -- not applicable, since Kitty Hawk's
loop is hand-rolled, not built on a framework autolog supports. The MLflow
trace UI (`mlflow ui`) itself is not exercised here; this module proves
persistence and queryability via the Python API only.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(THIS_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import mlflow  # noqa: E402

from agent_loop import run_agent_loop  # noqa: E402
from provider_protocol import SynapseProvider  # noqa: E402
from rag.store import RagStore  # noqa: E402

DEFAULT_TRACKING_URI = "sqlite:///mlflow_kitty_hawk_comparison.db"
DEFAULT_EXPERIMENT = "kitty-hawk-m5-comparison"


class _AttrProxy:
    """Adapts trace.Span's `.attributes[key] = value` dict-style interface
    (used directly by agent_loop.py's post-hoc attribute sets, e.g.
    `iter_span.attributes["termination"] = ...`) onto real MLflow spans.
    MLflow distinguishes span inputs/outputs from generic attributes; the
    homegrown Tracer does not need to make that distinction. Values
    accumulated here become the span's `outputs` on close."""

    def __init__(self) -> None:
        self.outputs: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self.outputs[key] = value


class _SpanHandle:
    """Mirrors trace.Span's shape closely enough for agent_loop.py's call
    sites: `.attributes[key] = value` must work on the yielded object."""

    def __init__(self, proxy: _AttrProxy) -> None:
        self.attributes = proxy


class MlflowSpanTracer:
    """Implements the exact same `.span(name, **attrs)` context-manager
    interface as trace.Tracer (see trace.py), so agent_loop.py's
    instrumentation call-sites run completely unchanged against a real
    MLflow trace instead of the homegrown one. This class *is* the
    comparison: same instrumentation code, different backend.

    Must be used inside an already-open mlflow.start_span(...) root (see
    run_with_mlflow_trace below) -- MLflow's start_span() nests under
    whatever span is currently active, but starts a brand-new, separate
    trace if nothing is active. Without an explicit root, this loop's
    several top-level `agent_iteration` spans would each become their own
    disconnected trace instead of one coherent run."""

    @contextmanager
    def span(self, name: str, **attributes: Any):
        with mlflow.start_span(name=name) as real_span:
            if attributes:
                # Span-open kwargs (e.g. iteration=1, action_input="...")
                # are the closest analog to a function's real inputs.
                real_span.set_inputs(attributes)
            proxy = _AttrProxy()
            try:
                yield _SpanHandle(proxy)
            finally:
                if proxy.outputs:
                    real_span.set_outputs(proxy.outputs)


def run_with_mlflow_trace(
    goal: str,
    *,
    client: "SynapseProvider | None" = None,
    rag_store: "RagStore | None" = None,
    max_iterations: int | None = None,
    timeout_seconds: float | None = None,
    tracking_uri: str = DEFAULT_TRACKING_URI,
    experiment_name: str = DEFAULT_EXPERIMENT,
) -> dict[str, Any]:
    """Runs the identical M4 loop, traced by real MLflow instead of
    trace.py. Returns run_agent_loop's own result dict plus one extra key,
    `mlflow_trace_id`, so a caller can pull the persisted trace back later
    with `mlflow.get_trace(result['mlflow_trace_id'])` -- proving
    persistence, the one thing the homegrown tracer's inline JSON cannot
    do on its own (see trace.py's own docstring)."""
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)

    tracer = MlflowSpanTracer()
    kwargs: dict[str, Any] = {"client": client, "rag_store": rag_store, "tracer": tracer}
    if max_iterations is not None:
        kwargs["max_iterations"] = max_iterations
    if timeout_seconds is not None:
        kwargs["timeout_seconds"] = timeout_seconds

    # Root span: without this, each top-level agent_iteration call starts
    # an *independent* MLflow trace instead of nesting under one shared
    # root -- observed directly while building this module (only the last
    # iteration's spans were retrievable via get_last_active_trace_id()
    # until this wrapper was added). trace.Tracer's own _stack mechanism
    # makes this implicit; MLflow's start_span() does not, without an
    # already-open parent to nest under.
    with mlflow.start_span(name="agent_run") as root:
        root.set_inputs({"goal": goal})
        result = run_agent_loop(goal, **kwargs)
        root.set_outputs({"termination": result["termination"], "answer": result["answer"]})
    mlflow.flush_trace_async_logging()
    result["mlflow_trace_id"] = mlflow.get_last_active_trace_id()
    return result
