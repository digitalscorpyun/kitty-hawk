"""
trace_store.py — M6b: durable trace persistence via SQLAlchemy

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md, M6.0 decision
record (Section 6, "M6.0 DECIDED") and M6b.

Concept: swap trace_export.py's placeholder JSONL sink for a real durable
sink, without touching AsyncTraceExporter or should_keep_full at all --
both already treat `sink` as an opaque `Callable[[dict[str, Any]], None]`.
This module supplies that callable, built against the SQLAlchemy engine
abstraction so the identical schema/insert/query code runs unmodified
against SQLite (CI, both ubuntu-latest and windows-latest) or Postgres
(the intended production database class) -- only the connection URL
passed to `create_engine` differs.

M6.0 explicitly left open whether the durable backend needs AWS RDS. M6b
does not resolve that, and does not choose, provision, or incur cost for
any hosted production service: building against the SQLAlchemy engine
abstraction with Postgres as the intended dialect is the whole of M6b's
production-readiness claim here. Where and how a real Postgres instance
is hosted remains explicitly deferred (M6d, AWS extension) -- named as
still open, not silently assumed one way or the other.

Trace-ID note: Tracer.to_dict() (trace.py) returns a bare span tree with
no trace_id of its own -- unlike MLflow's library-assigned trace_id (see
the M5 mlflow_comparison.py finding), this homegrown tracer has never
produced one. This store therefore assigns the ID (a uuid4 string) at
persistence time; "queryable by trace_id" means queryable by the ID this
store assigned when it wrote the row, which is the concrete claim M6b
verifies -- not an ID that existed on the trace before this module saw it.

NOT_YET_MODELED (explicit, M6b scope only):
    - Connection pooling / behavior under concurrent load.
    - Migrations tooling (e.g. Alembic) -- schema is created via
      `metadata.create_all`, adequate for this milestone's single-table
      schema, not a migration strategy for future schema changes.
    - Retry/backoff or any delivery guarantee beyond what M6a already
      named as an accepted, bounded risk -- a sink write that raises
      still isolates to AsyncTraceExporter's background thread and the
      trace is lost, exactly as before this module existed.
    - Production RDS/provider infrastructure -- no AWS resource is
      chosen, provisioned, or billed here (M6.0 open item, deferred to
      M6d, AWS extension).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import (
    Column,
    DateTime,
    Engine,
    MetaData,
    String,
    Table,
    Text,
    insert,
    select,
)

metadata = MetaData()

traces_table = Table(
    "traces",
    metadata,
    Column("trace_id", String(36), primary_key=True),
    Column("termination", String(64), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("payload", Text, nullable=False),
)


def init_schema(engine: Engine) -> None:
    """Idempotent: creates the `traces` table if it does not already exist.
    Safe to call once at startup or on every sink write -- create_all
    no-ops when the table is already present, identically on SQLite and
    Postgres."""
    metadata.create_all(engine, checkfirst=True)


def _termination_of(trace: dict[str, Any] | None) -> str | None:
    """The trace payload is a span tree, not a flat record -- termination
    lives on the 'response' span's attributes (see agent_api.py's response
    span). Absent for traces built outside that endpoint (e.g. a bare
    Tracer used directly in a test), which is fine here: termination is
    filter metadata, not required for round-trip or query-by-trace_id."""
    if trace is None:
        return None
    if trace.get("name") == "response":
        return trace.get("attributes", {}).get("termination")
    for child in trace.get("children", []):
        found = _termination_of(child)
        if found is not None:
            return found
    return None


def make_sql_sink(engine: Engine) -> Callable[[dict[str, Any]], None]:
    """M6b durable sink: persists one row per trace to the `traces` table
    via the given SQLAlchemy engine. Matches trace_export.py's
    `Callable[[dict[str, Any]], None]` sink contract exactly, so it drops
    in for `make_local_jsonl_sink` with zero changes to AsyncTraceExporter
    or the sampling gate. `engine` decides SQLite vs. Postgres -- this
    function is dialect-agnostic."""
    init_schema(engine)

    def _sink(trace: dict[str, Any]) -> None:
        with engine.begin() as conn:
            conn.execute(
                insert(traces_table).values(
                    trace_id=str(uuid.uuid4()),
                    termination=_termination_of(trace),
                    started_at=datetime.now(timezone.utc),
                    payload=json.dumps(trace),
                )
            )

    return _sink


def get_trace(engine: Engine, trace_id: str) -> dict[str, Any] | None:
    """Query-by-trace_id -- the concrete capability the M6a JSONL
    placeholder could not offer. Returns the original trace payload
    (decoded from storage), or None if no row matches."""
    with engine.connect() as conn:
        row = conn.execute(
            select(traces_table).where(traces_table.c.trace_id == trace_id)
        ).first()
    if row is None:
        return None
    return json.loads(row.payload)


def list_traces(engine: Engine, termination: str | None = None) -> list[dict[str, Any]]:
    """Returns every persisted trace as
    {"trace_id", "termination", "started_at", "payload"}, most-recent-last,
    optionally filtered by termination state."""
    stmt = select(traces_table).order_by(traces_table.c.started_at)
    if termination is not None:
        stmt = stmt.where(traces_table.c.termination == termination)
    with engine.connect() as conn:
        rows = conn.execute(stmt).all()
    return [
        {
            "trace_id": r.trace_id,
            "termination": r.termination,
            "started_at": r.started_at,
            "payload": json.loads(r.payload),
        }
        for r in rows
    ]
