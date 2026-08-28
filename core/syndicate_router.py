"""Governed AVM Syndicate handoff router.

Option B (capability-matching) ratified 2026-08-23: the classifier selects a
seat by matching a free-text task against each eligible seat's stated
capability, not against a fixed escalation-condition table. It never grants
authority. VS-ENC policy validates the complete invocation contract before a
provider adapter may serve one of the eligible seats. VS-ENC and WATSONX are
structurally excluded from automated selection (R1, ratified 2026-08-23) —
excluded from the classifier's candidate pool by construction, and refused
independently by dispatch() regardless of what the classifier returns. Vault
writeback is disabled unless an operator authorization and a Gold Standard
emitter are both supplied.

EXTERNAL INFERENCE BOUNDARY (operator ruling, 2026-08-23 -- corrects an earlier,
since-retired multi-vendor architecture): IBM watsonx.ai is the only
authorized paid external inference service/runtime for the AVM Syndicate; IBM Granite
is the model family used for the recorded LIVE-003 inference (ibm/granite-4-h-small).
SEAT_PROVIDER therefore maps every assigned-provider seat to WatsonXClient (client for
the watsonx.ai service, which then invokes the Granite model) -- OD-COMPLY,
ECHO-PROPHET (formerly QWEN-ECHO), CONTEXTUAL-CATALYST (formerly CTX-GROK),
and CG-SCRIBE are governed identities/jurisdictions (distinct manifests
loaded via WatsonXClient.set_agent()), not vendor API contracts, and are
never constructed against a different provider class. The two seats were
renamed 2026-08-24 (operator ruling, model-agnostic naming) since their old
names referenced specific vendor models that no longer have any technical
binding to the seat; resolve_seat_name() in provider_protocol.py keeps
legacy names readable without this module ever emitting them again.
TWIN-WARDEN and MW-ARCHIVE still have no registered provider and fail closed
pending their own separate evidence-backed operator rulings (unchanged by
this correction). WATSONX remains a distinct, command-invoked advisory seat
identity, structurally excluded from automated dispatch (R1) -- the shared
IBM watsonx.ai inference service/runtime is not the same thing as the WATSONX seat
being selected. No live provider calls have been made establishing this;
production dispatch validation is still pending before the router itself is
fully ratified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Protocol

import pytz
import yaml
from watsonx_client import WatsonXClient

# IBM watsonx.ai is the only authorized paid external inference service/runtime (operator ruling
# 2026-08-23, correcting an earlier, since-retired multi-vendor architecture).
# TWIN-WARDEN and MW-ARCHIVE stay absent from SEAT_PROVIDER pending their own
# separate evidence-backed provider rulings.
from provider_protocol import ProviderUnavailableError, resolve_seat_name

LOCAL_TZ = pytz.timezone("America/Los_Angeles")
VAULT_BASE_PATH = Path(os.getenv("KITTY_HAWK_VAULT_PATH", os.getenv("VAULT_BASE_PATH", str(Path(__file__).resolve().parent / "fixtures" / "vault"))))
GRANITE_MODEL_ID = "ibm/granite-4-h-small"
DISPATCH_LOG_PATH = Path(os.getenv("SYNDICATE_ROUTER_LOG", str(Path(__file__).resolve().parents[1] / "_debug" / "syndicate_router_log.jsonl")))
INVOCATION_LAW_PATH = Path(__file__).parent.parent / "config" / "vs_enc_invocation_law.yaml"

CARR_CATEGORIES = ("Social Structures", "Governance", "Ways of Knowing", "Science and Technology", "Cultural Meaning-Making", "Movement and Memory")


@dataclass(frozen=True)
class CarrRouting:
    primary: str
    secondary: tuple[str, ...] = ()
    liberation_test: str = ""

    def validate(self) -> None:
        if self.primary not in CARR_CATEGORIES:
            raise ValueError(f"Unknown Carr category: {self.primary!r}")
        invalid = set(self.secondary) - set(CARR_CATEGORIES)
        if invalid:
            raise ValueError(f"Unknown secondary Carr categories: {sorted(invalid)}")
        if self.primary in self.secondary:
            raise ValueError("Primary Carr category cannot also be secondary.")
        if not self.liberation_test.strip():
            raise ValueError("The liberation test ('How do it free us?') requires an answer.")


@dataclass(frozen=True)
class InvocationContract:
    """The four fields required by VS-ENC manifest section III."""
    invocation_type: str
    agent: str
    output_shape: str
    writeback: bool = False


@dataclass(frozen=True)
class AgentSeat:
    name: str
    manifest_path: str
    manifest_sha256: str
    provider_adapter: str
    invocation_types: frozenset[str]
    output_shapes: frozenset[str]
    auto_dispatch_excluded: bool = False


def _seat(name: str, manifest: str, digest: str, *, provider_adapter: str = "watsonx_manifest", auto_dispatch_excluded: bool = False) -> AgentSeat:
    return AgentSeat(name, manifest, digest, provider_adapter, frozenset({"syndicate_handoff"}), frozenset({"narrative_text", "structured_text"}), auto_dispatch_excluded)


AGENT_SEATS: dict[str, AgentSeat] = {
    # R1: VS-ENC is model-agnostic (operator ruling 2026-08-23, superseding an
    # earlier "genuinely ChatGPT/OpenAI" characterization that conflated
    # behavioral provenance with a vendor API contract -- the same category
    # error corrected for TWIN-WARDEN and the four SEAT_PROVIDER seats).
    # VS-ENC is never an automatic dispatch target regardless -- human-invoked
    # policy seat, excluded structurally (below), not because of any
    # provider binding.
    # Hash updated 2026-08-23: a legitimate, already-committed manifest
    # revision changed this file's content since the prior digest was
    # pinned. Re-pinning follows independent confirmation that the change
    # is a real, intentional manifest edit -- not a stray or unexplained
    # modification (same verification bar as the CG-SCRIBE re-pin below).
    "VS-ENC": _seat("VS-ENC", "war_council/avm_syndicate/agents/protocols/vault_sentinel_protocol_manifest.md", "c02d25aa9438f77901678bb26e1241691913a8c7e087f8070224e8213dba14db", provider_adapter="vs_enc_policy", auto_dispatch_excluded=True),
    # Hash updated 2026-08-23: same governed manifest revision, same
    # verification standard as VS-ENC above.
    "OD-COMPLY": _seat("OD-COMPLY", "war_council/avm_syndicate/agents/protocols/oracular_decree_protocol_manifest.md", "f6f02a50ff167f08846a8ab6ffc50812ecd5fd38f674c45621fa377e952641ba"),
    "TWIN-WARDEN": _seat("TWIN-WARDEN", "war_council/avm_syndicate/agents/protocols/twin_warden_protocol_manifest.md", "715db3f7dd171c84e5965fef6a3083a2f30e57cc35b5d5e1131cdd4ae2e8fd1a", provider_adapter="unassigned"),
    # Hash re-pinned 2026-08-24: the 2026-08-23 value for this digest did not
    # actually match the manifest source, confirmed by independently
    # recomputing the file's hash against its actual committed content with
    # a clean working tree and no other pending changes. The mismatch traced
    # to a data-entry error made while re-pinning CG-SCRIBE below, not a
    # sign of further, unexplained drift in this manifest.
    "ECHO-PROPHET": _seat("ECHO-PROPHET", "war_council/avm_syndicate/agents/protocols/echo_prophet_protocol_manifest.md", "45194b4f0dae0905c52cbd64f2fd0f5f3960871816251611351477656bf455fd"),
    "MW-ARCHIVE": _seat("MW-ARCHIVE", "war_council/avm_syndicate/agents/protocols/mnemonic_warden_protocol_manifest.md", "41675b1c00eaa82b63f3684a73b344f83c67a7c60283e28106af8d477e26e7e5"),
    # Hash re-pinned 2026-08-24: a legitimate, already-committed manifest
    # revision -- a coherent, deliberate rename pass touching this
    # manifest's prose, tags, and one governed field name together in a
    # single edit. Re-pinning followed direct inspection of that revision's
    # diff, confirming a deliberate content change rather than a stray edit.
    "CONTEXTUAL-CATALYST": _seat("CONTEXTUAL-CATALYST", "war_council/avm_syndicate/agents/protocols/contextual_catalyst_protocol_manifest.md", "6e3e8d43f171958d02dfff7c02377213a4e9ae5cab83dce73c917c5e77abc969"),
    "CG-SCRIBE": _seat("CG-SCRIBE", "war_council/avm_syndicate/agents/protocols/cipher_griot_protocol_manifest.md", "2c793647b8cc8636d4d98fe5730200e91d21e4b27046b62d0fd92776424e4105"),
    # R1 / S-10: WATSONX's provider genuinely is watsonx -- it is command-invoked
    # only (`watson scan`/`bias`/`nlu`/`signal`), never an automatic dispatch
    # target. Excluded here so a capability match can never route to it.
    "WATSONX": _seat("WATSONX", "war_council/avm_syndicate/agents/protocols/external_analyst_protocol_manifest.md", "d82f0ca8eaa816fde9c678fc4ca7851bb4c522d7e697e9e6a23ecd06e474404d", auto_dispatch_excluded=True),
}

# Curated capability summaries, one per seat, grounded directly in each
# seat's manifest Role Statement / Jurisdiction / Canonical Functions section
# (read 2026-08-23, per-seat readiness assessment). These are the classifier's only
# candidate pool -- rendered exclusively for seats where
# AGENT_SEATS[name].auto_dispatch_excluded is False, so VS-ENC and WATSONX
# can never appear here regardless of anything else in this module (R1,
# layer 1 of 2; dispatch()'s independent refusal is layer 2).
SEAT_CAPABILITIES: dict[str, str] = {
    "TWIN-WARDEN": "Protects the learning boundary. Governance gate: bias detection (selection, framing, omission, skew), consent verification, distribution/drift monitoring, dataset/input card generation, source-fidelity verification. Pedagogical forge: drill decomposition, progressive difficulty scaffolding, repetition circuit design, exam-storage compression, skill validation through execution.",
    "ECHO-PROPHET": "Converts fragmented evidence into structured, archive-grade synthesis: claim interrogation, evidence adjudication, structured synthesis, comparative reasoning, bias exposure, receipt validation, uncertainty disclosure, context-boundary enforcement, failure-state remediation.",
    "MW-ARCHIVE": "Prevents cognitive amnesia across sessions: session lineage tracking, recall integrity checks, version memory. Ensures prior decisions remain visible, terminology stays stable, governance does not reset by accident.",
    "CONTEXTUAL-CATALYST": "Makes thinking possible at scale: defines terms precisely, exposes system boundaries and assumptions, models causal relationships and feedback loops, prevents semantic drift across agents and notes. Builds the terrain arguments occur on rather than arguing outcomes itself.",
    "CG-SCRIBE": "Compresses validated, provided, or verification-buffered analysis into forms that travel: micro-briefs, encoded rhetoric, captions, thread-ready posts, public-facing signal artifacts. Prepares language; does not decide the public move or replace the agents that adjudicate claims.",
    "OD-COMPLY": "Compliance Finisher, Formatting Foreman, Output Validation Layer, Literal Serializer (when invoked). Governs how outputs are finalized, never what they decide.",
}

# IBM watsonx.ai inference service bindings (operator ruling 2026-08-23, superseding the
# earlier, since-retired per-vendor SEAT_PROVIDER mapping). OD-COMPLY, ECHO-PROPHET, CONTEXTUAL-
# CATALYST, and CG-SCRIBE are governed identities/jurisdictions distinguished by manifest
# (WatsonXClient.set_agent()), not by distinct vendor API contracts -- all
# four execute against the same authorized IBM watsonx substrate. TWIN-WARDEN's
# retired KIMI-DEUX/Moonshot association was a behavioral analogy, not a
# technical binding; it is deliberately absent here and fails closed until
# the operator ratifies a verified execution provider. VS-ENC and WATSONX
# are deliberately never keys here: dispatch()'s R1 gate (below) refuses
# both before this registry is ever consulted, so they cannot reach it even
# if added by mistake -- the shared watsonx.ai service/runtime used by the four seats (which then invokes Granite)
# above is not the same thing as the WATSONX advisory seat being selected.
# MW-ARCHIVE is deliberately absent (A1, operator ruling 2026-08-23): no
# genuine Microsoft Copilot execution path has been identified, and no
# substitute (Azure OpenAI, GitHub Copilot, watsonx, or otherwise) is
# authorized. An eligible seat with no entry here is unconditionally
# unavailable -- see discover_seat_availability().
SEAT_PROVIDER: dict[str, type] = {
    "OD-COMPLY": WatsonXClient,
    "ECHO-PROPHET": WatsonXClient,
    "CONTEXTUAL-CATALYST": WatsonXClient,
    "CG-SCRIBE": WatsonXClient,
}


def _eligible_seats() -> tuple[str, ...]:
    return tuple(name for name, seat in AGENT_SEATS.items() if not seat.auto_dispatch_excluded)


def _render_capability_cards() -> str:
    return "\n\n".join(f"{name}: {SEAT_CAPABILITIES[name]}" for name in _eligible_seats())


@dataclass(frozen=True)
class ClassificationResult:
    target: str | None
    raw_model_output: str


CLASSIFIER_SYSTEM_PROMPT = (
    "You are a capability-matching AVM routing classifier, not an agent persona. "
    "Given a task, select the ONE seat below whose stated capability most directly "
    "covers it, or respond 'AGENT: NONE' if none apply. Only select from the seats "
    "listed below -- never invent a seat name, and never select a seat that is not "
    "listed here under any circumstances, regardless of how well the task appears "
    "to match a capability you may know about from elsewhere."
)


def classify_task(task_description: str, carr: CarrRouting, client: WatsonXClient | None = None) -> ClassificationResult:
    carr.validate()
    router_client = client or WatsonXClient(model_id=GRANITE_MODEL_ID)
    router_client.system_prompt = CLASSIFIER_SYSTEM_PROMPT
    router_client.current_agent = "SYNDICATE-ROUTER"
    prompt = f"Carr primary: {carr.primary}\nCarr secondary: {', '.join(carr.secondary) or 'None'}\nLiberation test answer: {carr.liberation_test}\n\nEligible seats:\n{_render_capability_cards()}\n\nTask:\n{task_description}\n\nRespond only: AGENT: <name> or AGENT: NONE"
    raw = router_client.ask(prompt, max_new_tokens=20, temperature=0.0)
    target = None
    for line in raw.splitlines():
        if line.strip().upper().startswith("AGENT:"):
            candidate = line.split(":", 1)[1].strip()
            # Deliberately permissive here: an excluded canonical name (VS-ENC,
            # WATSONX) is still passed through to ClassificationResult.target
            # rather than laundered into None -- only a truly invented name
            # (not a key in AGENT_SEATS at all) is filtered here. dispatch()'s
            # independent refusal (R1, layer 2) is what must hold even when
            # this layer returns an excluded name -- that's the actual claim
            # the offline exclusion tests verify.
            candidate = resolve_seat_name(candidate)
            if candidate.upper() != "NONE" and (candidate in AGENT_SEATS):
                target = candidate
            break
    return ClassificationResult(target, raw)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class SeatAvailability:
    available: bool
    reason: str


def discover_seat_availability(seat: AgentSeat, *, require_credentials: bool = True) -> SeatAvailability:
    path = VAULT_BASE_PATH / seat.manifest_path
    if not path.is_file():
        return SeatAvailability(False, f"Manifest missing: {path}")
    actual = _sha256(path)
    if actual != seat.manifest_sha256:
        return SeatAvailability(False, f"Manifest drift: expected {seat.manifest_sha256}, found {actual}")
    if seat.auto_dispatch_excluded:
        return SeatAvailability(False, f"{seat.name} is excluded from automated dispatch by design (R1).")
    if require_credentials:
        provider_cls = SEAT_PROVIDER.get(seat.name)
        if provider_cls is None:
            # MW-ARCHIVE today (A1): an eligible seat with no canonical
            # provider registered fails closed unconditionally -- never
            # falls back to WatsonXClient or any other substitute.
            return SeatAvailability(False, f"No canonical provider binding configured for {seat.name}.")
        required_vars = getattr(provider_cls, "REQUIRED_ENV_VARS", ())
        missing = [name for name in required_vars if not os.getenv(name)]
        if missing:
            return SeatAvailability(False, f"{seat.name}'s canonical provider is unavailable; missing environment variables: {missing}")
    return SeatAvailability(True, "Manifest identity verified and provider prerequisites present.")


class AgentClient(Protocol):
    system_prompt: str
    current_agent: str
    def ask(self, prompt: str, **kwargs) -> str: ...


def _manifest_body(seat: AgentSeat) -> str:
    parts = (VAULT_BASE_PATH / seat.manifest_path).read_text(encoding="utf-8").split("---")
    if len(parts) < 3:
        raise ValueError(f"Malformed manifest for {seat.name}")
    return parts[-1].strip()


DispatchOutcome = Literal["executed", "escalated_orchestrator", "excluded_watsonx", "refused", "unavailable", "no_match", "dry_run"]


@dataclass(frozen=True)
class DispatchResult:
    outcome: DispatchOutcome
    target: str | None
    content: str | None
    reason: str
    dispatch_id: str | None = None


def _invocation_rule(invocation_type: str) -> dict | None:
    law = yaml.safe_load(INVOCATION_LAW_PATH.read_text(encoding="utf-8")) or {}
    return law.get("invocation_types", {}).get(invocation_type)


def validate_invocation(contract: InvocationContract, classification: ClassificationResult) -> str | None:
    rule = _invocation_rule(contract.invocation_type)
    if rule is None:
        return f"Unknown invocation type: {contract.invocation_type!r}"
    if classification.target is None:
        return "No validated classification target."
    contract_agent = resolve_seat_name(contract.agent)
    if contract_agent != classification.target:
        return "Invocation agent does not match the classified target."
    seat = AGENT_SEATS.get(contract_agent)
    if seat is None:
        return f"{contract.agent!r} is not one of the eight canonical seats."
    if contract.invocation_type not in seat.invocation_types or contract_agent not in rule.get("allowed_agents", []):
        return f"Invocation type is not allowed for {seat.name}."
    law_shapes = rule.get("output_shape", [])
    if contract.output_shape not in seat.output_shapes or contract.output_shape not in law_shapes:
        return f"Output shape {contract.output_shape!r} is not allowed for {seat.name}."
    if contract.writeback:
        return "Dispatch cannot authorize Vault writeback; use the separate operator-authorized Gold Standard gate."
    return None


def dispatch(classification: ClassificationResult, contract: InvocationContract, task_description: str, *, client: AgentClient | None = None, availability_check: Callable[[AgentSeat], SeatAvailability] = discover_seat_availability) -> DispatchResult:
    if classification.target is None:
        return DispatchResult("no_match", None, None, "Classifier found no validated seat match.")
    # R1, layer 2: independent, structural refusal for VS-ENC and WATSONX.
    # Checked against BOTH classification.target and contract.agent so this
    # cannot be bypassed by either field alone -- must hold even if the
    # classifier itself (layer 1) is fooled or misbehaves.
    for candidate_name in (classification.target, contract.agent):
        excluded_seat = AGENT_SEATS.get(candidate_name)
        if excluded_seat is not None and excluded_seat.auto_dispatch_excluded:
            if excluded_seat.name == "VS-ENC":
                return DispatchResult("escalated_orchestrator", "VS-ENC", None, "VS-ENC requires direct human invocation and is never auto-executed.")
            return DispatchResult("excluded_watsonx", excluded_seat.name, None, f"{excluded_seat.name} is command-invoked only (S-10); never an automated dispatch target.")
    error = validate_invocation(contract, classification)
    if error:
        return DispatchResult("refused", contract.agent, None, error)
    seat = AGENT_SEATS[resolve_seat_name(contract.agent)]
    availability = availability_check(seat)
    if not availability.available:
        return DispatchResult("unavailable", seat.name, None, availability.reason)
    if client is not None:
        agent_client = client
    else:
        # Canonical-provider construction. Deliberately no except-and-
        # fall-back-to-WatsonXClient/BedrockClient/anything-else branch --
        # a provider that fails to construct is "unavailable", full stop.
        # This is the fix for a prior six-seat provider-binding drift.
        provider_cls = SEAT_PROVIDER.get(seat.name)
        if provider_cls is None:
            return DispatchResult("unavailable", seat.name, None, f"No canonical provider binding configured for {seat.name}.")
        try:
            agent_client = provider_cls()
        except ProviderUnavailableError as exc:
            return DispatchResult("unavailable", seat.name, None, str(exc))
    agent_client.system_prompt = _manifest_body(seat)
    agent_client.current_agent = seat.name
    # Shared with watsonx_client.py's usage ledger so a token-cost line can be
    # joined back to the dispatch that spent it (F-07) — the two logs carried
    # no common key before this.
    dispatch_id = f"{classification.target}:{uuid.uuid4().hex[:8]}"
    agent_client.dispatch_id = dispatch_id
    return DispatchResult("executed", seat.name, agent_client.ask(task_description), "Governed handoff executed.", dispatch_id)


@dataclass(frozen=True)
class WritebackAuthorization:
    operator: str
    authorized: bool
    scope: str


GoldStandardEmitter = Callable[[dict], dict]


def build_emission_record(task_description: str, carr: CarrRouting, classification: ClassificationResult, result: DispatchResult) -> dict:
    if result.outcome != "executed" or not result.content:
        raise ValueError("Only executed, non-empty results may enter emission review.")
    return {"title": f"Syndicate Router Dispatch — {result.target}", "category": "system_log", "content": result.content, "routing_provenance": {"target_agent": result.target, "dispatch_id": result.dispatch_id}, "carr_category_routing": asdict(carr), "source_task": task_description}


def emit_with_gold_standard(record: dict, authorization: WritebackAuthorization | None, emitter: GoldStandardEmitter | None) -> dict:
    if authorization is None or not authorization.authorized:
        raise PermissionError("Vault writeback requires explicit operator authorization.")
    if authorization.operator != "digitalscorpyun" or authorization.scope != "syndicate_router_dispatch":
        raise PermissionError("Writeback authorization identity or scope is invalid.")
    if emitter is None:
        raise RuntimeError("No Gold Standard emitter is configured; writeback fails closed.")
    return emitter(record)


def _record_dispatch(task_description: str, carr: CarrRouting, classification: ClassificationResult, result: DispatchResult) -> None:
    # F-07 follow-up (S-12): executed dispatches previously left no durable
    # record of what the target agent actually said, only that the call
    # succeeded — making them unauditable and indistinguishable from a
    # fabricated response after the fact. _debug/ is gitignored, so
    # logging the full response here is local-only and never enters git history.
    entry = {"ts": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"), "script": Path(sys.argv[0]).name or "interactive", "task_preview": task_description[:120], "carr_primary": carr.primary, "target": result.target, "dispatch_id": result.dispatch_id, "outcome": result.outcome, "reason": result.reason, "content": result.content}
    try:
        DISPATCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DISPATCH_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"Dispatch ledger write failed (call itself succeeded): {exc}")


def route_and_execute(task_description: str, carr: CarrRouting, *, execute: bool = False, classifier_client: AgentClient | None = None, agent_client: AgentClient | None = None, availability_check: Callable[[AgentSeat], SeatAvailability] = discover_seat_availability) -> dict:
    """Safe default is classification-only. This function never writes Vault notes."""
    classification = classify_task(task_description, carr, client=classifier_client)
    if not execute:
        result = DispatchResult("dry_run", classification.target, None, "Classification only; execution was not explicitly enabled.")
    else:
        contract = InvocationContract("syndicate_handoff", classification.target or "NONE", "narrative_text", False)
        result = dispatch(classification, contract, task_description, client=agent_client, availability_check=availability_check)
    _record_dispatch(task_description, carr, classification, result)
    return {"classification": classification, "dispatch": result, "vault_payload": None}


def _to_json_payload(classification: ClassificationResult, result: DispatchResult) -> dict:
    """Machine-readable shape for --json CLI output and the ai_use_gate subprocess
    bridge (F-08). Kept separate from the print path so it's unit-testable without
    a live model call."""
    return {
        "target": classification.target,
        "outcome": result.outcome,
        "reason": result.reason,
        "dispatch_id": result.dispatch_id,
        "content": result.content,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AVM Syndicate Router — Option B capability matching, ratified 2026-08-23")
    parser.add_argument("--task", required=True)
    parser.add_argument("--carr-primary", required=True, choices=CARR_CATEGORIES)
    parser.add_argument("--carr-secondary", action="append", default=[], choices=CARR_CATEGORIES)
    parser.add_argument("--liberation-test", required=True)
    parser.add_argument("--execute", action="store_true", help="Explicitly enable governed provider execution. Default is dry-run.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON on stdout instead of human-readable text.")
    args = parser.parse_args()
    outcome = route_and_execute(args.task, CarrRouting(args.carr_primary, tuple(args.carr_secondary), args.liberation_test), execute=args.execute)
    classification, result = outcome["classification"], outcome["dispatch"]
    if args.json:
        print(json.dumps(_to_json_payload(classification, result), ensure_ascii=False))
        return
    print(f"target={classification.target}")
    print(f"outcome={result.outcome}: {result.reason}")
    if result.content:
        print(result.content)


if __name__ == "__main__":
    main()
