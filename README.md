# Kitty Hawk — Governed Agentic Reliability Workflow

**Portfolio project by digitalscorpyun (Michael Kibbe) — AVM Syndicate, 2026**
**Status:** Offline reproducer ready (live bounded validation 003 passed, portfolio-ready)

> Kitty Hawk is a governed 4-seat agentic workflow for AI citation-integrity incidents — when an AI research system fabricates a citation like *Acme v. Beta, 123 F.4th 456 (9th Cir. 2024)*. It intake-validates versioned evidence packets, verifies `content_sha256` receipt lineage (2 receipts → 1 event via explicit `event_id`), runs deterministic reliability gates (citation / scenario-fidelity / unsupported-number), and halts invalid packets **before any provider call** (`halted_invalid_evidence_packet`, `ask_calls == []`). Every report is `vault_writeback: null`, `not_reviewed / not_authorized`, with explicit human-review escalation. Built for IBM watsonx.ai with IBM Granite (TLS verified for the watsonx.ai service connection, no fallback, `authorize_live=False` with `FakeClient` offline — offline demo makes zero external inference-service calls and therefore no Granite inference), verified by 269 mission + 17–18 watsonx.ai-service offline checks (public clean-clone counts; see `docs/EVIDENCE.md` for the historical-vs-public distinction), semantic determinism scoped. One command reproduces. Live transport to the watsonx.ai service (KH-03 `SSL: UNEXPECTED_EOF` during watsonx.ai request) and 6 controls remain `NOT_YET_MODELED` by design — documented limits, not hidden debt.

## One-Command Reproducer (no credentials, no live watsonx.ai inference)

```bash
# From repo root — requires Python 3.10+ and pytz (see requirements.txt)
# Windows: chcp 65001 > /dev/null  (UTF-8 console for ✶)
PYTHONUTF8=1 python -X utf8 demo/kitty_hawk_offline_demo.py
# Expected: VALID CASE: PASS, NEGATIVE CASE: PASS, Determinism: semantic PASS
```

Or with conda env `wx310` (as used in Forge, internal path redacted):
```bash
chcp 65001 > /dev/null
PYTHONUTF8=1 python -X utf8 demo/kitty_hawk_offline_demo.py
# Forge verified with Python 3.10.19 (wx310, internal path redacted)
```

What it does:
- **Valid:** `CASE-KITTY-HAWK-DEMO-001` (2 synthetic receipts `RCPT-SAN-001/002` → 1 event `EVT-SAN-CITATION-001`) → normalization → 4-seat chain `ECHO-PROPHET → CONTEXTUAL-CATALYST → CG-SCRIBE → OD-COMPLY` via `FakeClient` → `execution_complete`, human-review boundary asserted
- **Negative:** hash-mismatch `RCPT-SAN-NEG-001` (`00…0`) and malformed packet → `halted_invalid_evidence_packet`, 0 stages, **zero provider calls** (`ask_calls == []` for all 4 seats)
- **Legacy:** `legacy-list` `[ {source,content}×2 ]` → `execution_complete_with_gate_findings` preserved

## Tests (offline)

```bash
PYTHONUTF8=1 python -X utf8 tests/test_mission_citation_fabrication.py
# All 269 mission_citation_fabrication checks passed. (2 skipped: historic SYLLO records, expected on a clean clone)

PYTHONUTF8=1 python -X utf8 tests/test_watsonx_client.py
# All 17 watsonx_client checks passed (18 in a clean venv where ibm-watsonx-ai is absent --
# one extra check exercises the initialize_sdk=True fail-closed path, which only
# applies when the SDK is genuinely absent).
```

No live watsonx.ai inference-service call (and therefore no Granite inference), no `.env`, no `verify=False`, no fallback.

## Extending the Reliability Pattern — M1–M5 (Agentic Systems Trajectory)

A second, newer track in this repository extends the same evidence-first
discipline from the citation-reliability workflow above into a general
agentic-systems build sequence: **M1 provider boundary → M2 evaluation
baseline → M3 retrieval/context construction → M4 bounded agent/tool loop →
M5 FastAPI+observability → M6 production/deployment.** M1–M5 are built;
M6 is not started.

### Learn M4 before running it

M4 answers one precise engineering question: **when an agent is allowed to
choose its next step, what stops that choice from becoming unbounded or
unauthorized execution?** It does not make a model correct, and it does not
make a tool safe by name alone. It gives a small loop explicit stopping and
scope rules.

Follow one request through the loop:

1. **Observe:** the loop receives a goal and the accumulated result of any
   earlier allowed tool call.
2. **Reason:** the model returns structured JSON naming its next action.
3. **Act only after validation:** the loop accepts only `read_kitty_hawk_manifest`,
   `retrieve_context`, or `final_answer`. Any other proposed action terminates
   the run before it executes.
4. **Observe again or stop:** each completed step becomes part of the trajectory;
   the loop stops on a final answer, a timeout, the iteration cap, or a
   disallowed action.

The three controls answer different questions:

| Control | Question it answers | What the test demonstrates |
| --- | --- | --- |
| Iteration cap | Has the loop kept asking for another step without finishing? | A scripted agent is stopped after exactly three calls. |
| Wall-clock timeout | Has the whole run taken longer than its permitted time, even if a call finally returns an answer? | A deliberately slow client terminates as `timeout`; its late answer is rejected. |
| Tool allowlist | Is this particular action authorized at all? | An unknown action terminates as `disallowed_action` before execution. |

#### Boundary with the 3.2M-token incident

The earlier incident was not merely “a loop without brakes.” Its documented
failure chain was: an authoritative syllabus path existed → a child lost that
path → it launched `find /` → 594 seconds elapsed → no useful artifact.
M4 would refuse `find /` **only if it were proposed as a non-allowlisted M4
action**. M4 does not model a generic shell tool, authority-path inheritance,
child-process containment, or a token/cost budget. Those omissions matter.

M4 therefore teaches bounded autonomy at the tool-selection level. M5 is the
milestone intended to make the authority-path failure legible through a trace;
cost/token monitoring belongs to the later observability/production work. The
tests establish the three M4 controls above, not a claim that M4 would have
prevented the complete earlier incident.

```bash
PYTHONUTF8=1 python -X utf8 tests/test_watsonx_ping.py
# All 17 watsonx_ping M1 checks passed — ONE PING ONLY (valid JSON, no
# hallucination, exactly one ask() call). Offline: FakeClient, no credentials.

PYTHONUTF8=1 python -X utf8 tests/test_m2_evaluation.py
# All 34 M2 evaluation checks passed — baseline trace + HTTP-success-vs-
# cognitive-success distinction + one-ping trace condition.

PYTHONUTF8=1 python -X utf8 tests/test_m3_rag.py
# All 28 M3 RAG checks passed — Document->Chunk->Embed->Index->Retrieve->
# Context against a real local Chroma collection, citation-bearing results,
# and an explicit retrieval-failure case. Requires chromadb (requirements.txt).

PYTHONUTF8=1 python -X utf8 tests/test_m4_agent_loop.py
# All 20 M4 agent-loop checks passed — bounded ReAct loop verified (success,
# max_iterations, disallowed_action fail-closed, timeout, grounded retrieval).

PYTHONUTF8=1 python -X utf8 tests/test_m5_api.py
# All 20 M5 API checks passed — HTTP 200 on bounded non-success termination,
# trace exposes internal state a status code cannot, genuine crash still 5xx.
```

- **M1 (`scripts/watsonx_ping.py`):** a single structured Granite call behind
  the same `set_agent`/`ask` seam as the citation workflow above, with one
  bounded, allowlisted tool the model may or may not invoke. Offline test
  proves valid-JSON, no-hallucination, and exactly-one-call behavior; no
  network or credentials required to verify it.
- **M2 (`evals/m1_evaluation.py`):** an evaluation baseline defined *before*
  additional complexity was added — exact/schema checks, a latency threshold,
  and an explicit rule that HTTP success does not imply cognitive success.
- **M3 (`rag/`):** a real local Chroma-backed retrieval pipeline (`store.py`)
  over a small controlled corpus, with citation-bearing context construction
  and a demonstrated retrieval-failure case for an out-of-domain query. A
  deterministic, dependency-free scaffold (`store_deterministic.py`) is
  preserved for teaching reference but is not the M3 artifact. The corpus
  loader ships with **no personal filesystem paths** — its two optional
  private sources resolve only from `KITTY_HAWK_VAULT_SYLLABUS` /
  `KITTY_HAWK_VAULT_GAMEPLAN` environment variables, unset on every clone but
  the author's own, and fall back to synthetic stubs that preserve the exact
  retrieval contract (this is the path CI and any other clone actually runs).
- **M4 (`core/agent_loop.py`):** wraps M1's bounded manifest tool and M3's
  retrieval pipeline into a single `Observe -> Reason -> Act -> Observe`
  loop with three independent bounds — a 3-iteration cap, a wall-clock
  timeout, and a fixed tool allowlist (`read_kitty_hawk_manifest`,
  `retrieve_context`, `final_answer`) — so a reasoning loop cannot become an
  uncontrolled execution loop. Every run reports one of four explicit
  termination states (`success`, `max_iterations`, `timeout`,
  `disallowed_action`); an unknown action fails closed on the same step it
  was proposed, without executing anything. Offline tests exercise all four
  termination paths directly, including a scripted slow client to prove the
  timeout bound actually trips rather than only existing in theory.
  **Evidence and limits, per this project's own evaluation discipline (Eden;
  see `avm/dev_notes/project_eden_roadmap.md` in the Forge):** tested —
  bounded termination in all four states, fail-closed on a disallowed
  action, grounded (non-hallucinated) tool observations for both real
  tools, offline-deterministic via `ScriptedFakeClient`. NOT_YET_MODELED —
  no cost/token-budget termination condition (reserved for M5/M6
  observability work), no mid-loop human-in-the-loop interrupt, no
  cross-run trajectory persistence, no multi-agent handoff (this is one
  reasoning loop, not the 4-seat pipeline above). Not self-certified beyond
  what these offline checks actually exercise; no live watsonx.ai call was
  made to build or verify M4.
- **M5 (`core/agent_api.py`, `core/trace.py`):** exposes the M4 loop over
  HTTP (FastAPI) and answers the milestone's precise question — when a
  request returns `200 OK`, does that mean the reasoning inside actually
  succeeded? No. A `max_iterations` or `disallowed_action` termination
  still returns `200` with an informative body; only a genuine crash (e.g.
  an empty goal) produces a real `5xx`. `trace.py` is a small homegrown
  span/tree tracer — built by hand before comparing to MLflow's own
  `mlflow.trace`/autolog pattern, per this milestone's own instruction, not
  a wrapper around the MLflow library. Every request returns its full
  execution tree (`router → agent_iteration → model_call/validate_step/
  tool:<name> → response`) alongside the result, so a disallowed action's
  `validate_step` span shows `status: "error"` with the rejected action
  named, even though the HTTP layer reports success throughout.
  **Evidence and limits (Eden discipline, as above):** tested — HTTP 200
  on all three bounded non-crash terminations (success, max_iterations,
  disallowed_action), HTTP 500 on a genuine crash, full trace tree shape
  verified per termination type, error status correctly recorded on a
  rejected action's span. NOT_YET_MODELED — no real MLflow integration
  (homegrown tracer only, by design at this stage), no auth/rate-limiting,
  synchronous endpoint only (no async/concurrency tracing — M6 territory),
  no trace persistence across requests. No live watsonx.ai call was made
  to build or verify M5.

No live watsonx.ai call anywhere in M1–M5's test paths.

## Architecture

```
Evidence packet (1.0 + receipts with content_sha256)
  → _validate (hash, schema, case_id, severity, version)
  → receipt/event lineage (explicit event_id only)
  → run_mission(clients=FakeClient/WatsonXClient [watsonx.ai service client], authorize_live)  # WatsonXClient -> watsonx.ai -> Granite model
    → ECHO-PROPHET → [citation + scenario-fidelity gates]
    → CONTEXTUAL-CATALYST → [unsupported-number + scenario-fidelity gates]
    → CG-SCRIBE → OD-COMPLY
  → Customer Success report (_debug/mission_citation_fabrication/*.json/.md)
     receipt ledger, per-seat traces, gate findings, Human review required
```

**External inference boundary (operator ruling 2026-08-23):** IBM watsonx.ai is the authorized external inference service/runtime; IBM Granite is the model family used for the recorded LIVE-003 inference (`ibm/granite-4-h-small`). `syndicate_router.SEAT_PROVIDER` maps all 4 seats to `WatsonXClient` (client for the watsonx.ai service); seats are governed identities distinguished by manifest, not vendor bindings. `FakeClient` in offline demo uses identical seam (`set_agent`, `ask`) with no network and therefore no Granite inference.

## Project Structure

```
kitty-hawk/
├── demo/kitty_hawk_offline_demo.py   # canonical reproducer (21K, offline)
├── core/                             # engine + router + watsonx bridge
│   ├── mission_citation_fabrication.py
│   ├── syndicate_router.py
│   ├── provider_protocol.py
│   ├── watsonx_client.py
│   ├── agent_loop.py                   # M4 bounded Observe->Reason->Act->Observe loop
│   ├── trace.py                        # M5 homegrown span/trace tree (built before MLflow)
│   └── agent_api.py                    # M5 FastAPI boundary over the M4 loop
├── scripts/
│   ├── watsonx_ping.py                # M1 provider-boundary single-call script
│   └── public_boundary_scan.py        # CI check: no personal paths anywhere in-tree
├── evals/
│   └── m1_evaluation.py               # M2 evaluation baseline
├── rag/
│   ├── corpus.py                      # M3 controlled corpus (no personal paths)
│   ├── store.py                       # M3 required artifact: real local Chroma store
│   └── store_deterministic.py         # teaching-reference scaffold, not the M3 artifact
├── tests/                            # 269+17/18 (citation/watsonx) + 17+34+28+20+20 (M1-M5) offline checks
├── docs/
│   └── EVIDENCE.md                   # observed vs not-yet-observed, historical vs public
├── examples/                         # pre-generated reports (JSON + MD)
│   ├── KITTY-HAWK-DEMO-VALID-001.json/.md
│   └── CASE-KITTY-HAWK-LIVE-003.json/.md
└── requirements.txt
```

## Glossary

A few terms appear in the evidence output (`examples/*.md`, `examples/*.json`) that
come from this project's human-governance schema, not from the code's runtime
behavior:

- **`VS-ENC`** — a human-governed review/acceptance role in the workflow this project
  demonstrates. It is not an autonomous agent and does not act on its own; every
  record explicitly marks itself `not_reviewed` until a human performs that review.
- **`Customer Success`** — a downstream acceptance state represented in the evidence
  schema (the report format the mission engine writes). Its presence in a report is
  not proof that any customer has approved that run.
- **`acceptance` / `authorization`** — explicit human-governance states, distinct from
  technical execution. A mission reaching `execution_complete` means its stages ran;
  it does not mean a human has accepted or authorized the result.

## Live Bounded Validation — Historical Evidence Only

Bounded live validation (CASE-KITTY-HAWK-LIVE-003) was executed in the internal Forge with synthetic data only (TLS verified, ≤4 requests, ≤120s, no Vault writeback). No live call is required for portfolio evaluation — the offline reproducer is the primary signal.

> **Disclaimer:** LIVE-003 is bounded-execution evidence only; not VS-ENC acceptance, not operator authorization, not Customer Success acceptance, not public-release readiness. See `docs/EVIDENCE.md`.

Outcome (2026-08-27): **PASSED — BOUNDED** — 4/4 seats invoked Granite `ibm/granite-4-h-small` through IBM watsonx.ai, 27s, 3,526 tokens, TLS verified for the watsonx.ai service connection. Evidence in `docs/EVIDENCE.md` and `examples/CASE-KITTY-HAWK-LIVE-003.*` (historical, not a public runnable).

## Limitations (NOT_YET_MODELED — explicit, not hidden)

Temporal windows, evidence-sufficiency transitions, mandatory escalation, declared `packet_sha256` verification (computed only), semantic entailment, broader lineage beyond `CLAIM_RECEIPT_MISSING`/`CROSS_CASE_*`/`PROVENANCE_*`, authorization budget. Live TLS for the watsonx.ai service connection was hardened offline (`HttpClientConfig` 10/150/30) but live-unverified until 003. Byte-for-byte artifact determinism not claimed (`timestamp`/`dispatch_id` differ by design); semantic determinism (status/gates/schema/response/lineage) is asserted.

## Why This Is Portfolio-Worthy

Not a chatbot — a reliability layer that stops a chatbot from hallucinating citations and proves it halted before calling the model. Shows: intake validation, hash-verified lineage, deterministic gates, human-review enforcement, and honest scope limits. Portfolio framing and evidence in `docs/EVIDENCE.md`.

---
*Teams are from the same truck. This repository is a curated portfolio extract of the author's private development work.*

---
## Evidence and Validation State

Full evidence detail — what has been observed, on which platform, and what remains
unobserved — lives in [`docs/EVIDENCE.md`](docs/EVIDENCE.md). In summary:

- The one-command offline demo and both offline test suites have been observed
  passing on Linux. Native Windows results, where established, are recorded in this
  repository's own commit history and CI runs rather than restated here, to avoid
  this file going stale.
- A historical internal validation run (outside this repository) recorded 277
  mission-engine checks and 14 watsonx-client checks passing on Windows against a
  larger private fixture set. This public repository does not treat that historical
  record as a substitute for independently observed results from its own, smaller
  public fixture set — see `docs/EVIDENCE.md` for what this repository's own checks
  actually cover.
- **Python version:** the code targets Python 3.10+. The GitHub Actions workflow
  (`.github/workflows/kitty-hawk-offline.yml`) currently validates against Python
  3.11 specifically — that is the floor this repository's CI actually exercises.
- GitHub-hosted CI (both `ubuntu-latest` and `windows-latest`) is configured but
  **not yet observed** — it becomes evidence only once a workflow run has actually
  executed on GitHub, not merely because it is configured to run.
