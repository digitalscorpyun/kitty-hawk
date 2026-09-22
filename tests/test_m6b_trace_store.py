"""
test_m6b_trace_store.py — M6b: durable trace persistence via SQLAlchemy

Proves the M6b claim directly against a real SQLAlchemy engine (SQLite, so
this runs identically on ubuntu-latest and windows-latest with no service
container): schema creation, a real sink write, round-trip persistence,
and query by the trace_id this store assigns -- the concrete capability
the M6a JSONL placeholder could not offer. Also proves the sink drops into
agent_api.py's real dependency wiring with no changes to
AsyncTraceExporter or the sampling gate.

Dialect-specific Postgres behavior is NOT exercised here by design -- see
test_m6b_trace_store_live_postgres.py (live-gated, not run in CI). This
file stays entirely local: no network, no credentials, no AWS resource of
any kind.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-m6b")

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(REPO_ROOT / "core"), str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import create_engine  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import agent_loop as al  # noqa: E402
from rag.store import RagStore  # noqa: E402
from rag.corpus import load_min_corpus_for_tests  # noqa: E402
from trace_store import get_trace, init_schema, list_traces, make_sql_sink, traces_table  # noqa: E402


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

    ok_trace = {
        "name": "router", "status": "ok", "duration_ms": 1.0,
        "attributes": {"goal": "test goal"}, "error": None,
        "children": [
            {"name": "response", "status": "ok", "duration_ms": 0.1,
             "attributes": {"termination": "success"}, "error": None, "children": []},
        ],
    }
    max_iter_trace = {
        "name": "router", "status": "ok", "duration_ms": 2.0,
        "attributes": {"goal": "never finish"}, "error": None,
        "children": [
            {"name": "response", "status": "ok", "duration_ms": 0.1,
             "attributes": {"termination": "max_iterations"}, "error": None, "children": []},
        ],
    }

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "m6b_unit.db"
        engine = create_engine(f"sqlite:///{db_path}")

        # --- schema creation is idempotent ---
        init_schema(engine)
        init_schema(engine)  # second call must not raise or duplicate the table
        # engine.connect() checks out a pooled connection; it must be closed
        # explicitly (not left to GC) or it can still be open when this
        # block's engine.dispose() runs below -- exactly the leak that made
        # this test flaky on Windows (passed under Python 3.10 by GC timing
        # luck, failed under 3.11: PermissionError deleting the temp dir).
        with engine.connect() as conn:
            check(engine.dialect.has_table(conn, traces_table.name),
                  "traces table must exist after init_schema")

        # --- sink write + round-trip persistence + query by trace_id ---
        sink = make_sql_sink(engine)
        sink(ok_trace)
        sink(max_iter_trace)

        rows = list_traces(engine)
        check(len(rows) == 2, f"expected 2 persisted traces, got {len(rows)}")
        ids = {r["trace_id"] for r in rows}
        check(len(ids) == 2, "each persisted trace must get its own trace_id")

        ok_row = next(r for r in rows if r["termination"] == "success")
        max_row = next(r for r in rows if r["termination"] == "max_iterations")
        check(ok_row["payload"] == ok_trace, "round-tripped payload must equal what was written (success trace)")
        check(max_row["payload"] == max_iter_trace, "round-tripped payload must equal what was written (max_iterations trace)")

        fetched = get_trace(engine, ok_row["trace_id"])
        check(fetched == ok_trace, "get_trace(trace_id) must return the exact original payload")
        check(get_trace(engine, "not-a-real-id") is None, "get_trace on an unknown trace_id must return None, not raise")

        # --- list_traces filtering by termination ---
        only_success = list_traces(engine, termination="success")
        check(len(only_success) == 1 and only_success[0]["trace_id"] == ok_row["trace_id"],
              "list_traces(termination=...) must filter to matching rows only")

        # --- a trace with no 'response' span (e.g. bare Tracer use) persists with termination=None ---
        bare_trace = {"name": "router", "status": "ok", "duration_ms": 0.5, "attributes": {}, "error": None, "children": []}
        sink(bare_trace)
        none_rows = [r for r in list_traces(engine) if r["termination"] is None]
        check(len(none_rows) == 1 and none_rows[0]["payload"] == bare_trace,
              "a trace with no termination-bearing response span must still persist, with termination=None")

        # SQLite holds an open file handle via the engine's connection pool
        # on Windows; dispose before the TemporaryDirectory context tries
        # to remove the file, or cleanup raises PermissionError there.
        engine.dispose()

    # --- Integration: agent_api's real (non-overridden) exporter wiring persists via trace_store ---
    with tempfile.TemporaryDirectory() as tmp2:
        wiring_db = Path(tmp2) / "m6b_wiring.db"
        os.environ["KITTY_HAWK_TRACE_DB_URL"] = f"sqlite:///{wiring_db}"

        # Import agent_api only after the env var is set, so its default
        # engine URL (read at request time inside get_trace_exporter, not
        # at import time) picks up this test's temp database either way --
        # importing after setting it is just belt-and-suspenders here.
        import agent_api as api  # noqa: E402

        client_app = TestClient(api.app, raise_server_exceptions=False)
        api.app.dependency_overrides[api.get_rag_store] = _fresh_test_store
        # M6c added a real auth dependency to /agent/run; this suite
        # predates M6c and tests trace_store wiring, not auth, so bypass
        # it here. The real dependency is exercised for real in
        # tests/test_m6c_auth.py.
        api.app.dependency_overrides[api.verify_api_key] = lambda: None

        non_finalizing = json.dumps({"thought": "again", "action": al.ACTION_MANIFEST, "action_input": ""})
        api.app.dependency_overrides[api.get_client] = lambda: ScriptedFakeClient([non_finalizing] * al.MAX_ITERATIONS)
        resp = client_app.post("/agent/run", json={"goal": "never finish, m6b wiring check"})
        check(resp.status_code == 200, "max_iterations must still be HTTP 200 (M5 finding, unchanged by M6b)")

        # Export is fire-and-forget on a background thread; poll briefly
        # rather than assuming it has already landed.
        wiring_engine = create_engine(f"sqlite:///{wiring_db}")
        deadline = time.monotonic() + 2.0
        rows = []
        while time.monotonic() < deadline:
            init_schema(wiring_engine)
            rows = list_traces(wiring_engine)
            if rows:
                break
            time.sleep(0.05)
        check(len(rows) == 1, "agent_api's real exporter must persist the max_iterations trace via trace_store")
        check(rows[0]["termination"] == "max_iterations", "persisted row must carry the correct termination")

        api.app.dependency_overrides.clear()
        del os.environ["KITTY_HAWK_TRACE_DB_URL"]
        # Dispose both this test's verification engine and agent_api's own
        # lazily-cached engine (same underlying SQLite file) before the
        # TemporaryDirectory context tries to remove it -- same Windows
        # open-handle constraint as above.
        wiring_engine.dispose()
        api._trace_engine.dispose()
        api._trace_engine = None

    print(f"All {checks} M6b trace_store checks passed — schema creation, sink write, round-trip "
          f"persistence, and query-by-trace_id all verified against a real SQLAlchemy engine (SQLite); "
          f"agent_api's real exporter wiring confirmed to persist through trace_store with no code "
          f"change needed to target Postgres instead (KITTY_HAWK_TRACE_DB_URL).")


if __name__ == "__main__":
    main()
