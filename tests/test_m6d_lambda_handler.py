"""
test_m6d_lambda_handler.py — M6d: Lambda entry point, offline

Drives core/lambda_handler.handler with hand-built API Gateway HTTP API
(payload v2) events -- no AWS, no network, no credentials, no live
watsonx.ai call. Proves: the import is fail-closed without
KITTY_HAWK_LAMBDA_MODE=fake; the real bearer check still gates the route
(missing/wrong token -> 401, FakeClient never asked); the correct token
reaches the scripted FakeClient and returns HTTP 200 / success.

Not a Lambda execution: memory, CPU and cold start are unmeasured.
Skips (exit 0, says so) when mangum is not installed -- mangum is in
requirements-lambda.txt, not requirements.txt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN = "test-m6d-demo-token"

try:
    import mangum  # noqa: F401
except ImportError:
    print("SKIP: mangum not installed (see requirements-lambda.txt); M6d handler checks not run.")
    sys.exit(0)


def _event(body: dict, token: str | None) -> dict:
    headers = {"content-type": "application/json"}
    if token is not None:
        headers["x-kitty-hawk-token"] = token
    return _event_with_headers(body, headers)


def _event_with_headers(body: dict, headers: dict) -> dict:
    return {
        "version": "2.0",
        "routeKey": "POST /agent/run",
        "rawPath": "/agent/run",
        "rawQueryString": "",
        "headers": headers,
        "requestContext": {
            "accountId": "000000000000",
            "apiId": "test",
            "domainName": "test.execute-api.us-east-1.amazonaws.com",
            "http": {"method": "POST", "path": "/agent/run", "protocol": "HTTP/1.1",
                     "sourceIp": "127.0.0.1", "userAgent": "test"},
            "requestId": "test", "stage": "$default", "time": "01/Jan/2026:00:00:00 +0000",
            "timeEpoch": 0,
        },
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def main() -> None:
    checks = 0

    def check(v: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not v:
            raise AssertionError(label)

    # Fail-closed import: no mode set -> RuntimeError (run in a clean subprocess).
    env = {k: v for k, v in os.environ.items() if k != "KITTY_HAWK_LAMBDA_MODE"}
    env["PYTHONPATH"] = str(REPO_ROOT / "core")
    proc = subprocess.run(
        [sys.executable, "-c", "import lambda_handler"],
        env=env, capture_output=True, text=True, cwd=REPO_ROOT,
    )
    check(proc.returncode != 0 and "KITTY_HAWK_LAMBDA_MODE" in proc.stderr,
          "import without KITTY_HAWK_LAMBDA_MODE=fake must fail closed")

    # Deployed-style configuration.
    tmp = tempfile.mkdtemp(prefix="kh_m6d_")
    os.environ["KITTY_HAWK_LAMBDA_MODE"] = "fake"
    os.environ["KITTY_HAWK_API_KEY"] = TOKEN
    os.environ["KITTY_HAWK_TRACE_DB_URL"] = f"sqlite:///{Path(tmp, 'traces.db').as_posix()}"
    for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
        os.environ.pop(name, None)  # handler must import with none set (clean Lambda-like env)
    sys.path.insert(0, str(REPO_ROOT / "core"))
    sys.path.insert(0, str(REPO_ROOT))

    import lambda_handler as lh  # noqa: E402

    check(all(os.environ.get(n) == "lambda-fake-mode-placeholder"
              for n in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION")),
          "handler import must set inert placeholders, not read real WATSONX_* values")

    body = {"goal": "check the manifest"}

    r_none = lh.handler(_event(body, None), None)
    check(r_none["statusCode"] == 401, f"no token should be 401, got {r_none['statusCode']}")
    r_bad = lh.handler(_event(body, "wrong"), None)
    check(r_bad["statusCode"] == 401, f"wrong token should be 401, got {r_bad['statusCode']}")

    r_ok = lh.handler(_event(body, TOKEN), None)
    check(r_ok["statusCode"] == 200, f"correct token should be 200, got {r_ok['statusCode']}: {r_ok.get('body')}")
    parsed = json.loads(r_ok["body"])
    check(parsed["termination"] == "success", f"expected success, got {parsed['termination']}")
    check(parsed["answer"] == "m6d fake smoke ok", "scripted FakeClient answer not returned")

    # Second request: a fresh scripted client each time (stateful fake must not leak).
    r_ok2 = lh.handler(_event(body, TOKEN), None)
    check(r_ok2["statusCode"] == 200 and json.loads(r_ok2["body"])["termination"] == "success",
          "second request should also succeed")

    # Function URL (AWS_IAM) shape: Authorization carries a SigV4 signature, the bearer
    # token travels in X-Kitty-Hawk-Token.
    sigv4 = "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20260101/us-east-1/lambda/aws4_request, Signature=00"
    ok_hdr = {"content-type": "application/json", "authorization": sigv4, "x-kitty-hawk-token": TOKEN}
    r_url_ok = lh.handler(_event_with_headers(body, ok_hdr), None)
    check(r_url_ok["statusCode"] == 200, f"SigV4 Authorization + token header should be 200, got {r_url_ok['statusCode']}")
    no_tok = {"content-type": "application/json", "authorization": sigv4}
    r_url_no = lh.handler(_event_with_headers(body, no_tok), None)
    check(r_url_no["statusCode"] == 401, f"SigV4 Authorization alone must not pass the bearer check, got {r_url_no['statusCode']}")
    bad_tok = {"content-type": "application/json", "authorization": sigv4, "x-kitty-hawk-token": "wrong"}
    r_url_bad = lh.handler(_event_with_headers(body, bad_tok), None)
    check(r_url_bad["statusCode"] == 401, f"wrong token header should be 401, got {r_url_bad['statusCode']}")
    smuggle = {"content-type": "application/json", "authorization": f"Bearer {TOKEN}"}
    r_smuggle = lh.handler(_event_with_headers(body, smuggle), None)
    check(r_smuggle["statusCode"] == 401, "a Bearer token in Authorization alone must be discarded by the Function URL handler")

    print(f"All {checks} M6d lambda_handler checks passed.")


if __name__ == "__main__":
    main()
