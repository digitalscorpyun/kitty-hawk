"""Shared contract and manifest-resolution utilities for the AVM Syndicate.

SUPERSEDED (operator ruling, 2026-08-23): this module originally
described a canonical-vendor provider-client family (Gemini, Qwen, Grok,
DeepSeek). That multi-vendor architecture is retired as a category error; IBM watsonx.ai
is the only authorized paid external inference service/runtime for the AVM Syndicate;
IBM Granite is the model family used for the recorded LIVE-003 inference (ibm/granite-4-h-small).
The gemini_client.py/qwen_client.py/grok_client.py/deepseek_client.py files
and call_openai_compatible_chat() below are preserved as historical/inert
code (not deleted, not live-wired) rather than removed outright.

Still live and in active use: SynapseProvider (the shape watsonx_client.py's
WatsonXClient and bedrock_client.py's BedrockClient already independently
converged on: system_prompt, current_agent, dispatch_id, last_usage, ask(),
set_agent(), now_iso()), MANIFEST_ALIAS_MAP / resolve_manifest_system_prompt()
(vendor-neutral seat -> manifest-path resolution, now also used directly by
WatsonXClient.set_agent()), now_iso(), and record_usage().
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pytz

LOCAL_TZ = pytz.timezone("America/Los_Angeles")
VAULT_BASE_PATH = Path(os.getenv("KITTY_HAWK_VAULT_PATH", os.getenv("VAULT_BASE_PATH", str(Path(__file__).resolve().parent / "fixtures" / "vault"))))


class SynapseProvider(Protocol):
    system_prompt: str
    current_agent: str
    dispatch_id: str | None
    last_usage: dict | None

    def ask(self, prompt: str, **kwargs) -> str: ...
    def set_agent(self, agent_name: str) -> None: ...
    def now_iso(self) -> str: ...


class ProviderUnavailableError(RuntimeError):
    """Raised at client construction when a provider's required credentials
    are absent. Callers (dispatch()) must catch this narrowly around
    construction only, never around .ask() — a real in-flight API failure
    must never be mistaken for a missing-credentials case."""


# Model-agnostic seat rename (operator ruling 2026-08-24): QWEN-ECHO and
# CTX-GROK named a specific vendor model (Alibaba Qwen, xAI Grok) as if that
# were the seat's identity, even though both execute on the same shared
# watsonx substrate as every other seat (see multi_provider_architecture_
# superseded_20260823.md) -- misleading given the retired per-vendor
# architecture. Canonical names now come directly from each seat's own
# protocol manifest title (echo_prophet_protocol_manifest.md,
# contextual_catalyst_protocol_manifest.md). New code must never emit a
# legacy name; this map exists only so old references keep resolving.
LEGACY_SEAT_ALIASES: dict[str, str] = {
    "QWEN-ECHO": "ECHO-PROPHET",
    "CTX-GROK": "CONTEXTUAL-CATALYST",
}


def resolve_seat_name(name: str) -> str:
    """Normalize a possibly-legacy seat identifier to its current canonical
    name. A no-op for any name that isn't a known legacy alias."""
    return LEGACY_SEAT_ALIASES.get(name, name)


# The single canonical seat -> manifest-path map for the whole package.
# WatsonXClient.set_agent() delegates here directly (its own former inline
# alias_map never covered CTX-GROK or CG-SCRIBE, a latent gap this closes).
MANIFEST_ALIAS_MAP: dict[str, str] = {
    "OD-COMPLY": "war_council/avm_syndicate/agents/protocols/oracular_decree_protocol_manifest.md",
    "TWIN-WARDEN": "war_council/avm_syndicate/agents/protocols/twin_warden_protocol_manifest.md",
    "ECHO-PROPHET": "war_council/avm_syndicate/agents/protocols/echo_prophet_protocol_manifest.md",
    "CONTEXTUAL-CATALYST": "war_council/avm_syndicate/agents/protocols/contextual_catalyst_protocol_manifest.md",
    "CG-SCRIBE": "war_council/avm_syndicate/agents/protocols/cipher_griot_protocol_manifest.md",
    "VS-ENC": "war_council/avm_syndicate/agents/protocols/vault_sentinel_protocol_manifest.md",
}


def resolve_manifest_system_prompt(agent_name: str) -> str:
    """Reads the seat's manifest and returns the frontmatter-delimited body
    as the system prompt -- identical logic to WatsonXClient.set_agent().
    Accepts a legacy seat name (resolved via resolve_seat_name()) for
    backward compatibility."""
    agent_name = resolve_seat_name(agent_name)
    rel_path = MANIFEST_ALIAS_MAP.get(agent_name) or f"war_council/avm_syndicate/agents/protocols/{agent_name.lower().replace('-', '_')}_protocol_manifest.md"
    full_path = VAULT_BASE_PATH / rel_path
    if not full_path.exists():
        raise FileNotFoundError(f"Manifest missing for {agent_name} at: {full_path}")
    content = full_path.read_text(encoding="utf-8")
    parts = content.split("---")
    if len(parts) < 3:
        raise ValueError(f"Manifest at {full_path} is malformed.")
    return parts[-1].strip()


def now_iso() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def record_usage(log_path: Path, *, agent: str, dispatch_id: str | None, model_id: str, usage: dict | None) -> None:
    """Append-only usage ledger, same shape/discipline as watsonx_client.py
    and bedrock_client.py: counts and identifiers only, never prompt or
    response text. Never raises -- a logging failure must not take down a
    call whose real work already succeeded."""
    usage = usage or {}
    entry = {
        "ts": now_iso(),
        "script": Path(sys.argv[0]).name or "interactive",
        "agent": agent,
        "dispatch_id": dispatch_id,
        "model_id": model_id,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reported": bool(usage),
    }
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"Usage ledger write failed (call itself succeeded): {exc}")


def call_openai_compatible_chat(
    *, base_url: str, api_key: str, model_id: str, system_prompt: str, prompt: str,
    temperature: float = 0.0, max_tokens: int = 1500, timeout: float = 60.0,
) -> tuple[str, dict]:
    """Shared POST for the three vendors (Qwen, Grok, DeepSeek) that
    expose an OpenAI-compatible /chat/completions endpoint. Returns
    (response_text, usage_dict). Imports requests lazily so constructing a
    client (checking credentials) never requires a network library import
    to have succeeded, and so no client accidentally makes a network call
    at import time."""
    import requests

    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    text = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {}) or {}
    return text, usage
