"""
trace.py — M5 homegrown execution tracer (built before adopting MLflow)

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md M5
Concept: A span is a named unit of work with a start time, an end time, a
         status (ok/error), and whatever inputs/outputs are worth recording
         about it. Nesting spans inside each other reconstructs the actual
         execution tree: which stage called which, in what order, and how
         long each one took -- the exact shape an HTTP status code cannot
         show, because a 200 response only proves the outermost span
         finished without an unhandled exception, not that every span
         inside it did what it was supposed to.

This is intentionally small and dependency-free. The gameplan's own
instruction is to build this by hand before comparing it to MLflow's real
`mlflow.trace` / autolog pattern -- that comparison is a later, separate
step, not this one.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class Span:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list["Span"] = field(default_factory=list)
    status: str = "in_progress"  # "in_progress" | "ok" | "error"
    error: str | None = None
    _start: float = field(default_factory=time.monotonic, repr=False)
    _end: float | None = field(default=None, repr=False)

    @property
    def duration_ms(self) -> float | None:
        if self._end is None:
            return None
        return round((self._end - self._start) * 1000, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "error": self.error,
            "children": [c.to_dict() for c in self.children],
        }


class Tracer:
    """Builds one rooted tree of Spans per run. Not thread-safe by design --
    one Tracer per request, matching one execution tree per request.

    Callers that will open more than one top-level span in sequence (e.g.
    agent_loop.py's per-iteration `agent_iteration` spans across several
    loop turns) MUST wrap the whole sequence in one outer `with
    tracer.span(...)` first -- without that wrapper, the *second* top-level
    span raises RuntimeError, because the first already claimed the root
    and popped back off the stack. agent_api.py's "router" span exists for
    exactly this reason. This is not incidental: real MLflow's
    `mlflow.start_span()` has the identical constraint -- called with
    nothing already active, it starts a brand-new, disconnected trace each
    time rather than nesting under a prior sibling call (confirmed directly
    while building mlflow_comparison.py; see that module's own "agent_run"
    wrapper). Both tracers require an explicit outer span for a multi-call
    sequence to produce one coherent tree instead of several fragments."""

    def __init__(self) -> None:
        self.root: Span | None = None
        self._stack: list[Span] = []

    @contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[Span]:
        s = Span(name=name, attributes=dict(attributes))
        if self._stack:
            self._stack[-1].children.append(s)
        else:
            if self.root is not None:
                raise RuntimeError(
                    "Tracer already has a root span -- one Tracer instance "
                    "traces exactly one request. Use a fresh Tracer per call."
                )
            self.root = s
        self._stack.append(s)
        try:
            yield s
            s.status = "ok"
        except Exception as exc:  # noqa: BLE001 -- re-raised immediately, never swallowed
            s.status = "error"
            s.error = str(exc)
            raise
        finally:
            s._end = time.monotonic()
            self._stack.pop()

    def to_dict(self) -> dict[str, Any] | None:
        return self.root.to_dict() if self.root else None

    def find_all(self, name: str) -> list[Span]:
        """Depth-first search for every span with this exact name, anywhere
        in the tree. Useful for tests asserting a specific stage ran."""
        found: list[Span] = []

        def _walk(s: Span) -> None:
            if s.name == name:
                found.append(s)
            for c in s.children:
                _walk(c)

        if self.root is not None:
            _walk(self.root)
        return found
