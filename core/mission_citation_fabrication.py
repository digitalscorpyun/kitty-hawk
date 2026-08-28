# ==============================================================================
# mission_citation_fabrication.py — smallest governed four-seat mission runner
# ==============================================================================
# MISSION (fixed, not general-purpose): a user reports that a citation
# produced by an AI research/synthesis system appears fabricated or altered.
# This module composes the EXISTING provider
# registry (syndicate_router.SEAT_PROVIDER) into one hardcoded four-stage
# chain and nothing else -- it is not a reusable mission framework.
#
# Chain: ECHO-PROPHET (receipt/evidence adjudication; fact/claim/inference
# separation) -> CONTEXTUAL-CATALYST (failure-mechanism + escalation-condition
# modeling) -> CG-SCRIBE (compression into client-facing language) -> OD-COMPLY
# (output-form/schema validation only -- never truth adjudication). Three
# deterministic checks sit between the seats (never inside CG-SCRIBE or
# OD-COMPLY): an evidence-citation check and a scenario-fidelity check after
# ECHO-PROPHET, and an unsupported-number check plus a second scenario-fidelity
# check after CONTEXTUAL-CATALYST. Findings are preserved in the governed
# evidence/report while the workflow continues (Operation Kitty Hawk, 2026-08-25).
#
# EXTERNAL INFERENCE BOUNDARY (operator ruling, 2026-08-23, correcting an earlier
# multi-vendor architecture that has since been retired): IBM watsonx.ai
# is the ONLY authorized paid external inference service/runtime for the AVM
# Syndicate; IBM Granite is the model family used for the recorded LIVE-003 inference
# (ibm/granite-4-h-small). ECHO-PROPHET (formerly QWEN-ECHO), CONTEXTUAL-CATALYST (formerly
# CTX-GROK), CG-SCRIBE, and OD-COMPLY are governed identities/jurisdictions
# (renamed 2026-08-24, model-agnostic naming), not vendor API contracts --
# all four execute through the same WatsonXClient (client for the watsonx.ai service,
# which then invokes the Granite model), distinguished only by which seat's manifest
# is loaded via set_agent(). WATSONX itself remains a separate, command-invoked
# advisory seat, structurally excluded from this (and every) automated dispatch --
# it is never one of this mission's four stages, even though its service client
# class is what provides the path to Granite inference.
#
# Terminal authority is explicitly OUTSIDE this file:
#   - VS-ENC performs the agentic acceptance review outside this Forge runner.
#   - digitalscorpyun alone authorizes consequential (live, client-facing) use.
# No status value produced here may be read as "accepted." No Vault
# writeback. No autonomous publication or external message. Evidence is
# written only to _debug/mission_citation_fabrication/ (repo-local,
# gitignored).
# ==============================================================================
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from provider_protocol import now_iso
from syndicate_router import SEAT_PROVIDER
from watsonx_client import WatsonXClient

# ---------------------------------------------------------------------------
# Fixed mission topology. Hardcoded to exactly these four seats, in exactly
# this order, for exactly this use case -- never classifier-routed.
# ---------------------------------------------------------------------------
MISSION_SEAT_ORDER: tuple[str, ...] = ("ECHO-PROPHET", "CONTEXTUAL-CATALYST", "CG-SCRIBE", "OD-COMPLY")

# Structural allowlist enforcement: neither Twin Warden (provider-unassigned,
# fail-closed by its own doctrine), MW-ARCHIVE (no registered provider, A1),
# WATSONX/VS-ENC (the advisory/policy seat identities -- command-invoked or
# human-invoked only, never an automated seat), nor any non-watsonx vendor
# name may ever enter this mission's topology -- checked at import time so
# the module cannot even load in a bad state.
FORBIDDEN_SEATS: frozenset[str] = frozenset({"TWIN-WARDEN", "MW-ARCHIVE", "WATSONX", "VS-ENC", "BEDROCK"})

if FORBIDDEN_SEATS & set(MISSION_SEAT_ORDER):
    raise RuntimeError("Mission topology error: a forbidden seat is present in MISSION_SEAT_ORDER.")
for _seat_name in MISSION_SEAT_ORDER:
    if _seat_name not in SEAT_PROVIDER:
        raise RuntimeError(f"Mission seat {_seat_name!r} has no registered provider in syndicate_router.SEAT_PROVIDER.")
    if SEAT_PROVIDER[_seat_name] is not WatsonXClient:
        # Defense-in-depth against exactly the category error this module
        # was rebuilt to correct: if syndicate_router.SEAT_PROVIDER is ever
        # re-wired to a non-watsonx vendor client, this module refuses to
        # load at all rather than silently executing against it.
        raise RuntimeError(
            f"Mission seat {_seat_name!r} is bound to {SEAT_PROVIDER[_seat_name].__name__} in "
            "syndicate_router.SEAT_PROVIDER, not WatsonXClient. IBM watsonx.ai is the only "
            "authorized paid external inference service/runtime for the AVM Syndicate (operator ruling 2026-08-23); "
            "Granite is the model family used for LIVE-003 (ibm/granite-4-h-small)."
        )

EVIDENCE_DIR = Path(os.getenv(
    "MISSION_CITATION_FABRICATION_EVIDENCE_DIR",
    str(Path(__file__).resolve().parents[1] / "_debug" / "mission_citation_fabrication"),
))

ACCEPTANCE_AUTHORITY_NOTE = (
    "Execution-only. Mission acceptance belongs exclusively to VS-ENC's "
    "agentic acceptance review (outside this Forge runner), followed by "
    "digitalscorpyun's explicit authorization. No status value produced by "
    "this module may be interpreted as acceptance."
)

EXECUTION_COMPLETE_STATUS = "execution_complete"
EXECUTION_COMPLETE_WITH_FINDINGS_STATUS = "execution_complete_with_gate_findings"
DEFAULT_REVIEW_STATUS = "not_reviewed"
DEFAULT_OPERATOR_AUTHORIZATION_STATUS = "not_authorized"

REQUIRED_CLIENT_FACING_SECTIONS: tuple[str, ...] = ("WHAT WE VERIFIED:", "WHAT REMAINS UNCERTAIN:", "NEXT STEPS:")


class AgentClient(Protocol):
    system_prompt: str
    current_agent: str
    dispatch_id: str | None
    def ask(self, prompt: str, **kwargs) -> str: ...
    def set_agent(self, agent_name: str) -> None: ...


# ---------------------------------------------------------------------------
# Task prompts. Fixed to this one mission -- not templated for reuse.
# ---------------------------------------------------------------------------
ECHO_PROPHET_TASK_TEMPLATE = """You are ECHO-PROPHET, the AVM Syndicate's evidence-adjudication seat.

CASE: A user reports that a citation produced by an AI research/synthesis system appears fabricated or altered -- the source the AI attributed a claim to may not say what the AI says it says, or may not exist at all in the form cited.

TASK: Read the supplied receipts below. Produce a structured adjudication with exactly four labeled sections:

VERIFIED FACTS:
- Only what the receipts themselves directly establish. Every bullet MUST end with one or more exact receipt_id(s) from the supplied receipts in parentheses, e.g. "(RCPT-CATTO-AUDIT)". Before returning, perform a final citation check: move any statement without an exact receipt_id citation into REPORTED CLAIMS, INFERENCES, or UNRESOLVED QUESTIONS. Never leave an uncited statement under VERIFIED FACTS.

REPORTED CLAIMS:
- Assertions made by a party that are not independently verified by the receipts alone. Name the party only if the receipts themselves name one -- do not assume a lawyer, vendor, or any other role not present in the receipts.

INFERENCES:
- Reasonable interpretations that go beyond the receipts but are not yet claims made by any party.

UNRESOLVED QUESTIONS:
- Anything a receipt leaves genuinely ambiguous, or that cannot be settled from the supplied receipts alone.

Do not invent any fact, source, or citation not present in the receipts. If a receipt is ambiguous, put it in UNRESOLVED QUESTIONS rather than resolving the ambiguity yourself.

RECEIPTS (JSON):
{receipts}
"""

CONTEXTUAL_CATALYST_TASK_TEMPLATE = """You are CONTEXTUAL-CATALYST, the AVM Syndicate's terrain-modeling seat.

You are given ECHO-PROPHET's adjudicated fact/claim/inference/unresolved-question separation for an AI citation-integrity incident (below). Do not re-adjudicate or dispute ECHO-PROPHET's boundaries -- treat them as given.

TASK: Produce a structured analysis with exactly two labeled sections:

FAILURE MECHANISM:
- Name the specific class of failure this incident represents (e.g. ungrounded generation / hallucinated source, retrieval-grounding gap, citation-verification gap, prompt-injection, tool-use error), using only the verified facts provided. Do not state a numeric confidence percentage -- describe your confidence qualitatively (e.g. "well-supported," "tentative") and name what would raise or lower it.

ESCALATION CRITERIA:
- Define concrete, checkable conditions under which this incident must be escalated beyond a routine support response (e.g. pattern across multiple users, regulatory/bar-complaint exposure, repeat occurrence after a prior fix, financial or professional harm to the client).
- Do not invent numerical thresholds, counts, percentages, deadlines, or time windows. Use only thresholds supplied by the receipts or an identified policy artifact. Otherwise state that the escalation threshold requires operator or organizational policy.

ECHO-PROPHET ADJUDICATION:
{adjudication}
"""

CG_SCRIBE_TASK_TEMPLATE = """You are CG-SCRIBE, the AVM Syndicate's compression seat. You prepare language; you do not decide the public move or adjudicate claims.

You are given the verified adjudication and the failure/escalation model below for an AI citation-integrity incident reported by a user. Compress them into a client-facing response using exactly these three labeled sections, and no others:

WHAT WE VERIFIED:
- Plain-language summary of the verified facts only.

WHAT REMAINS UNCERTAIN:
- Plain-language summary of claims/inferences not yet independently verified.

NEXT STEPS:
- Concrete next actions for the client, grounded only in the material above.

Do not assert the disputed citation is valid or invalid beyond what was verified. Do not add any new facts.

VERIFIED ADJUDICATION:
{adjudication}

FAILURE MECHANISM AND ESCALATION MODEL:
{failure_model}
"""

OD_COMPLY_TASK_TEMPLATE = """You are OD-COMPLY, the AVM Syndicate's Output Validation Layer. Your role is strictly output-form and schema validation. You never adjudicate whether the content is true, complete, or correct -- another seat already did that. Do not add, remove, or reinterpret any factual claim.

TASK: Check ONLY whether the client-facing text below contains exactly the three required section headers "WHAT WE VERIFIED:", "WHAT REMAINS UNCERTAIN:", and "NEXT STEPS:", in that order, each followed by non-empty content. Report PASS or FAIL for each header and nothing about the substance of the content.

CLIENT-FACING TEXT:
{client_facing_response}
"""


def _hash_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


EVIDENCE_PACKET_VERSION = "1.0"
ALLOWED_PACKET_SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high", "critical"})
REQUIRED_EVIDENCE_PACKET_FIELDS: tuple[str, ...] = (
    "packet_version", "case_id", "severity", "customer_impact",
    "affected_workflow", "incident_boundary", "verification_scope",
    "provenance_classification", "evidence_sufficiency", "uncertainty",
    "escalation_conditions", "receipts",
)


@dataclass(frozen=True)
class EvidencePacketCheck:
    valid: bool
    findings: tuple[str, ...]
    receipts: tuple[dict, ...]
    metadata: dict
    finding_codes: tuple[str, ...] = ()


def _canonical_packet_hash(packet: dict) -> str:
    """Hash canonical packet JSON; hashes are integrity evidence, not truth."""
    canonical = json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_text(canonical)


def _find_receipt_lineage_violations(text: str | None, packet_receipts: tuple[dict, ...], case_id: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Resolve receipt references and cross-object provenance after adjudication."""
    findings: list[str] = []
    codes: list[str] = []
    known_ids = {r.get("receipt_id") for r in packet_receipts if isinstance(r, dict) and r.get("receipt_id")}
    for receipt_id in sorted(set(re.findall(r"\bRCPT-[A-Z0-9-]+\b", text or ""))):
        if receipt_id not in known_ids:
            findings.append(f"Claim references receipt {receipt_id}, which is absent from the packet ledger.")
            codes.append("CLAIM_RECEIPT_MISSING")
    for index, receipt in enumerate(packet_receipts):
        if not isinstance(receipt, dict):
            continue
        receipt_id = receipt.get("receipt_id") or f"index-{index}"
        receipt_case = receipt.get("case_id")
        provenance = receipt.get("provenance")
        if receipt_case is not None and case_id is not None and receipt_case != case_id:
            findings.append(f"Receipt {receipt_id} belongs to case {receipt_case!r}, not packet case {case_id!r}.")
            codes.append("CROSS_CASE_RECEIPT")
        if isinstance(provenance, dict):
            if provenance.get("case_id") is not None and case_id is not None and provenance.get("case_id") != case_id:
                findings.append(f"Receipt {receipt_id} provenance identifies case {provenance.get('case_id')!r}, not packet case {case_id!r}.")
                codes.append("CROSS_CASE_PROVENANCE")
            if provenance.get("source") is not None and provenance.get("source") != receipt.get("source"):
                findings.append(f"Receipt {receipt_id} provenance source contradicts its declared source.")
                codes.append("PROVENANCE_CONTRADICTION")
            if provenance.get("content_sha256") is not None and provenance.get("content_sha256") != receipt.get("content_sha256"):
                findings.append(f"Receipt {receipt_id} provenance hash contradicts its declared content hash.")
                codes.append("PROVENANCE_HASH_CONTRADICTION")
    return tuple(findings), tuple(codes)


def _validate_evidence_packet(packet: list[dict] | dict) -> EvidencePacketCheck:
    """Validate a versioned packet before provider construction.

    Legacy receipt lists remain accepted for historical compatibility. Versioned
    packets use SHA-256 over UTF-8 content bytes, with no Unicode normalization;
    packet hashes use sorted-key compact JSON. Hashes establish integrity of the
    declared representation, not source truthfulness.
    """
    findings: list[str] = []
    codes: list[str] = []
    if isinstance(packet, list):
        receipts = tuple(packet)
        metadata = {"packet_version": "legacy-list", "schema_status": "legacy_compatible", "case_id": None}
    elif isinstance(packet, dict):
        missing = [field for field in REQUIRED_EVIDENCE_PACKET_FIELDS if field not in packet]
        findings.extend(f"Evidence packet missing required field: {field}" for field in missing)
        codes.extend("PACKET_MISSING_FIELD" for _ in missing)
        version = packet.get("packet_version")
        if version != EVIDENCE_PACKET_VERSION:
            findings.append(f"Unsupported evidence packet version: {version!r}; expected {EVIDENCE_PACKET_VERSION!r}.")
            codes.append("PACKET_UNSUPPORTED_VERSION")
        receipts_value = packet.get("receipts")
        receipts = tuple(receipts_value) if isinstance(receipts_value, list) else ()
        if not isinstance(receipts_value, list):
            findings.append("Evidence packet field 'receipts' must be a list.")
            codes.append("PACKET_RECEIPTS_TYPE")
        metadata = {key: packet.get(key) for key in REQUIRED_EVIDENCE_PACKET_FIELDS if key != "receipts"}
        metadata["packet_version"] = version
        metadata["schema_status"] = "pending"
        metadata["packet_sha256"] = _canonical_packet_hash(packet)
        for field in REQUIRED_EVIDENCE_PACKET_FIELDS:
            if field not in ("packet_version", "receipts") and field in packet:
                value = packet.get(field)
                if not isinstance(value, (str, list, dict)) or (isinstance(value, str) and not value.strip()):
                    findings.append(f"Evidence packet field {field!r} must be non-empty text or a structured value.")
                    codes.append("PACKET_FIELD_VALUE")
        case_id = packet.get("case_id")
        if isinstance(case_id, str) and not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{2,63}", case_id):
            findings.append("Evidence packet case_id is malformed.")
            codes.append("PACKET_CASE_ID_INVALID")
        severity = packet.get("severity")
        if severity not in ALLOWED_PACKET_SEVERITIES:
            findings.append(f"Evidence packet severity is unsupported: {severity!r}.")
            codes.append("PACKET_SEVERITY_INVALID")
    else:
        return EvidencePacketCheck(False, ("Evidence packet must be a legacy receipt list or a mapping.",), (), {"schema_status": "invalid"}, ("PACKET_TOP_LEVEL_TYPE",))

    seen_ids: set[str] = set()
    for index, receipt in enumerate(receipts):
        if not isinstance(receipt, dict):
            findings.append(f"Receipt {index} must be an object.")
            codes.append("RECEIPT_ITEM_TYPE")
            continue
        receipt_id = receipt.get("receipt_id")
        if isinstance(packet, dict) and (not isinstance(receipt_id, str) or not receipt_id.strip()):
            findings.append(f"Receipt {index} has an empty or missing receipt_id.")
            codes.append("RECEIPT_ID_INVALID")
        elif receipt_id and receipt_id in seen_ids:
            findings.append(f"Duplicate receipt_id: {receipt_id}.")
            codes.append("RECEIPT_ID_DUPLICATE")
        elif receipt_id:
            seen_ids.add(receipt_id)
        for field in ("source", "content"):
            if not isinstance(receipt.get(field), str) or not receipt.get(field).strip():
                findings.append(f"Receipt {index} missing non-empty {field!r}.")
                codes.append("RECEIPT_FIELD_INVALID")
        supplied_hash = receipt.get("content_sha256")
        content = receipt.get("content")
        if isinstance(packet, dict):
            if not isinstance(supplied_hash, str) or not supplied_hash:
                findings.append(f"Receipt {receipt_id or index} is missing required content_sha256.")
                codes.append("RECEIPT_HASH_MISSING")
            elif not re.fullmatch(r"[0-9a-fA-F]{64}", supplied_hash):
                findings.append(f"Receipt {receipt_id or index} content_sha256 has invalid length or encoding.")
                codes.append("RECEIPT_HASH_FORMAT")
            if receipt.get("hash_algorithm") != "sha256":
                findings.append(f"Receipt {receipt_id or index} declares unsupported or missing hash algorithm.")
                codes.append("RECEIPT_HASH_ALGORITHM")
        if supplied_hash is not None and isinstance(content, str) and supplied_hash != _hash_text(content):
            findings.append(f"Receipt {receipt_id or index} content_sha256 mismatch: declared hash differs from recomputed SHA-256.")
            codes.append("RECEIPT_HASH_MISMATCH")
        if receipt.get("event_id") is not None and (not isinstance(receipt.get("event_id"), str) or not receipt.get("event_id").strip()):
            findings.append(f"Receipt {receipt_id or index} event_id must be a non-empty string when supplied.")
            codes.append("EVENT_ID_INVALID")
    if not receipts:
        findings.append("Evidence packet must contain at least one receipt.")
        codes.append("PACKET_RECEIPTS_EMPTY")
    metadata["schema_status"] = "valid" if not findings else "invalid"
    return EvidencePacketCheck(not findings, tuple(findings), receipts, metadata, tuple(codes))


@dataclass(frozen=True)
class ReceiptRecord:
    receipt_id: str
    source: str
    content: str
    content_sha256: str
    captured_at: str
    # Optional, backward-compatible: absent from every persisted record that
    # predates this field (deserializes as None, no migration needed).
    # Receipts sharing the same event_id corroborate ONE underlying event
    # rather than counting as independent incidents -- e.g. RCPT-CATTO-AUDIT
    # and RCPT-CATTO-VERIFY both describe the single 2026-08-02 Catto
    # citation-mutation finding, just captured in two different source
    # documents. A receipt with no event_id is treated as its own standalone
    # event (never silently merged with anything).
    event_id: str | None = None


def _preserve_receipts(receipts: list[dict]) -> tuple[ReceiptRecord, ...]:
    records = []
    for i, r in enumerate(receipts):
        if not isinstance(r, dict):
            continue
        content = r.get("content") or ""
        records.append(ReceiptRecord(
            receipt_id=r.get("receipt_id") or f"RCPT-{i + 1:03d}",
            source=r.get("source") or "(missing source)",
            content=content,
            content_sha256=_hash_text(content),
            captured_at=now_iso(),
            event_id=r.get("event_id"),
        ))
    return tuple(records)


def _distinct_events(receipts: tuple[ReceiptRecord, ...]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Group receipts by event_id. A receipt with no event_id is its own
    standalone event, keyed by its own receipt_id -- never forced into a
    group it wasn't explicitly assigned to. Order-preserving."""
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for r in receipts:
        key = r.event_id or r.receipt_id
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r.receipt_id)
    return tuple((key, tuple(groups[key])) for key in order)


@dataclass(frozen=True)
class MissionStageResult:
    mission_id: str
    seat: str
    provider: str
    model_id: str
    input_artifact_hash: str
    output_artifact_hash: str | None
    dispatch_id: str | None
    timestamp: str
    source_receipt_refs: tuple[str, ...]
    outcome: str  # "executed" | "unavailable" | "failed"
    reason: str
    output_text: str | None = None


# A live-flight stall (KH-01, 2026-08-24) never reached this line -- it died
# at watsonx_client's import-time env-var guard. This bound exists for the
# separate, real failure mode it would otherwise leave open: a live call that
# imports fine but then hangs (network stall, IBM-side outage) with no return
# value, which would leave a mission silently stuck instead of failing closed.
# ibm-watsonx-ai's ModelInference.chat() takes no timeout parameter of its
# own, so the bound is enforced here via a worker thread. This does not
# cancel the underlying network call (Python threads can't be killed), only
# the mission's wait for it -- a genuinely slow-but-eventually-successful
# call may still write to the usage ledger after this function has already
# returned "failed". First-pass value; adjust if real traffic needs longer.
STAGE_TIMEOUT_SECONDS = 180


def _run_stage(mission_id: str, seat_name: str, prompt: str, source_receipt_refs: tuple[str, ...], *, client_override: AgentClient | None = None, timeout_seconds: float = STAGE_TIMEOUT_SECONDS) -> MissionStageResult:
    input_hash = _hash_text(prompt)
    timestamp = now_iso()
    if client_override is not None:
        client = client_override
        provider_name = type(client).__name__
    else:
        provider_cls = SEAT_PROVIDER[seat_name]  # always WatsonXClient -- enforced at import time above
        provider_name = provider_cls.__name__
        try:
            client = provider_cls()
        except Exception as exc:
            # WatsonXClient does not raise provider_protocol.ProviderUnavailableError
            # -- its credential check is a process-level fail-fast guard at
            # watsonx_client.py's IMPORT time (REQUIRED_VARS -> sys.exit(1)), not a
            # per-instance one, so a real WATSONX_* misconfiguration is normally
            # caught long before this line runs. This except is defensive only: if
            # construction ever fails for any other reason, the stage fails closed
            # rather than crashing the whole mission run uncontrolled.
            return MissionStageResult(mission_id, seat_name, provider_name, "n/a", input_hash, None, None, timestamp, source_receipt_refs, "unavailable", f"{type(exc).__name__}: {exc}")
    client.set_agent(seat_name)
    dispatch_id = f"{seat_name}:{uuid.uuid4().hex[:8]}"
    client.dispatch_id = dispatch_id
    model_id = getattr(client, "model_id", "unknown")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            output_text = pool.submit(client.ask, prompt).result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        return MissionStageResult(mission_id, seat_name, provider_name, model_id, input_hash, None, dispatch_id, timestamp, source_receipt_refs, "failed", f"Stage exceeded {timeout_seconds}s with no response (live call may still be in flight in the background).")
    except Exception as exc:
        # A real in-flight failure, distinct from the construction-time
        # "unavailable" case above -- caught narrowly around ask() only.
        return MissionStageResult(mission_id, seat_name, provider_name, model_id, input_hash, None, dispatch_id, timestamp, source_receipt_refs, "failed", f"{type(exc).__name__}: {exc}")
    return MissionStageResult(mission_id, seat_name, provider_name, model_id, input_hash, _hash_text(output_text), dispatch_id, timestamp, source_receipt_refs, "executed", "Stage executed.", output_text)


@dataclass(frozen=True)
class SchemaCheck:
    valid: bool
    findings: tuple[str, ...]


def _validate_output_schema(client_facing_response: str) -> SchemaCheck:
    """Deterministic, form-only gate -- the real pass/fail authority for
    schema compliance. OD-COMPLY's own LLM response (stage 4's output_text)
    is advisory only and is never consulted here, so no LLM free-text
    output can ever change whether the mission's schema check passes."""
    findings: list[str] = []
    text = client_facing_response or ""
    if not text.strip():
        findings.append("Client-facing response is empty.")
        return SchemaCheck(False, tuple(findings))
    positions = []
    for section in REQUIRED_CLIENT_FACING_SECTIONS:
        idx = text.find(section)
        if idx == -1:
            findings.append(f"Missing required section header: {section!r}")
        else:
            positions.append((idx, section))
    if len(positions) == len(REQUIRED_CLIENT_FACING_SECTIONS):
        ordered = tuple(section for _, section in sorted(positions))
        if ordered != REQUIRED_CLIENT_FACING_SECTIONS:
            findings.append("Required section headers are present but out of order.")
        sorted_positions = sorted(positions)
        for i, (idx, section) in enumerate(sorted_positions):
            end = sorted_positions[i + 1][0] if i + 1 < len(sorted_positions) else len(text)
            if not text[idx + len(section):end].strip():
                findings.append(f"Section {section!r} has no content.")
    return SchemaCheck(valid=not findings, findings=tuple(findings))


# =============================================================================
# Deterministic pre-composition gates (Operation Kitty Hawk, 2026-08-24).
# Each is a pure, mechanical pattern/structure check -- none of them make a
# truth judgment, and none of them ever run inside CG-SCRIBE or OD-COMPLY.
# They fail run_mission() closed before CG-SCRIBE composes client-facing
# text, per the operator's explicit "fail closed before CG-SCRIBE; do not
# rely on CG-SCRIBE silently removing the defect" instruction.
# =============================================================================

_ECHO_PROPHET_SECTION_MARKERS = ("VERIFIED FACTS", "REPORTED CLAIMS", "CLAIMS", "INFERENCES", "UNRESOLVED QUESTIONS")


def _find_uncited_verified_facts(echo_prophet_output: str, receipt_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Deterministic check over ECHO-PROPHET's VERIFIED FACTS section: every
    non-empty bullet must contain at least one of this mission's real
    receipt_ids. A "verified fact" with no receipt_id anywhere in it is, by
    construction, a claim of verification with nothing supporting it --
    exactly the finding-level evidence-ledger requirement this gate exists
    to enforce. Not a truth check: a cited bullet can still be wrong, but an
    uncited one can never pass."""
    text = echo_prophet_output or ""
    upper = text.upper()
    start_idx = upper.find("VERIFIED FACTS")
    if start_idx == -1:
        return ("No VERIFIED FACTS section found in ECHO-PROPHET's output.",)
    nl = text.find("\n", start_idx)
    start = nl + 1 if nl != -1 else len(text)
    end = len(text)
    for marker in _ECHO_PROPHET_SECTION_MARKERS:
        if marker == "VERIFIED FACTS":
            continue
        idx = upper.find(marker, start)
        if idx != -1:
            end = min(end, idx)
    section = text[start:end]
    findings: list[str] = []
    for line in section.splitlines():
        stripped = line.strip().lstrip("-*").strip()
        if not stripped:
            continue
        if not any(rid in line for rid in receipt_ids):
            findings.append(stripped)
    return tuple(findings)


_UNSUPPORTED_NUMBER_UNITS = (
    "user", "users", "customer", "customers", "incident", "incidents",
    "occurrence", "occurrences", "report", "reports", "complaint", "complaints",
    "day", "days", "week", "weeks", "month", "months", "hour", "hours",
    "time", "times", "instance", "instances",
)
_SOURCE_MARKERS = (
    "policy", "rcpt-", "receipt", "documented", "cites", "citing",
    "identified source", "organizational policy", "operator policy",
    "policy artifact",
)
_NUMBER_WORD = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
_THRESHOLD_PATTERN = re.compile(
    rf"\b{_NUMBER_WORD}\b[^.]{{0,40}}\b(?:{'|'.join(re.escape(u) for u in _UNSUPPORTED_NUMBER_UNITS)})\b"
    rf"|\b(?:{'|'.join(re.escape(u) for u in _UNSUPPORTED_NUMBER_UNITS)})\b[^.]{{0,40}}\b{_NUMBER_WORD}\b",
    re.IGNORECASE,
)
# Deliberately separate from _THRESHOLD_PATTERN: a trailing \b after a
# literal "%" fails to match when the percentage is followed by punctuation
# (e.g. "(70%),") because "%" and ")" are both non-word characters -- no
# boundary exists between them. That gap is exactly how both real 2026-08-23
# runs' "(70%)" confidence figure slipped past an earlier version of this
# check. This pattern needs no trailing boundary.
_PERCENTAGE_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")


def _find_unsupported_numbers(stage_output: str) -> tuple[str, ...]:
    """Deterministic, mechanical pattern match across an ENTIRE seat output
    -- not just its ESCALATION CRITERIA section. The confirmed 2026-08-23
    defect's confidence percentage sits in the preceding FAILURE MECHANISM
    section; scanning only from the "ESCALATION CRITERIA" marker onward (an
    earlier version of this function) silently skipped right past it. Flags
    any percentage or count/time-window threshold with no source marker (a
    receipt or policy reference) in a nearby window. Cannot judge whether a
    *sourced* number is correct -- only whether one was asserted with
    nothing backing it."""
    text = stage_output or ""
    findings: list[str] = []
    for pattern in (_THRESHOLD_PATTERN, _PERCENTAGE_PATTERN):
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - 60):min(len(text), match.end() + 60)].strip()
            if not any(marker in window.lower() for marker in _SOURCE_MARKERS):
                findings.append(window)
    return tuple(findings)


# Obsolete scaffolding this module's prompts once hardcoded ("lawyer,
# workspace, vendor") from its original fabricated-legal-citation scenario.
# The Syllo Customer Success use case has no lawyer, no bar complaint, and
# (usually) no named vendor -- this watchlist catches that language leaking
# into a seat's output even after the prompt template itself was softened,
# without banning the words outright: a term is only a violation when the
# mission's own receipts never mention it, so a future mission whose
# receipts genuinely do involve a lawyer or a named vendor is unaffected.
_OBSOLETE_SCENARIO_TERMS = ("lawyer", "legal work", "bar complaint", "regulatory complaint", "vendor")


def _find_scenario_fidelity_violations(stage_output: str, receipts_text: str) -> tuple[str, ...]:
    """Contract-driven, not hardcoded to one incident: flags a watchlist
    term only when it appears in the seat's output but nowhere in the
    mission's actual receipt packet."""
    output_lower = (stage_output or "").lower()
    receipts_lower = (receipts_text or "").lower()
    return tuple(
        f"'{term}' appears in the seat output but not in the receipt packet"
        for term in _OBSOLETE_SCENARIO_TERMS
        if term in output_lower and term not in receipts_lower
    )


@dataclass(frozen=True)
class MissionResult:
    mission_id: str
    created_at: str
    receipts: tuple[ReceiptRecord, ...]
    stages: tuple[MissionStageResult, ...]
    client_facing_response: str | None
    od_comply_notes: str | None
    schema_valid: bool | None
    schema_findings: tuple[str, ...]
    status: str
    vs_enc_review_status: str = DEFAULT_REVIEW_STATUS
    operator_authorization_status: str = DEFAULT_OPERATOR_AUTHORIZATION_STATUS
    vault_writeback: None = None
    # Findings from deterministic checks. They are preserved whether the
    # workflow continues to completion or a provider/stage failure later halts.
    gate_findings: tuple[str, ...] = ()
    packet_metadata: dict | None = None


def _write_evidence(mission_id: str, result: MissionResult) -> None:
    # Repo-local only (_debug/ is gitignored). Never Vault. Never
    # committed. A write failure must not take down a mission whose real
    # work already completed -- same discipline as record_usage()/
    # _record_dispatch() elsewhere in this package.
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE_DIR / f"{mission_id}.json"
        path.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
        report_path = EVIDENCE_DIR / f"{mission_id}.md"
        report_path.write_text(_render_customer_success_report(result), encoding="utf-8")
    except OSError as exc:
        print(f"Mission evidence write failed (mission result itself is still returned): {exc}")


def _table_cell(value: object) -> str:
    """Keep generated values inside one readable Markdown table cell."""
    return str(value if value is not None else "—").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _extract_section(text: str | None, header: str, other_headers: tuple[str, ...]) -> str:
    """Pull one labeled section's body out of a seat's free-text output.
    Same mechanical marker-search approach as the gates above -- not a
    parser, just a bounded substring extraction for report rendering."""
    t = text or ""
    idx = t.find(header)
    if idx == -1:
        return ""
    start = idx + len(header)
    end = len(t)
    for h in other_headers:
        i = t.find(h, start)
        if i != -1:
            end = min(end, i)
    return t[start:end].strip()


def _render_customer_success_report(result: MissionResult) -> str:
    """Render the machine evidence as a Customer Success diagnostic record.

    This is a view of the governed trace, not a new inference layer. Model
    outputs are reproduced and visibly labeled as drafts; rendering never
    changes mission status or grants acceptance. Leads with case identity
    and every status field so a reader can never mistake `execution_complete`
    for operator acceptance -- that boundary is stated explicitly, not left
    implicit in a status string.
    """
    verified = _extract_section(result.client_facing_response, "WHAT WE VERIFIED:", REQUIRED_CLIENT_FACING_SECTIONS[1:])
    uncertain = _extract_section(result.client_facing_response, "WHAT REMAINS UNCERTAIN:", (REQUIRED_CLIENT_FACING_SECTIONS[2],))
    next_action = _extract_section(result.client_facing_response, "NEXT STEPS:", ())

    lines = [
        f"# Customer Success Incident Record — {result.mission_id}",
        "",
        f"- **Case ID:** `{result.mission_id}`",
        f"- **Execution status:** `{result.status}`",
        f"- **VS-ENC review status:** `{result.vs_enc_review_status}`",
        f"- **Operator authorization status:** `{result.operator_authorization_status}`",
        f"- **Evidence packet version:** `{(result.packet_metadata or {}).get('packet_version', 'legacy-list')}`",
        f"- **Evidence packet schema:** `{(result.packet_metadata or {}).get('schema_status', 'unknown')}`",
        "",
        "> **Review state:** `execution_complete` means the mission's stages ran to "
        "completion -- it is NOT operator acceptance and NOT a claim that this record "
        "is approved for client delivery. Acceptance requires VS-ENC's agentic review "
        "and digitalscorpyun's explicit authorization, tracked separately above.",
        "",
    ]

    if result.gate_findings:
        heading = "## Gate findings (workflow continued with findings)" if result.status == EXECUTION_COMPLETE_WITH_FINDINGS_STATUS else "## Gate findings (mission halted)"
        lines.extend([heading, ""])
        lines.extend(f"- {finding}" for finding in result.gate_findings)
        lines.append("")

    lines.extend([
        "## Verified Incident",
        "",
        verified or "No customer-facing verified-incident summary was produced (mission halted before CG-SCRIBE, or CG-SCRIBE produced no matching section).",
        "",
        "## Supporting Receipts",
        "",
        f"{len(result.receipts)} receipt(s) preserved for this mission. Full ledger with source, hash, and content is in **Receipt ledger** below.",
        "",
        "## Affected Evidence / Events",
        "",
    ])
    for event_key, member_ids in _distinct_events(result.receipts):
        if len(member_ids) > 1:
            lines.append(f"- **Event `{event_key}`** — corroborated by {len(member_ids)} receipts: {', '.join(member_ids)}")
        else:
            lines.append(f"- **Event `{event_key}`** — 1 receipt: {member_ids[0]}")
    if not result.receipts:
        lines.append("- No receipts were supplied.")
    lines.extend([
        "",
        "## Customer Impact",
        "",
        "Not separately assessed by this mission's fixed four-stage pipeline; see Verified Incident above.",
        "",
        "## Remaining Uncertainty",
        "",
        uncertain or "No remaining-uncertainty summary was produced (mission halted before CG-SCRIBE, or CG-SCRIBE produced no matching section).",
        "",
        "## Recommended Next Action",
        "",
        next_action or "No next-action summary was produced (mission halted before CG-SCRIBE, or CG-SCRIBE produced no matching section).",
        "",
        "---",
        "",
        "## Mission summary",
        "",
        f"- **Created:** {result.created_at}",
        f"- **Schema valid:** `{result.schema_valid}`",
        f"- **Vault writeback:** `{result.vault_writeback}`",
        f"- **Receipts:** {len(result.receipts)}",
        f"- **Stages completed:** {sum(stage.outcome == 'executed' for stage in result.stages)}/{len(MISSION_SEAT_ORDER)}",
        "",
        "## Customer-facing draft",
        "",
        "> **Human review required.** This is CG-SCRIBE's model-generated draft, reproduced without editorial correction.",
        "",
        result.client_facing_response or "No customer-facing response was produced because the mission halted.",
        "",
        "## Compliance review",
        "",
        f"- **Deterministic schema result:** `{result.schema_valid}`",
    ])
    if result.schema_findings:
        lines.extend(f"- {finding}" for finding in result.schema_findings)
    else:
        lines.append("- No deterministic schema findings.")
    lines.extend([
        "",
        "### OD-COMPLY notes",
        "",
        result.od_comply_notes or "OD-COMPLY did not execute.",
        "",
        "## Governed workflow trace",
        "",
        "| Seat | Outcome | Provider | Model | Dispatch ID | Reason |",
        "|---|---|---|---|---|---|",
    ])
    for stage in result.stages:
        lines.append(
            "| " + " | ".join(_table_cell(value) for value in (
                stage.seat, stage.outcome, stage.provider, stage.model_id,
                stage.dispatch_id, stage.reason,
            )) + " |"
        )
    lines.extend(["", "## Receipt ledger", ""])
    for receipt in result.receipts:
        lines.extend([
            f"### {receipt.receipt_id}",
            "",
            f"- **Source:** `{receipt.source}`",
            f"- **Event ID:** `{receipt.event_id or '(standalone -- no shared event)'}`",
            f"- **SHA-256:** `{receipt.content_sha256}`",
            f"- **Captured:** {receipt.captured_at}",
            "",
            "```text",
            receipt.content,
            "```",
            "",
        ])
    lines.extend(["## Per-seat diagnostic outputs", ""])
    for stage in result.stages:
        lines.extend([
            f"### {stage.seat}",
            "",
            f"**Outcome:** `{stage.outcome}`  ",
            f"**Source receipts:** {', '.join(stage.source_receipt_refs) or 'None'}",
            "",
            stage.output_text or f"No output was produced. Reason: {stage.reason}",
            "",
        ])
    lines.extend([
        "## Decision boundary",
        "",
        ACCEPTANCE_AUTHORITY_NOTE,
        "",
    ])
    return "\n".join(lines)


def run_mission(receipts: list[dict] | dict, *, mission_id: str | None = None, clients: dict[str, AgentClient] | None = None, authorize_live: bool = False) -> MissionResult:
    """Execution-only. See ACCEPTANCE_AUTHORITY_NOTE: no return value from
    this function is an acceptance decision.

    `clients` is a test/offline injection seam only -- the same shape as
    dispatch()'s `client` parameter in syndicate_router.py. Any seat absent
    from `clients` is constructed from the REAL SEAT_PROVIDER registry
    (WatsonXClient for all four mission seats), which requires
    `authorize_live=True` (a separate, explicit operator authorization) or
    this function refuses before touching any provider."""
    packet_check = _validate_evidence_packet(receipts)
    if isinstance(receipts, list) and not receipts:
        raise ValueError("run_mission requires at least one supplied receipt.")
    clients = clients or {}
    unknown = set(clients) - set(MISSION_SEAT_ORDER)
    if unknown:
        raise ValueError(f"clients override names seats outside MISSION_SEAT_ORDER: {sorted(unknown)}")

    live_needed = any(seat not in clients for seat in MISSION_SEAT_ORDER)
    if live_needed and not authorize_live:
        raise PermissionError(
            "Live provider execution requires authorize_live=True, granted only after "
            "explicit digitalscorpyun authorization for this run. No stage was invoked."
        )

    mission_id = mission_id or f"MISSION-CITFAB-{uuid.uuid4().hex[:12]}"
    receipt_records = _preserve_receipts([r for r in packet_check.receipts if isinstance(r, dict)])
    receipt_ids = tuple(r.receipt_id for r in receipt_records)
    if not packet_check.valid:
        result = MissionResult(
            mission_id, now_iso(), receipt_records, (), None, None, None, (),
            "halted_invalid_evidence_packet", packet_metadata=packet_check.metadata,
            gate_findings=tuple(f"Evidence-packet schema discrepancy: {finding}" for finding in packet_check.findings),
        )
        _write_evidence(mission_id, result)
        return result
    stages: list[MissionStageResult] = []
    gate_findings: list[str] = []

    def halt(status: str, additional_findings: tuple[str, ...] = ()) -> MissionResult:
        findings = tuple(gate_findings) + tuple(additional_findings)
        result = MissionResult(mission_id, now_iso(), receipt_records, tuple(stages), None, None, None, (), status, gate_findings=findings, packet_metadata=packet_check.metadata)
        _write_evidence(mission_id, result)
        return result

    receipts_payload = json.dumps(
        [{"receipt_id": r.receipt_id, "source": r.source, "content": r.content} for r in receipt_records],
        ensure_ascii=False, sort_keys=True,
    )

    stage1 = _run_stage(mission_id, "ECHO-PROPHET", ECHO_PROPHET_TASK_TEMPLATE.format(receipts=receipts_payload), receipt_ids, client_override=clients.get("ECHO-PROPHET"))
    stages.append(stage1)
    if stage1.outcome != "executed":
        return halt(f"halted_echo_prophet_{stage1.outcome}")

    uncited = _find_uncited_verified_facts(stage1.output_text, receipt_ids)
    gate_findings.extend(f"ECHO-PROPHET citation discrepancy: {finding}" for finding in uncited)

    lineage_receipts = tuple(
        dict(raw, receipt_id=raw.get("receipt_id") or receipt_records[index].receipt_id)
        for index, raw in enumerate(packet_check.receipts)
        if isinstance(raw, dict) and index < len(receipt_records)
    )
    lineage_findings, lineage_codes = _find_receipt_lineage_violations(stage1.output_text, lineage_receipts, packet_check.metadata.get("case_id"))
    gate_findings.extend(f"ECHO-PROPHET receipt-lineage discrepancy [{code}]: {finding}" for code, finding in zip(lineage_codes, lineage_findings))

    scenario1 = _find_scenario_fidelity_violations(stage1.output_text, receipts_payload)
    gate_findings.extend(f"ECHO-PROPHET scenario-fidelity discrepancy: {finding}" for finding in scenario1)

    stage2 = _run_stage(mission_id, "CONTEXTUAL-CATALYST", CONTEXTUAL_CATALYST_TASK_TEMPLATE.format(adjudication=stage1.output_text), receipt_ids, client_override=clients.get("CONTEXTUAL-CATALYST"))
    stages.append(stage2)
    if stage2.outcome != "executed":
        return halt(f"halted_contextual_catalyst_{stage2.outcome}")

    unsupported = _find_unsupported_numbers(stage2.output_text)
    gate_findings.extend(f"CONTEXTUAL-CATALYST unsupported-number discrepancy: {finding}" for finding in unsupported)

    scenario2 = _find_scenario_fidelity_violations(stage2.output_text, receipts_payload)
    gate_findings.extend(f"CONTEXTUAL-CATALYST scenario-fidelity discrepancy: {finding}" for finding in scenario2)

    stage3 = _run_stage(mission_id, "CG-SCRIBE", CG_SCRIBE_TASK_TEMPLATE.format(adjudication=stage1.output_text, failure_model=stage2.output_text), receipt_ids, client_override=clients.get("CG-SCRIBE"))
    stages.append(stage3)
    if stage3.outcome != "executed":
        return halt(f"halted_cg_scribe_{stage3.outcome}")

    # Frozen from here on. OD-COMPLY (stage 4) may never mutate this value --
    # its own output is captured separately as od_comply_notes below.
    client_facing_response = stage3.output_text

    stage4 = _run_stage(mission_id, "OD-COMPLY", OD_COMPLY_TASK_TEMPLATE.format(client_facing_response=client_facing_response), receipt_ids, client_override=clients.get("OD-COMPLY"))
    stages.append(stage4)
    if stage4.outcome != "executed":
        return halt(f"halted_od_comply_{stage4.outcome}")

    schema = _validate_output_schema(client_facing_response)

    result = MissionResult(
        mission_id=mission_id,
        created_at=now_iso(),
        receipts=receipt_records,
        stages=tuple(stages),
        client_facing_response=client_facing_response,
        od_comply_notes=stage4.output_text,
        schema_valid=schema.valid,
        schema_findings=schema.findings,
        status=EXECUTION_COMPLETE_WITH_FINDINGS_STATUS if gate_findings else EXECUTION_COMPLETE_STATUS,
        gate_findings=tuple(gate_findings),
        packet_metadata=packet_check.metadata,
    )
    _write_evidence(mission_id, result)
    return result
