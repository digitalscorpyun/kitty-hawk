# Kitty Hawk Evidence

This document records what has actually been observed for Kitty Hawk, and — just as
importantly — what has not. It is written for a reader with no access to any private
system. Every claim below is either independently reproducible from this repository
or explicitly marked historical.

## Public Offline Reproducer

The offline demo (`demo/kitty_hawk_offline_demo.py`) is the primary, publicly
reproducible signal. It exercises:

- **Valid path** — packet `CASE-KITTY-HAWK-DEMO-001` (2 synthetic receipts,
  `RCPT-SAN-001`/`RCPT-SAN-002`, grouped into 1 event via an explicit `event_id`) runs
  the full 4-seat chain (`ECHO-PROPHET → CONTEXTUAL-CATALYST → CG-SCRIBE → OD-COMPLY`)
  to `execution_complete`, with the human-review boundary hard-asserted in the output
  report (`Human review required`, `NOT operator acceptance`).
- **Negative paths** — a hash-mismatch receipt and a malformed packet (missing
  `case_id`, invalid `severity`) both halt before any seat runs
  (`halted_invalid_evidence_packet`, 0 stages). All 4 injected `FakeClient`s assert
  `ask_calls == []` and `set_agent_calls == []` for these cases — the mission engine
  provably makes no provider call when the input packet doesn't validate.
- **Legacy path** — a pre-receipt-schema packet (`[{source, content}]` pairs) is
  accepted for backward compatibility and returns `execution_complete_with_gate_findings`
  rather than being rejected.
- **Semantic determinism** — the valid packet is run twice with fresh `FakeClient`
  instances. Status, gate findings, schema validity, response text, review/authorization
  state, and per-stage semantic fields are asserted identical across both runs.
  Byte-for-byte determinism is **not** claimed: timestamps and per-dispatch UUIDs are
  intentionally non-deterministic and are excluded from the comparison.

The demo uses `FakeClient` throughout (`authorize_live=False`). It makes zero external
inference-service calls, and therefore performs zero Granite inference. It reads no
credentials and writes nothing outside a local, gitignored `_debug/` directory.

## LIVE-003 Historical Evidence

`CASE-KITTY-HAWK-LIVE-003` (2026-08-27) is a single bounded historical execution of the
same mission engine against the live IBM watsonx.ai service, kept separate from the
public offline reproducer.

- **Chain observed:** `AVM seat → WatsonXClient → IBM watsonx.ai → ibm/granite-4-h-small → response`
- `WatsonXClient` is the adapter/client in this repository; IBM watsonx.ai is the
  external inference service/runtime it calls; `ibm/granite-4-h-small` is the exact
  model ID that answered every seat in this run.
- 4 of 4 seats executed (`ECHO-PROPHET`, `CONTEXTUAL-CATALYST`, `CG-SCRIBE`,
  `OD-COMPLY`), each issuing exactly one provider request (0 retries), for 4 total
  provider requests and 3,526 tokens, in ~27 seconds wall-clock.
- TLS certificate verification was enabled for the watsonx.ai connection throughout
  (`verify=True`, no fallback provider).
- The run recorded `execution_complete_with_gate_findings`: one deterministic gate
  (an "unsupported number" check) flagged a false positive on the phrase "24-hour
  window," and one deterministic schema check failed because a downstream seat used
  markdown bold instead of the required literal heading text. Neither is a transport
  or authentication failure — both are the mission engine's own gates doing exactly
  what they're designed to do: catch a discrepancy and keep it visible rather than
  silently pass it through.
- `vs_enc_review_status: not_reviewed`, `operator_authorization_status: not_authorized`,
  `vault_writeback: null` on every record this mission produced — no output from this
  run has been accepted by anyone, and none was written to any external store.

Full evidence artifacts for this run: `examples/CASE-KITTY-HAWK-LIVE-003.json` and
`examples/CASE-KITTY-HAWK-LIVE-003.md`.

## What LIVE-003 Does Not Establish

LIVE-003 is one bounded, synthetic-data execution. It is historical evidence only. It
does **not** establish:

- production readiness;
- authorization to use any Granite model beyond the exact ID recorded above — no
  family-wide Granite authorization is implied or granted;
- Customer Success acceptance;
- operator or VS-ENC acceptance of the mission's output;
- current, standing, or repeatable live-execution capability (this public repository
  ships no credentials and cannot make a live call);
- hosted CI execution of any kind — see Validation State below.

## Validation State

- **Local Linux (previously recorded):** the offline demo and both offline test suites
  were observed passing on Linux prior to this evidence pass.

- **2026-08-28 — local native Windows execution — OBSERVED:**
  - Offline demo (`demo/kitty_hawk_offline_demo.py`): **VALID CASE PASS**,
    **NEGATIVE CASE PASS**, **semantic determinism PASS**.
  - `tests/test_mission_citation_fabrication.py`: **269 checks PASS**, with 2 expected
    skips (historic SYLLO records not present in this public clean clone — this is the
    correct public-fixture-set count, not the larger historical internal Forge count
    described above, which this repository does not treat as equivalent).
  - `tests/test_watsonx_client.py`: **17/17 PASS** when `ibm-watsonx-ai` is installed;
    **18/18 PASS** in a clean venv where it's absent. The `initialize_sdk` offline-
    construction seam (commit `f1b5933`) added 4 checks over the prior 14; one of the
    4 (the default-construction-raises-`WatsonXSDKUnavailableError` check) only runs
    when the SDK is genuinely absent, hence 17 vs. 18.
  - This run exercised the real Windows `winreg` code path natively, rather than the
    `sys.platform="win32"` simulation used in the prior Linux-only validation.

- **GitHub-hosted `ubuntu-latest`:** configured in
  `.github/workflows/kitty-hawk-offline.yml`, but **NOT YET OBSERVED**.
- **GitHub-hosted `windows-latest`:** configured in the same workflow, but **NOT YET
  OBSERVED**.

Local native Windows execution and GitHub-hosted Windows execution are not the same
claim — the former is now OBSERVED; the latter remains unobserved until a workflow
run has actually executed on GitHub's own runners. Configured CI is not executed CI.
