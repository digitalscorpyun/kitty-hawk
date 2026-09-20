"""
trace_export.py — M6a: sampling policy + async trace-export decoupling

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md, M6.0 decision
record (Section 6, "M6.0 DECIDED") and M6a.

Concept, taught and predicted correctly before this was built: sampling has
to key off Kitty Hawk's own semantic termination state, not HTTP status. A
bounded non-success termination (max_iterations, timeout, disallowed_action)
returns HTTP 200 (agent_api.py) -- exactly the M5 finding that HTTP success
!= cognitive success. A naive "keep errors, sample everything else" rule
keyed on transport status would silently sample away exactly the traces
most worth keeping. Separately, "async" here means the *write to durable
storage* is decoupled from the request/response cycle -- not that the
FastAPI handler itself is `async def` (a distinct, still-open concern).

NOT_YET_MODELED (explicit, M6a scope only):
    - The durable backend itself is M6b's job (Postgres). AsyncTraceExporter
      writes through a pluggable `sink` callable so the storage target can
      be swapped in M6b without touching sampling or async-export logic.
    - No delivery guarantee. If the background export raises, or the
      process dies between the response being sent and the write landing,
      the trace is silently lost. This is named here as an accepted,
      bounded risk -- per the M6.0 decision record, a durability mechanism
      (write-ahead log, outbox, queue) is new infrastructure requiring its
      own presented cost/teardown plan, not something to assume into this
      module.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

NON_SUCCESS_TERMINATIONS = {"max_iterations", "timeout", "disallowed_action"}
DEFAULT_SUCCESS_SAMPLE_RATE = 0.1


def _has_error_span(trace: dict[str, Any] | None) -> bool:
    """Depth-first check for any span with status == 'error' anywhere in
    the tree -- a real exception, distinct from a bounded non-success
    termination, whose spans still report status 'ok' (the loop itself
    didn't crash; it correctly stopped)."""
    if trace is None:
        return False
    if trace.get("status") == "error":
        return True
    return any(_has_error_span(c) for c in trace.get("children", []))


def should_keep_full(termination: str, trace: dict[str, Any] | None) -> bool:
    """The sampling gate. Keeps 100% of anything that is not a clean
    success: any non-success termination state, or any real exception
    anywhere in the span tree -- regardless of what the HTTP layer
    returned. Only a genuine `success` termination with no error spans is
    eligible for the rate sampler below."""
    if termination in NON_SUCCESS_TERMINATIONS:
        return True
    return _has_error_span(trace)


class Sampler(Protocol):
    def __call__(self) -> bool:
        """Returns True if this specific success-path trace should be kept."""
        ...


def make_rate_sampler(rate: float, rng: Callable[[], float] | None = None) -> Sampler:
    """Deterministic-under-test sampler: keeps a trace with probability
    `rate` (0.0-1.0). `rng` defaults to `random.random` but accepts an
    injected deterministic sequence for tests, avoiding flaky assertions
    on a real random source."""
    import random as _random
    _rng = rng or _random.random

    def _sample() -> bool:
        return _rng() < rate

    return _sample


@dataclass
class ExportRecord:
    """Test/observability hook: records what the background thread actually
    did. The request path never reads this before responding -- it exists
    so a caller (production log line, or a test) can inspect the outcome
    *after* the fact, without the response ever waiting on it."""
    attempted: bool = False
    succeeded: bool | None = None
    error: str | None = None


@dataclass
class ExportHandle:
    record: ExportRecord
    thread: threading.Thread = field(repr=False)


class AsyncTraceExporter:
    """Hands a trace off to `sink` on a background thread and returns
    immediately -- the caller (agent_api.py's request handler) never blocks
    on `sink` running or completing. `sink` is pluggable so the actual
    durable store (M6b: Postgres) can be swapped in without touching this
    class's sampling-agnostic export mechanics."""

    def __init__(self, sink: Callable[[dict[str, Any]], None]):
        self._sink = sink

    def export(self, trace: dict[str, Any]) -> ExportHandle:
        record = ExportRecord()

        def _run() -> None:
            record.attempted = True
            try:
                self._sink(trace)
                record.succeeded = True
            except Exception as exc:  # noqa: BLE001 -- isolated to the background thread by design; must never propagate to the request path
                record.succeeded = False
                record.error = str(exc)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return ExportHandle(record=record, thread=thread)


def make_local_jsonl_sink(path: Path) -> Callable[[dict[str, Any]], None]:
    """M6a placeholder durable-ish sink: appends one JSON line per trace to
    a local file. This is NOT the durable backend M6b calls for (Postgres)
    -- it exists only so M6a's async/sampling mechanics have something real
    to write to and verify, behind a sink interface M6b can replace wholesale
    without touching sampling or async-export logic."""
    def _sink(trace: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(trace) + "\n")
    return _sink
