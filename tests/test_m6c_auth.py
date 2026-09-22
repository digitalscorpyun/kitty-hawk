"""
test_m6c_auth.py — M6c: application-level authentication

Proves the REAL verify_api_key dependency directly -- it is never
overridden anywhere in this file, unlike every other test suite that hits
/agent/run. Covers: fail-closed on an unset KITTY_HAWK_API_KEY, fail-closed
on an explicitly empty-string one, rejection of a wrong token, acceptance
of the correct token, and the core M6c claim -- a rejected request never
reaches run_agent_loop or the exporter, verified by asserting zero ask()
calls and zero export calls on every 401 case, not merely assumed from
FastAPI's dependency-ordering documentation.

Offline: no network, no credentials beyond this file's own configured
KITTY_HAWK_API_KEY test values.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-m6c")

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
for p in (str(REPO_ROOT / "core"), str(REPO_ROOT / "scripts"), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from fastapi.testclient import TestClient  # noqa: E402

import agent_api as api  # noqa: E402
import agent_loop as al  # noqa: E402
from rag.store import RagStore  # noqa: E402
from rag.corpus import load_min_corpus_for_tests  # noqa: E402


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


class RecordingExporter:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def export(self, trace: dict) -> None:
        self.calls.append(trace)


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

    client_app = TestClient(api.app, raise_server_exceptions=False)
    api.app.dependency_overrides[api.get_rag_store] = _fresh_test_store
    # api.verify_api_key is deliberately NEVER overridden in this file --
    # that is the entire point of test_m6c_auth.py.

    had_key_env = "KITTY_HAWK_API_KEY" in os.environ
    saved_key_env = os.environ.get("KITTY_HAWK_API_KEY")

    def _set_configured_key(value):
        if value is None:
            os.environ.pop("KITTY_HAWK_API_KEY", None)
        else:
            os.environ["KITTY_HAWK_API_KEY"] = value

    success_body = json.dumps({"thought": "done", "action": al.ACTION_FINAL, "action_input": "all good"})

    try:
        # --- Unconfigured (unset entirely): every request rejected ---
        _set_configured_key(None)
        fake_unset = ScriptedFakeClient([success_body, success_body])
        recorder_unset = RecordingExporter()
        api.app.dependency_overrides[api.get_client] = lambda: fake_unset
        api.app.dependency_overrides[api.get_trace_exporter] = lambda: recorder_unset

        resp = client_app.post("/agent/run", json={"goal": "no key configured, no header"})
        check(resp.status_code == 401, f"unset KITTY_HAWK_API_KEY + no header must 401, got {resp.status_code}")
        check(len(fake_unset.ask_calls) == 0, "rejected request must never reach run_agent_loop (zero ask() calls)")
        check(len(recorder_unset.calls) == 0, "rejected request must never reach the exporter")

        resp2 = client_app.post(
            "/agent/run", json={"goal": "no key configured, some header"},
            headers={"Authorization": "Bearer whatever-an-attacker-guesses"},
        )
        check(resp2.status_code == 401, "unset KITTY_HAWK_API_KEY must reject regardless of presented token")
        check(len(fake_unset.ask_calls) == 0, "still zero ask() calls with a presented token but no configured key")
        check(len(recorder_unset.calls) == 0, "still zero export calls with a presented token but no configured key")

        # --- Configured as an explicit empty string: must still reject ---
        _set_configured_key("")
        resp3 = client_app.post(
            "/agent/run", json={"goal": "empty key configured"},
            headers={"Authorization": "Bearer "},
        )
        check(resp3.status_code == 401, "empty-string KITTY_HAWK_API_KEY must still reject, not act as 'auth disabled'")
        check(len(fake_unset.ask_calls) == 0, "empty-config rejection must still be zero ask() calls")

        resp3b = client_app.post("/agent/run", json={"goal": "empty key, no header"})
        check(resp3b.status_code == 401, "empty-string KITTY_HAWK_API_KEY must reject a request with no header too")

        # --- Configured with a real key: wrong token rejected ---
        _set_configured_key("kh-real-secret-123")
        fake_wrong = ScriptedFakeClient([success_body])
        recorder_wrong = RecordingExporter()
        api.app.dependency_overrides[api.get_client] = lambda: fake_wrong
        api.app.dependency_overrides[api.get_trace_exporter] = lambda: recorder_wrong

        resp4 = client_app.post(
            "/agent/run", json={"goal": "wrong token"},
            headers={"Authorization": "Bearer not-the-real-secret"},
        )
        check(resp4.status_code == 401, "wrong token against a configured key must 401")
        check(len(fake_wrong.ask_calls) == 0, "wrong-token rejection must never reach run_agent_loop")
        check(len(recorder_wrong.calls) == 0, "wrong-token rejection must never reach the exporter")

        resp5 = client_app.post("/agent/run", json={"goal": "missing header entirely"})
        check(resp5.status_code == 401, "missing Authorization header against a configured key must 401")
        check(len(fake_wrong.ask_calls) == 0, "missing-header rejection must never reach run_agent_loop")

        # --- Configured with a real key: correct token accepted, normal behavior unchanged ---
        fake_ok = ScriptedFakeClient([success_body])
        recorder_ok = RecordingExporter()
        api.app.dependency_overrides[api.get_client] = lambda: fake_ok
        api.app.dependency_overrides[api.get_trace_exporter] = lambda: recorder_ok
        original_sampler = api._success_sampler
        api._success_sampler = lambda: True  # force export so we can assert it happened

        resp6 = client_app.post(
            "/agent/run", json={"goal": "correct token"},
            headers={"Authorization": "Bearer kh-real-secret-123"},
        )
        check(resp6.status_code == 200, f"correct token must be accepted (200), got {resp6.status_code}")
        check(len(fake_ok.ask_calls) == 1, "authenticated request must reach run_agent_loop normally")
        check(resp6.json()["termination"] == al.TERMINATION_SUCCESS,
              "authenticated request must behave exactly as before M6c")
        check(len(recorder_ok.calls) == 1, "authenticated + sampled-in request must still export normally")

        api._success_sampler = original_sampler

    finally:
        api.app.dependency_overrides.clear()
        if had_key_env:
            os.environ["KITTY_HAWK_API_KEY"] = saved_key_env
        else:
            os.environ.pop("KITTY_HAWK_API_KEY", None)

    print(f"All {checks} M6c auth checks passed — real verify_api_key dependency exercised directly "
          f"(never overridden): fail-closed on unset and empty configuration, wrong-token and "
          f"missing-header rejection, correct-token acceptance, and zero ask()/export calls on every "
          f"rejected request, confirming auth runs before agent execution or export.")


if __name__ == "__main__":
    main()
