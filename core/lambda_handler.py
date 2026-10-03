"""
lambda_handler.py — M6d: AWS Lambda entry point for the /agent/run boundary (smoke-test mode only)

Wraps the existing FastAPI app (agent_api.app) with Mangum so API Gateway
HTTP API (payload v2) events reach it. Governing plan: docs/M6D_PLAN_REV3.md.

Design, deliberately narrow:
    - Fake-only. The deployed smoke test uses a scripted FakeClient and the
      pinned test corpus. No watsonx.ai / Granite call is possible from this
      module: get_client is overridden at import time and there is no live
      mode. Granite credential design is deferred past M6d (plan decision 5).
    - Fail-closed on configuration. KITTY_HAWK_LAMBDA_MODE must be exactly
      "fake" or import raises, so a misconfigured function cannot silently
      fall through to the real WatsonXClient default.
    - The bearer check (auth.verify_api_key) is NOT overridden. A deployed
      function still rejects every request unless KITTY_HAWK_API_KEY is set
      and presented (plan decision 4). Because IAM (SigV4) and the bearer token
      cannot both use the Authorization header, the bearer token is sent in
      X-Kitty-Hawk-Token and mapped to Authorization by handler() below.
    - Placeholder WATSONX_* values (see below the mode check) exist only to
      satisfy watsonx_client's import-time check; they are not credentials.
    - Trace store: Lambda's package directory is read-only, so the default
      SQLite file under the repo root is unusable. Unless
      KITTY_HAWK_TRACE_DB_URL is already set, point it at /tmp. /tmp is
      ephemeral per execution environment; durable traces are NOT_YET_MODELED
      on Lambda.

NOT_YET_MODELED (explicit, M6d scope only):
    - Live Granite/watsonx.ai calls and their credentials.
    - Persistent Chroma, Postgres, or any non-/tmp trace backend.
    - Whether fire-and-forget trace export (AsyncTraceExporter) completes
      when Lambda freezes the environment after the response; unmeasured.
    - Behavior inside the real Lambda runtime (memory, CPU, cold start).
"""
from __future__ import annotations

import json
import os

if os.environ.get("KITTY_HAWK_LAMBDA_MODE") != "fake":
    raise RuntimeError(
        "KITTY_HAWK_LAMBDA_MODE must be 'fake'. M6d deploys the FakeClient smoke "
        "path only; there is no live mode."
    )

os.environ.setdefault("KITTY_HAWK_TRACE_DB_URL", "sqlite:////tmp/kitty_hawk_traces.db")

# watsonx_client exits the process at import if these four names are unset
# (found on a clean Linux run, 2026-10-03; on the Windows dev machine they were
# silently resolved from the User registry). The fake-only path never builds a
# WatsonXClient, so inert placeholders satisfy the import check without any
# real credential. A real value already in the environment is left alone, but
# the fake path does not use it either.
for _name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(_name, "lambda-fake-mode-placeholder")

from mangum import Mangum  # noqa: E402

import agent_api as api  # noqa: E402  (agent_api puts core/ and the repo root on sys.path)
import agent_loop as al  # noqa: E402
from rag.corpus import load_min_corpus_for_tests  # noqa: E402
from rag.store import RagStore  # noqa: E402


class _ScriptedFakeClient:
    """Deterministic two-step script: read the manifest, then finalize."""

    def __init__(self) -> None:
        self.system_prompt = ""
        self.current_agent = "FAKE"
        self.dispatch_id = None
        self.last_usage = None
        self.ask_calls: list[str] = []
        self._responses = [
            json.dumps({"thought": "check manifest", "action": al.ACTION_MANIFEST, "action_input": ""}),
            json.dumps({"thought": "done", "action": al.ACTION_FINAL, "action_input": "m6d fake smoke ok"}),
        ]

    def set_agent(self, name: str) -> None:
        self.current_agent = name

    def ask(self, prompt: str, **kwargs) -> str:
        self.ask_calls.append(prompt)
        # Past the script, keep finalizing so a longer loop cannot index out of range.
        return self._responses[min(len(self.ask_calls) - 1, len(self._responses) - 1)]


def _fresh_store() -> RagStore:
    store = RagStore(persist_path=None)
    store.add_documents(load_min_corpus_for_tests())
    return store


# A new fake per request: the scripted client is stateful.
api.app.dependency_overrides[api.get_client] = lambda: _ScriptedFakeClient()
api.app.dependency_overrides[api.get_rag_store] = _fresh_store

_mangum = Mangum(api.app, lifespan="off")

# Carrying both IAM and bearer credentials: a Lambda Function URL with AWS_IAM auth
# requires the SigV4 signature in the Authorization header, which is the header
# auth.verify_api_key reads. Lambda verifies the signature BEFORE this code runs, so
# the original Authorization value is no longer needed here. The bearer token travels
# in X-Kitty-Hawk-Token instead and is mapped into Authorization: Bearer <token>.
# Fail-closed: whatever Authorization value arrived is always discarded; if the custom
# header is absent there is no Authorization at all, so the bearer check rejects (401).
BEARER_HEADER = "x-kitty-hawk-token"


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    headers.pop("authorization", None)
    token = headers.pop(BEARER_HEADER, None)
    if token:
        headers["authorization"] = f"Bearer {token}"
    event = {**event, "headers": headers}
    return _mangum(event, context)
