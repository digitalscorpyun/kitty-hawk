"""
auth.py — M6c: application-level authentication for the FastAPI boundary

Governing spine: ibm_watsonx_cohesive_trajectory_gameplan.md, M6.0 decision
record and M6c.

Concept: agent_api.py's own docstring has named this gap since M5 -- "No
auth/rate-limiting on this endpoint ... not a hardened public API." M6c
answers the auth half of that: who is allowed to call /agent/run, and what
happens to a request that isn't.

Design, deliberately narrow:
    - A single shared bearer token (KITTY_HAWK_API_KEY), not per-caller
      credentials, not roles/scopes -- this endpoint has exactly one
      capability to gate (call it or don't), so a binary
      allowed/not-allowed check is the whole of what M6c needs.
    - Fail-closed by construction: an unset OR empty-string
      KITTY_HAWK_API_KEY does not mean "auth disabled." No presented
      token can ever satisfy the comparison in that state, so every
      request is rejected. There is no "if unconfigured, skip the check"
      branch that could accidentally leave the endpoint open.
    - Constant-time comparison (hmac.compare_digest) so a timing side
      channel can't be used to guess the configured token byte-by-byte.
      compare_digest is always invoked, even when unconfigured, so the
      unconfigured case doesn't short-circuit into a different timing
      shape than a configured-but-wrong-token case.
    - Rejection happens as a FastAPI route dependency
      (dependencies=[Depends(verify_api_key)] on the route), which
      FastAPI resolves before the route body runs -- a rejected request
      never constructs a Tracer, never calls run_agent_loop, and never
      reaches the exporter. tests/test_m6c_auth.py verifies this directly
      (zero ask() calls, zero export calls on every 401) rather than
      assuming FastAPI's dependency-ordering guarantee holds.

NOT_YET_MODELED (explicit, M6c scope only):
    - Rate-limiting -- named in agent_api.py's own NOT_YET_MODELED since
      M5, not scheduled to a specific milestone.
    - Authorization/roles/scopes -- one endpoint, one capability; nothing
      to differentiate yet.
    - The AWS API Gateway auth mechanism -- M6.0's own explicitly open
      item, deferred to M6d, not decided here.
    - Key rotation or secrets-manager integration -- KITTY_HAWK_API_KEY is
      a plain environment variable, nothing more.
    - Multiple or per-caller credentials -- one shared token only.
"""
from __future__ import annotations

import hmac
import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer_scheme = HTTPBearer(auto_error=False)


def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency: raises 401 unless the presented bearer token
    matches KITTY_HAWK_API_KEY exactly, compared in constant time. An
    unset or empty KITTY_HAWK_API_KEY always rejects -- fail-closed, never
    treated as "no credential required." Returns None; the route uses
    dependencies=[Depends(verify_api_key)] to gate access without needing
    this dependency's value."""
    configured = os.environ.get("KITTY_HAWK_API_KEY", "")
    presented = credentials.credentials if credentials is not None else ""

    # Always run compare_digest, even when unconfigured, so this branch's
    # timing shape doesn't differ from the configured-but-wrong-token case.
    token_matches = hmac.compare_digest(configured, presented)
    if not configured or not token_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API credential.",
            headers={"WWW-Authenticate": "Bearer"},
        )
