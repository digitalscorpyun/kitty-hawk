# M6d — AWS extension plan, revision 3 (planning only)

**Date:** 2026-10-02 (updated 2026-10-03: Python 3.12 selected, Lambda handler added, package set re-measured)
**Status:** plan for operator approval (updated 2026-10-02 with the Linux execution result). **No AWS action, billing access, resource creation, or
deployment is authorized by this document.** Each of those needs its own explicit approval.
**Scope:** deploy the existing FastAPI `/agent/run` boundary behind API Gateway, using `FakeClient`
only. No live watsonx.ai / Granite call, and no M6e (Orchestrate comparison).

Measurements referenced here: [M6D_COLD_START_LATENCY.md](M6D_COLD_START_LATENCY.md).

## Working decisions (confirmed 2026-10-02)

1. **Packaging:** measure the final Linux dependency set; trim first, and assess a container image
   and its costs only if trimming cannot get under the ZIP limit. Trimmed set: see below.
2. **"$0" means no cash charge and no credit consumption.** Any uncertainty about cost stops the
   deployment.
3. **Bearer token:** a fresh, demo-only Lambda environment variable. Never logged, never committed,
   removed at teardown.
4. **Gateway auth:** IAM authorization on the API Gateway route, plus the FastAPI bearer check.
   An API key is client identification, not authentication, and is not relied on.
5. **Granite credentials:** deferred past M6d. The smoke test uses `FakeClient`.
6. **Corpus:** a small pinned test corpus in this repo; no private notes corpus is deployed.
7. **Runtime: Python 3.12 (`python3.12`), selected 2026-10-03.** AWS's Lambda runtimes page lists it
   as supported on Amazon Linux 2023 with deprecation Oct 31, 2028; 3.13 and 3.14 are also listed.
   3.12 is the version the Linux measurements used.
8. **Entry point:** `core/lambda_handler.py` wraps the existing FastAPI app with Mangum. It is
   **fake-only**: it raises at import unless `KITTY_HAWK_LAMBDA_MODE=fake`, overrides `get_client` with a
   scripted FakeClient and `get_rag_store` with the pinned test corpus, and has no live mode. The bearer
   check (`verify_api_key`) is not overridden, so every request is still rejected without the configured
   token. The trace DB defaults to `/tmp` (the package directory is read-only on Lambda).

## Packaging measurement

| Item | Result |
|---|---|
| Baseline deployed set (FastAPI, chromadb, SQLAlchemy, pytz, PyYAML + transitive), Windows wheels, unzipped | about 395 MB |
| Trimmed set, Windows wheels, unzipped | about 175 MB |
| **Trimmed set, Linux (manylinux, CPython 3.12) wheels, unzipped, 36 packages, executed on Ubuntu 24.04** | **173,809,918 bytes (about 173.8 MB)** |
| Lambda ZIP limit (unzipped), per AWS documentation | 250 MB |
| Headroom | about 76 MB |
| Mangum wheel (a possible entry-point adapter, **not** in the measured set) | about 17 KB |
| **Re-measured 2026-10-03: 42 packages (adds Mangum 0.22.0 plus httpx, httpcore, h11, certifi, idna), Linux, CPython 3.12.3, unzipped, excluding `__pycache__`** | **175,318,338 bytes (about 175.3 MB)** |
| Same set, including the `__pycache__` that `pip install --target` writes (33,482,651 bytes) | 208,800,989 bytes (about 208.8 MB) |
| Headroom vs 250,000,000 bytes: excluding / including `__pycache__` | 74,681,662 / 41,199,011 bytes |
| Headroom if the limit is 250 MiB (262,144,000 bytes): excluding / including `__pycache__` | 86,825,662 / 53,343,011 bytes |

How the first trimmed set was found (Windows): the pinned packages were installed into a scratch directory, then
removed one at a time, largest first. A removal was kept only if a full `POST /agent/run` request
(success case, `FakeClient`, SQLite trace store) still returned HTTP 200 with a `success`
termination, run in isolation with only the scratch directories on the import path. 55 of 89
packages were removed. The largest were kubernetes (73 MB), sympy (51 MB) and onnxruntime (42 MB).
numpy (51 MB) stayed because chromadb imports it at load time. The pinned result is in
[requirements-lambda.txt](../requirements-lambda.txt); `requirements.txt` is unchanged.

### Linux execution result, and the Windows flaw it exposed

The 34-package Windows-derived set was executed on real Linux: a throwaway Ubuntu 24.04.5 WSL2
distro, Python 3.12.3, x86_64, no AWS credentials, `python -S` with only the deployed set and the
test-only httpx packages on the import path. The existing Ubuntu distro was not used.

- **As derived on Windows, it failed.** `import chromadb` raised `ModuleNotFoundError` for
  `pybase64`, then `orjson`. `rag/store.py` swallows the ImportError and then reports "chromadb not
  installed", so the visible symptom was an HTTP 500.
- **Why Windows missed it:** when a package was removed from the Windows scratch install, its empty
  directory remained. Python treats an empty directory as a **namespace package**, so
  `import pybase64` succeeded as an empty stub. The Windows result therefore only showed that imports
  did not error, not that the real package was unnecessary. The Linux set was built only from the kept
  wheels, so it had no such stubs.
- **After adding back `pybase64` and `orjson`**, `POST /agent/run` (FakeClient, SQLite trace store)
  returned HTTP 200 with a `success` termination, **3 of 3 runs**, about 6.1-6.4 s wall each.
- Linux timings (WSL2, not Lambda): `import chromadb` about 3.8 s; `RagStore` plus indexing the
  3-chunk test corpus about 244 ms.
- Other packages removed in the Windows pass were not re-added and the request still passed on
  Linux, so for this path they really are unneeded. That is stronger evidence than the Windows one.

### Re-measure with the Lambda handler (2026-10-03)

Run in the existing `Ubuntu` WSL distro (Ubuntu 24.04.2, Python 3.12.3), not a new distro or container.
`requirements-lambda.txt` was installed with `pip install --no-deps --only-binary=:all: --target`
into a scratch directory under the distro home, which was deleted afterwards. The handler test then ran
under `python3 -S` with only that directory on the import path and no `WATSONX_*` variables set.

- **Two defects found by the first Linux run, both fixed:**
  1. `watsonx_client` exits at import if the four `WATSONX_*` names are unset. On the Windows dev
     machine they were silently resolved from the User registry, which hid this. On Lambda the handler would
     have crashed on import. `core/lambda_handler.py` now sets inert placeholder values
     (`lambda-fake-mode-placeholder`) with `setdefault`; they are not credentials and the fake path never
     builds a `WatsonXClient`. The test asserts the placeholders are in place.
  2. `chromadb` imports `httpx` at load time (`chromadb/utils/embedding_functions/onnx_mini_lm_l6_v2.py`).
     The 2026-10-02 "isolated" run above had httpx on the path as a *test-only* dependency, so httpx was
     never part of the measured set and that run under-counted the runtime packages. `httpx`, `httpcore`,
     `h11`, `certifi` and `idna` are now pinned in `requirements-lambda.txt`. The 2026-10-02 figures above
     are preserved as history, not edited.
- **Result:** `tests/test_m6d_lambda_handler.py` passed 8 of 8 checks, 3 of 3 runs, about 3.6-4.0 s wall
  each (WSL2, not Lambda). The 8 checks: import without `KITTY_HAWK_LAMBDA_MODE=fake` fails closed;
  inert placeholders set on import; no token gives 401; wrong token gives 401; correct token gives 200;
  the termination is `success`; the scripted answer is returned; a second request also succeeds (a fresh
  scripted client per request). The bearer check is not overridden in any of them. The first draft of the
  test had 7 checks; the placeholder assertion made it 8.
- **Not directly comparable:** the 2026-10-02 figure (173,809,918 bytes, 36 packages) did not record whether
  `__pycache__` was counted. The excluding-`__pycache__` figure is 1,508,420 bytes larger; the added
  packages account for it, but this was not itemized.
- **Zip size is also unmeasured.** These figures are unzipped directory sizes; no deployment ZIP was built.
  Whether `__pycache__` is shipped is undecided; both figures fit under the limit either way.

### Limits of this measurement

- The Linux set **was executed once** (one WSL2 distro, Python 3.12.3, three runs of one request)
  and passed. That is not a Lambda execution; memory size, CPU allocation and platform cold start
  are unmeasured. The earlier Windows trim result is superseded by it, because of the namespace-package
  flaw above.
- **Python 3.12 is now selected (decision 7)**, but on documentation only. The Linux runs used 3.12.3 on
  WSL2, not the Lambda runtime. The local development environment is Python 3.10.
- Only the **success-case request path** was exercised. **Other paths may need packages that were
  removed**: a persistent Chroma client, Postgres/psycopg2, and a live watsonx call (which would
  need `requests` and its dependencies).
- Versions are pinned from the local development environment, not re-resolved for Linux/3.12.
- The Lambda handler (`core/lambda_handler.py`) now exists and is tested only against hand-built API
  Gateway HTTP API (payload v2) events, not a real API Gateway or Lambda invocation.
- The 250 MB limit and the 10 GB container-image limit were confirmed against AWS documentation by
  two reviewers; they were not independently re-checked when this was written. Cost is a separate
  question and is not settled by size.

### Limits of the handler test

- **The first 7-check run (Windows) used Python 3.10**, not Python 3.12 and not Lambda. The 8-check run
  on Python 3.12.3 is Linux/WSL2, still not Lambda.
- **CI skips the test unless Mangum is installed.** `tests/test_m6d_lambda_handler.py` exits 0 with a
  SKIP message when `mangum` is absent. CI installs `requirements.txt`, which does not list Mangum
  (it is in `requirements-lambda.txt` only), so CI does not run these checks. CI and `requirements.txt`
  were deliberately left unchanged.
- **Local credential isolation on Windows is unproven.** On the Windows run, `agent_loop` printed that it
  resolved the four `WATSONX_*` names "from User-scope registry". The Linux run, with no such registry and
  none of the variables set, is the cleaner evidence: the fake path runs on placeholders alone. It does
  not prove the code could never reach a live call under a different configuration.
- **Background trace export after Lambda freezes is unmeasured.** `AsyncTraceExporter` is
  fire-and-forget; whether it completes after the response, when Lambda freezes the execution
  environment, is not tested. `/tmp` traces are ephemeral per environment either way.
- No watsonx.ai or AWS call was made; no billing, credential or ledger action was taken.

## Resources (proposed, not created)

| Resource | Notes |
|---|---|
| API Gateway (HTTP API) | IAM authorization on the route; callers sign requests (SigV4) |
| Lambda function running FastAPI | ZIP package from `requirements-lambda.txt` if it still fits after a Linux execution check |
| IAM execution role | single-action-scoped policies; no administrator access |
| CloudWatch log group | cost at this volume Unknown; retention cap set before first deploy |
| NAT Gateway, EFS, RDS, container registry | none. Any step that seems to need one is presented first (necessity, cost, teardown) |

The Lambda runtime version, HTTP API vs REST API specifics, and exact free-tier terms are Unknown
until checked against AWS documentation and this account's billing at build time.

## $0 cost gate

- Definition above: no cash charge and no credit consumption.
- Free-tier terms are conditional; no service is assumed free until its pricing is checked against
  this account. That includes API Gateway, Lambda, CloudWatch logs.
- A request cap and a log-retention cap are set before the first deploy. Values are Unknown until
  pricing is checked.
- Before-and-after credit evidence is captured, per the practicum ledger ritual.
- Stop rule: any cost uncertainty stops the deployment.

## Teardown

- A scripted, CLI-verified delete of everything created, with a dry-run listing of targets before
  any create.
- Every resource tagged `project`, `lab`, `ephemeral` so teardown can find them by tag.
- Verification by CLI listing, not by assuming the delete worked. The demo bearer token is removed
  with the function.

## Carried-forward AWS practice

Least-privilege IAM; no SSH where avoidable; campaign resource tagging; before/after credit
evidence; CLI/API-verified teardown; a practicum ledger row opened at cost-check just before the
build, not during planning.

## Sequence (each external step separately authorized)

1. Operator approves or amends this plan.
2. **Local, no AWS:** ~~execute the trimmed Linux package on Linux with the same request-path smoke
   test~~ **done 2026-10-02 (passed after adding `pybase64` and `orjson`; see above)**.
   ~~Settle the Python version; write a Lambda entry point and test it locally.~~ **done 2026-10-03:
   Python 3.12; `core/lambda_handler.py` and its 8-check test pass on Linux/3.12.3 with the 42-package
   set (see above).** Still to do: decide whether CI should install Mangum.
3. Read-only check of AWS documentation for the runtime, pricing and free-tier terms.
4. Billing view for the before-credit baseline (separately authorized).
5. Practicum ledger row (a private-notes write, separately authorized).
6. Create resources with `FakeClient` (separately authorized).
7. `curl` proof against the deployed endpoint.
8. Teardown, CLI verification, after-credit comparison.
9. Evidence and limitations note, then stop at M6d's boundary for an operator-authorized commit.

## Still open

- Whether the set behaves the same inside the Lambda runtime (memory, CPU, cold start): unmeasured.
- Whether CI should install Mangum so the handler test runs there (CI unchanged for now).
- Whether background trace export completes after Lambda freezes the environment.
- Request and log caps; every service's pricing against this account.
- Whether any untested path (persistent Chroma, Postgres, live Granite) needs packages removed here.
- Granite credential design (deferred; required before any live call).
