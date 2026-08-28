# ==============================================================================
# ✶⌁✶ watsonx_client.py — THE UNIVERSAL SYNAPSE v3.6 [HARDENED]
# ==============================================================================
# ROLE: Hardened infrastructure bridge with Env-Var Authority.
# SERVICE/RUNTIME: IBM watsonx.ai (external inference service/runtime)
# MODEL (recorded LIVE-003): ibm/granite-4-h-small (IBM Granite)
# COMPLIANCE: WC-DIR-2026-01-11-ENV-HARDENING
# NOTE: Kitty Hawk -> WatsonXClient -> IBM watsonx.ai service/runtime -> Granite model -> response
# ==============================================================================

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytz
try:
    import httpx  # noqa: F401
except ImportError:
    httpx = None  # type: ignore
try:
    from ibm_watsonx_ai import APIClient, Credentials
    from ibm_watsonx_ai.foundation_models import ModelInference
    from ibm_watsonx_ai.utils.utils import HttpClientConfig
except ImportError:
    APIClient = Credentials = ModelInference = HttpClientConfig = None  # type: ignore  # offline stub

from provider_protocol import resolve_manifest_system_prompt, resolve_seat_name

LOCAL_TZ = pytz.timezone("America/Los_Angeles")
VAULT_BASE_PATH = Path(os.getenv("KITTY_HAWK_VAULT_PATH", os.getenv("VAULT_BASE_PATH", str(Path(__file__).resolve().parent / "fixtures" / "vault"))))

# Append-only token ledger. Usage was previously printed and discarded, which
# meant answering "what spent those tokens?" required inferring from debug-file
# timestamps after the fact. Forge-local (never the Vault), one JSON object per
# call, and it records no prompt or response text — only counts and identifiers.
USAGE_LOG_PATH = Path(
    os.getenv(
        "WATSONX_USAGE_LOG",
        str(Path(__file__).resolve().parents[1] / "_debug" / "watsonx_usage.jsonl"),
    )
)

def _load_missing_from_user_registry(missing_vars: list[str]) -> list[str]:
    """Self-heal REQUIRED_VARS absent from this process's environment by
    reading them directly from the Windows User-scope registry
    (HKCU\\Environment), instead of trusting the launching process to have
    propagated them.

    Root cause (KH-01 stall, 2026-08-24): a long-lived orchestrator process
    (e.g. Manus) started before these vars were set at User scope spawns
    children from its OWN stale environment snapshot -- `setx`/Control Panel
    only broadcasts WM_SETTINGCHANGE to already-running processes and does
    not retroactively inject values into an inherited environment block, so
    the child's `os.environ` stays empty regardless of what the registry
    holds. Reading the registry directly makes this check orchestrator-
    agnostic: it no longer matters whether the parent process ever saw the
    values.

    Populates os.environ for THIS process only -- never writes the registry,
    never logs a value, only which var names resolved. Returns the subset of
    missing_vars still unresolved after the attempt."""
    if sys.platform != "win32":
        return missing_vars
    try:
        import winreg
    except ImportError:
        return missing_vars
    still_missing: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for var in missing_vars:
                try:
                    value, _ = winreg.QueryValueEx(key, var)
                except FileNotFoundError:
                    still_missing.append(var)
                    continue
                if value:
                    os.environ[var] = value
                else:
                    still_missing.append(var)
    except OSError:
        return missing_vars
    return still_missing


# FAIL-FAST GUARD: Authority of the Execution Layer
REQUIRED_VARS = [
    "WATSONX_APIKEY",
    "WATSONX_PROJECT_ID",
    "WATSONX_URL",
    "WATSONX_REGION",
]
missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    resolved_from_registry = [v for v in missing if v not in _load_missing_from_user_registry(missing)]
    if resolved_from_registry:
        print(f"⚙ Synapse: resolved {resolved_from_registry} from User-scope registry (process environment did not carry them).")
    missing = [v for v in missing if not os.getenv(v)]
if missing:
    print(f"❌ CRITICAL INFRASTRUCTURE FAILURE: Missing env vars {missing}")
    sys.exit(1)


class WatsonXClient:
    # IBM watsonx.ai is the only authorized paid external inference service/runtime for the AVM
    # Syndicate; IBM Granite is the model family for the recorded LIVE-003 inference (ibm/granite-4-h-small)
    # (operator ruling 2026-08-23). Exposed so callers like
    # syndicate_router.discover_seat_availability() can generically check
    # credential presence the same way it already does for any other
    # provider class -- this was previously absent, which meant a seat bound
    # to WatsonXClient was silently reported "available" regardless of
    # whether these variables were actually set.
    REQUIRED_ENV_VARS = ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION")

    def __init__(self, model_id: str | None = None):
        if model_id is None:
            model_id = __import__("os").getenv("WATSONX_MODEL_ID", "ibm/granite-4-h-small")
        self.api_key = os.getenv("WATSONX_APIKEY")
        self.project_id = os.getenv("WATSONX_PROJECT_ID")
        self.url = os.getenv("WATSONX_URL")
        self.region = os.getenv("WATSONX_REGION")
        self.model_id = model_id
        self.current_agent = "SYNAPSE-CORE"
        self.system_prompt = "You are a cognitive node of the AVM Syndicate."
        self.last_usage = None
        self.dispatch_id = None

        self.creds = Credentials(api_key=self.api_key, url=self.url)
        # IBM SDK v1.3.42 defaults to a 1,800-second read timeout. The runner
        # itself bounds each stage at 180 seconds, but an SDK request with a
        # much longer read timeout can outlive that stage boundary in its
        # worker thread. Use the SDK-supported HttpClientConfig path so the
        # provider's transport bound is explicit and remains watsonx.ai-service-only (no fallback to another inference service, no substitution of the configured model ID (ibm/granite-4-h-small) without separate authorization).
        self.http_timeout = httpx.Timeout(
            connect=float(os.getenv("WATSONX_CONNECT_TIMEOUT_SECONDS", "10")),
            read=float(os.getenv("WATSONX_READ_TIMEOUT_SECONDS", "150")),
            write=float(os.getenv("WATSONX_WRITE_TIMEOUT_SECONDS", "30")),
            pool=float(os.getenv("WATSONX_POOL_TIMEOUT_SECONDS", "30")),
        )
        self.http_limits = httpx.Limits(max_connections=10, max_keepalive_connections=10, keepalive_expiry=5)
        self.http_config = HttpClientConfig(timeout=self.http_timeout, limits=self.http_limits)
        self.default_params = {
            "temperature": 0.0,
            "max_tokens": 1500,
        }

    def now_iso(self) -> str:
        return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")

    def _record_usage(self) -> None:
        """Append one line to the token ledger.

        Never raises: a logging failure must not take down a call whose real
        work already succeeded. Records counts and identifiers only — no prompt
        or response text, so the ledger is safe to read and share.
        """
        usage = self.last_usage or {}
        entry = {
            "ts": self.now_iso(),
            "script": Path(sys.argv[0]).name or "interactive",
            "agent": self.current_agent,
            "dispatch_id": self.dispatch_id,
            "model_id": self.model_id,
            "region": self.region,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "reported": bool(usage),
        }
        try:
            USAGE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(USAGE_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            print(f"⚠ Usage ledger write failed (call itself succeeded): {exc}")

    def set_agent(self, agent_name: str):
        """MANIFEST RESOLUTION: delegates to provider_protocol's canonical,
        vendor-neutral seat -> manifest-path map (MANIFEST_ALIAS_MAP). This
        replaces a local alias_map that never covered CTX-GROK or CG-SCRIBE
        -- their fallback path derived the wrong filename from the agent
        name itself, silently loading no manifest for either seat."""
        self.system_prompt = resolve_manifest_system_prompt(agent_name)
        # Store the resolved canonical name, not whatever legacy alias was
        # passed in -- current_agent feeds usage-ledger/dispatch logs, and
        # new log entries must never emit a retired seat name (2026-08-24
        # model-agnostic rename).
        self.current_agent = resolve_seat_name(agent_name)
        print(f"✶ Synapse: {self.current_agent} identity manifested.")

    def ask(self, prompt: str, **kwargs) -> str:
        """EXECUTION: chat-completion call. Migrated off the deprecated
        /ml/v1/text/generation endpoint to /ml/v1/text/chat (2026-08-01).
        Native system/user roles replace the old string-sentinel siloing —
        a chat model doesn't echo the prompt back, so there's nothing to strip."""
        call_params = {**self.default_params, **kwargs}
        max_new = call_params.pop("max_new_tokens", None)
        call_params.pop("decoding_method", None)
        if max_new is not None:
            # MUST overwrite, not setdefault. Before the 2026-08-01 chat-API
            # migration, default_params held "max_new_tokens": 1500 and a caller
            # passing max_new_tokens=2600 overrode it by key collision. Renaming
            # the default to "max_tokens" broke that collision, so setdefault
            # found 1500 already present and silently discarded every caller's
            # explicit budget -- capping scholarly_dive at 1500 when it asked for
            # 2600 and making Catto-length artifacts (~2200 completion tokens)
            # unreachable. An explicit per-call budget always wins.
            call_params["max_tokens"] = max_new

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        api_client = APIClient(
            credentials=self.creds,
            project_id=self.project_id,
            httpx_client=self.http_config,
            async_httpx_client=self.http_config,
        )
        model = ModelInference(
            model_id=self.model_id,
            api_client=api_client,
            max_retries=int(__import__("os").getenv("WATSONX_MAX_RETRIES", "0")),
            delay_time=1.0,
            retry_status_codes=[429, 500, 502, 503, 504],
        )

        response = model.chat(messages=messages, params=call_params)

        self.last_usage = response.get("usage", {})
        if self.last_usage:
            print(
                f"✶ Synapse usage: {self.last_usage.get('prompt_tokens', '?')} prompt "
                f"+ {self.last_usage.get('completion_tokens', '?')} completion "
                f"= {self.last_usage.get('total_tokens', '?')} total tokens "
                f"[{self.model_id}, {self.region}]"
            )
        else:
            print("✶ Synapse usage: response contained no 'usage' field — IBM did not report token counts for this call.")

        self._record_usage()
        # Clear immediately after logging so a stale dispatch_id from one
        # router call can't silently attach to a later, unrelated .ask() on
        # the same long-lived client (qwen_echo.py etc. hold one instance).
        self.dispatch_id = None

        return response["choices"][0]["message"]["content"].strip()
