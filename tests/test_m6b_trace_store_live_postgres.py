"""
test_m6b_trace_store_live_postgres.py — M6b: dialect-specific Postgres
verification (LIVE-GATED, NOT part of default CI)

test_m6b_trace_store.py proves the shared persistence mechanics (schema
creation, sink write, round-trip, query-by-trace_id) against SQLite, which
runs identically on ubuntu-latest and windows-latest. This file proves the
same code path against a real Postgres server -- confidence that nothing
in trace_store.py's SQL is SQLite-specific.

This is intentionally NOT wired into .github/workflows/kitty-hawk-offline.yml:
GitHub Actions service containers do not run on the windows-latest leg of
that matrix, and this project holds both offline-CI and no-external-
dependency discipline (see trace_export.py, trace_store.py). Provisioning
a Postgres server is left to whoever runs this file locally -- no AWS
resource is chosen, provisioned, or billed by this test or by M6b at all
(the M6.0 RDS question stays open, deferred to M6d).

To run against a local Postgres (e.g. `docker run -e POSTGRES_PASSWORD=x
-p 5432:5432 postgres`):

    set KITTY_HAWK_LIVE_POSTGRES_URL=postgresql+psycopg2://postgres:x@localhost:5432/postgres
    python tests/test_m6b_trace_store_live_postgres.py

Requires the `psycopg2-binary` (or equivalent) driver from requirements.txt.
Without the env var set, this prints a skip message and exits 0 -- it is
not a failure, just an unrun, opt-in check (same posture as this project's
other live-gated verification).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(REPO_ROOT / "core"),):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> None:
    live_url = os.environ.get("KITTY_HAWK_LIVE_POSTGRES_URL")
    if not live_url:
        print("SKIPPED — KITTY_HAWK_LIVE_POSTGRES_URL not set. This live-gated Postgres "
              "check is opt-in and not part of default CI (see module docstring). "
              "Set the env var to a real local Postgres URL to run it.")
        return

    from sqlalchemy import create_engine
    from trace_store import get_trace, init_schema, list_traces, make_sql_sink

    checks = 0

    def check(v: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not v:
            raise AssertionError(label)

    engine = create_engine(live_url)
    init_schema(engine)
    sink = make_sql_sink(engine)

    marker = str(uuid.uuid4())
    trace = {
        "name": "router", "status": "ok", "duration_ms": 1.0,
        "attributes": {"goal": f"live-postgres-check-{marker}"}, "error": None,
        "children": [
            {"name": "response", "status": "ok", "duration_ms": 0.1,
             "attributes": {"termination": "success"}, "error": None, "children": []},
        ],
    }
    sink(trace)

    rows = [r for r in list_traces(engine, termination="success")
            if r["payload"]["attributes"]["goal"] == f"live-postgres-check-{marker}"]
    check(len(rows) == 1, "sink write against real Postgres must be queryable via list_traces")
    fetched = get_trace(engine, rows[0]["trace_id"])
    check(fetched == trace, "get_trace against real Postgres must round-trip the exact payload")

    print(f"All {checks} live-Postgres checks passed against {live_url.split('@')[-1]} "
          f"-- trace_store's SQLAlchemy code path confirmed dialect-correct on real Postgres, "
          f"not just SQLite.")


if __name__ == "__main__":
    main()
