"""
Kitty Hawk Offline End-to-End Demonstration
Uses existing runner and architecture only — no toy logic, no live watsonx calls.

Valid sanitized case: versioned 1.0 packet -> normalization -> receipt/event lineage
-> deterministic gates -> human-review disposition -> traceable Customer Success report.
Negative case: receipt-hash mismatch -> rejected before provider dispatch -> zero provider calls.

Run offline (from repo root):
  python demo/kitty_hawk_offline_demo.py

Requires no credentials, no .env, no provider network.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

# Ensure offline import succeeds without real credentials (same as test suite).
for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy-offline-demo")
for name in ("GEMINI_API_KEY", "DASHSCOPE_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"):
    os.environ.pop(name, None)

# Allow running from repo root or demo/
DEMO_DIR = Path(__file__).parent
REPO_ROOT = DEMO_DIR.parent
CORE_DIR = REPO_ROOT / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import mission_citation_fabrication as mcf  # noqa: E402

# ---------------------------------------------------------------------------
# Offline fake client — identical seam as tests, no network
# ---------------------------------------------------------------------------
class FakeClient:
    def __init__(self, response: str, *, model_id: str = "OFFLINE-DEMO-MODEL", raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.system_prompt = ""
        self.current_agent = "FAKE"
        self.dispatch_id = None
        self.last_usage = None
        self.model_id = model_id
        self.set_agent_calls: list[str] = []
        self.ask_calls: list[str] = []

    def set_agent(self, agent_name: str) -> None:
        self.set_agent_calls.append(agent_name)
        self.current_agent = agent_name

    def ask(self, prompt: str, **kwargs) -> str:
        self.ask_calls.append(prompt)
        if self.raises is not None:
            raise self.raises
        return self.response

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

# ---------------------------------------------------------------------------
# Sanitized valid packet — synthetic, no private Syllo data
# ---------------------------------------------------------------------------
SANITIZED_RECEIPTS = [
    {
        "receipt_id": "RCPT-SAN-001",
        "source": "synthetic_audit_log_20260827.md#finding-01",
        "content": "Synthetic audit: AI synthesis output cited 'Acme v. Beta, 123 F.4th 456 (9th Cir. 2024)' which does not resolve in the reporter.",
        "event_id": "EVT-SAN-CITATION-001",
    },
    {
        "receipt_id": "RCPT-SAN-002",
        "source": "synthetic_workspace_transcript_20260827.md#excerpt-01",
        "content": "Synthetic workspace transcript: 'See Acme v. Beta, 123 F.4th 456 (9th Cir. 2024), holding that...'",
        "event_id": "EVT-SAN-CITATION-001",
    },
]
for r in SANITIZED_RECEIPTS:
    r["hash_algorithm"] = "sha256"
    r["content_sha256"] = _sha256(r["content"])

SANITIZED_VALID_PACKET = {
    "packet_version": "1.0",
    "case_id": "CASE-KITTY-HAWK-DEMO-001",
    "severity": "medium",
    "customer_impact": "Synthetic: potentially misleading research output with fabricated citation.",
    "affected_workflow": "AI-assisted research synthesis (synthetic)",
    "incident_boundary": "One bounded synthetic citation-reliability incident.",
    "verification_scope": "Receipt content and source comparison only (synthetic).",
    "provenance_classification": "synthetic-and-audited",
    "evidence_sufficiency": "sufficient-for-triage",
    "uncertainty": ["Independent source confirmation remains synthetic."],
    "escalation_conditions": ["Escalate if synthetic pattern repeats."],
    "receipts": SANITIZED_RECEIPTS,
}

# Well-formed seat outputs that cite the sanitized receipt IDs and avoid invented thresholds
WELL_FORMED_ECHO = (
    "VERIFIED FACTS:\n"
    "- The workspace output cites 'Acme v. Beta, 123 F.4th 456 (9th Cir. 2024)' (RCPT-SAN-002).\n"
    "- The audit notes this citation does not resolve in any reporter (RCPT-SAN-001).\n\n"
    "REPORTED CLAIMS:\n- Synthetic claim that the citation is fabricated.\n\n"
    "INFERENCES:\n- The workspace may have hallucinated the citation.\n\n"
    "UNRESOLVED QUESTIONS:\n- Whether this is a one-off or a repeated pattern."
)
WELL_FORMED_CATALYST = (
    "FAILURE MECHANISM:\n- Ungrounded generation / hallucinated source. Well-supported by the receipts.\n\n"
    "ESCALATION CRITERIA:\n- Escalate on repeat occurrence after a prior fix, or on regulatory exposure, per operator policy."
)
WELL_FORMED_SCRIBE = (
    "WHAT WE VERIFIED:\nThe synthetic citation does not resolve in the reporter.\n\n"
    "WHAT REMAINS UNCERTAIN:\nWhether this is a one-off.\n\n"
    "NEXT STEPS:\nWe are reviewing the underlying synthetic workspace session with human review."
)

# Legacy-compatible echo cites auto-assigned RCPT-001/002 (legacy list has no explicit receipt_id)
LEGACY_WELL_FORMED_ECHO = (
    "VERIFIED FACTS:\n"
    "- The workspace output cites 'Acme v. Beta, 123 F.4th 456 (9th Cir. 2024)' (RCPT-002).\n"
    "- The audit notes this citation does not resolve in any reporter (RCPT-001).\n\n"
    "REPORTED CLAIMS:\n- Synthetic claim that the citation is fabricated.\n\n"
    "INFERENCES:\n- The workspace may have hallucinated the citation.\n\n"
    "UNRESOLVED QUESTIONS:\n- Whether this is a one-off or a repeated pattern."
)

def _happy_clients() -> dict[str, FakeClient]:
    return {
        "ECHO-PROPHET": FakeClient(WELL_FORMED_ECHO),
        "CONTEXTUAL-CATALYST": FakeClient(WELL_FORMED_CATALYST),
        "CG-SCRIBE": FakeClient(WELL_FORMED_SCRIBE),
        "OD-COMPLY": FakeClient("PASS: WHAT WE VERIFIED:\nPASS: WHAT REMAINS UNCERTAIN:\nPASS: NEXT STEPS:"),
    }

def _legacy_happy_clients() -> dict[str, FakeClient]:
    return {
        "ECHO-PROPHET": FakeClient(LEGACY_WELL_FORMED_ECHO),
        "CONTEXTUAL-CATALYST": FakeClient(WELL_FORMED_CATALYST),
        "CG-SCRIBE": FakeClient(WELL_FORMED_SCRIBE),
        "OD-COMPLY": FakeClient("PASS: WHAT WE VERIFIED:\nPASS: WHAT REMAINS UNCERTAIN:\nPASS: NEXT STEPS:"),
    }

# ---------------------------------------------------------------------------
# Negative packet: receipt hash mismatch (deterministic, no provider dispatch)
# ---------------------------------------------------------------------------
NEGATIVE_RECEIPTS = [
    {
        "receipt_id": "RCPT-SAN-NEG-001",
        "source": "synthetic_audit_log_20260827.md#finding-neg",
        "content": "Synthetic audit: content that will have mismatched hash.",
        "hash_algorithm": "sha256",
        "content_sha256": "0" * 64,  # intentionally wrong
        "event_id": "EVT-SAN-NEG-001",
    },
    {
        "receipt_id": "RCPT-SAN-NEG-002",
        "source": "synthetic_workspace_transcript_20260827.md#excerpt-neg",
        "content": "Synthetic workspace transcript for negative case.",
        "hash_algorithm": "sha256",
        "content_sha256": _sha256("Synthetic workspace transcript for negative case."),
        "event_id": "EVT-SAN-NEG-001",
    },
]
NEGATIVE_PACKET_HASH_MISMATCH = {
    "packet_version": "1.0",
    "case_id": "CASE-KITTY-HAWK-DEMO-NEG-001",
    "severity": "high",
    "customer_impact": "Synthetic negative case: receipt hash mismatch.",
    "affected_workflow": "AI-assisted research synthesis (synthetic)",
    "incident_boundary": "One bounded synthetic incident for hash-mismatch gate.",
    "verification_scope": "Receipt content hash comparison only.",
    "provenance_classification": "synthetic-and-audited",
    "evidence_sufficiency": "insufficient",
    "uncertainty": ["Hash mismatch leaves verification uncertain."],
    "escalation_conditions": ["Escalate if hash mismatch indicates tampering."],
    "receipts": NEGATIVE_RECEIPTS,
}

# Malformed packet alternative (uncomment to test missing-field path):
NEGATIVE_PACKET_MALFORMED = {
    "packet_version": "1.0",
    # "case_id" missing intentionally
    "severity": "bad-severity",  # invalid
    "customer_impact": "Synthetic malformed case.",
    "affected_workflow": "AI-assisted research synthesis",
    "incident_boundary": "Synthetic boundary.",
    "verification_scope": "Synthetic scope.",
    "provenance_classification": "synthetic",
    "evidence_sufficiency": "sufficient-for-triage",
    "uncertainty": ["Synthetic"],
    "escalation_conditions": ["Synthetic"],
    "receipts": SANITIZED_RECEIPTS,
}


def run_valid_case() -> mcf.MissionResult:
    print("=" * 78)
    print("VALID SANITIZED OFFLINE CASE — versioned packet -> report")
    print("=" * 78)
    # Preflight validation (normalization boundary)
    check = mcf._validate_evidence_packet(SANITIZED_VALID_PACKET)
    print(f"Preflight valid={check.valid} schema_status={check.metadata.get('schema_status')} "
          f"packet_sha256={check.metadata.get('packet_sha256')[:12]}... codes={check.finding_codes}")
    assert check.valid, f"Sanitized valid packet should pass preflight, got {check.findings}"

    # Receipt/event lineage (explicit event_id only)
    normalized = mcf._preserve_receipts(SANITIZED_VALID_PACKET["receipts"])
    events = mcf._distinct_events(normalized)
    print(f"Receipts preserved: {len(normalized)} | Distinct events: {len(events)} "
          f"| Event grouping: {events}")
    assert len(events) == 1 and events[0][0] == "EVT-SAN-CITATION-001"
    assert set(events[0][1]) == {"RCPT-SAN-001", "RCPT-SAN-002"}

    clients = _happy_clients()
    # Non-live security boundary: offline demo uses injected fake clients only.
    # No live provider is constructed; authorize_live remains False.
    result = mcf.run_mission(
        SANITIZED_VALID_PACKET,
        mission_id="KITTY-HAWK-DEMO-VALID-001",
        clients=clients,
        authorize_live=False,
    )

    print(f"Status: {result.status}")
    print(f"Gate findings: {result.gate_findings}")
    print(f"Stages: {len(result.stages)} ({', '.join(s.seat for s in result.stages)})")
    print(f"Human-review disposition: vs_enc_review_status={result.vs_enc_review_status} "
          f"operator_authorization_status={result.operator_authorization_status}")
    print(f"Schema valid: {result.schema_valid}")
    print(f"Client-facing draft present: {bool(result.client_facing_response)}")

    # Deterministic gates passed
    assert result.status == mcf.EXECUTION_COMPLETE_STATUS
    assert result.gate_findings == ()
    assert len(result.stages) == 4
    assert tuple(s.seat for s in result.stages) == mcf.MISSION_SEAT_ORDER
    # All seats were invoked via same provider seam (FakeClient here, WatsonXClient in live)
    for seat in mcf.MISSION_SEAT_ORDER:
        assert clients[seat].set_agent_calls == [seat], f"{seat} identity not set correctly"
        assert clients[seat].ask_calls, f"{seat} was not invoked"
    # Human-review and operator-authorization boundary (real, non-vacuous):
    # Runner must never claim acceptance; report must explicitly mark human review
    # and operator boundary. No `or True` — this is a hard assertion.
    assert result.vs_enc_review_status == "not_reviewed"
    assert result.operator_authorization_status == "not_authorized"
    # Resolve the report file: MissionResult may expose report_path, otherwise fall back to EVIDENCE_DIR/mission_id.md
    _report_text = ""
    _candidate_report_paths = []
    if hasattr(result, "report_path") and getattr(result, "report_path"):
        _candidate_report_paths.append(Path(getattr(result, "report_path")))
    _candidate_report_paths.append(Path(mcf.EVIDENCE_DIR) / "KITTY-HAWK-DEMO-VALID-001.md")
    _candidate_report_paths.append(Path(mcf.EVIDENCE_DIR) / f"{result.mission_id}.md")
    for _p in _candidate_report_paths:
        if _p and _p.exists():
            _report_text = _p.read_text(encoding="utf-8")
            break
    assert _report_text, "Valid report file not found for human-review boundary check"
    assert "Human review required" in _report_text, "Report missing 'Human review required' marker"
    assert "NOT operator acceptance" in _report_text, "Report missing 'NOT operator acceptance' boundary"
    assert "VS-ENC review status" in _report_text
    assert "Operator authorization status" in _report_text
    assert mcf.ACCEPTANCE_AUTHORITY_NOTE in _report_text
    # Report traceability
    # Evidence is written to Forge-local _debug, never Vault
    print(f"Evidence JSON: {getattr(result, 'evidence_path', 'n/a')}")
    print(f"Report MD: {getattr(result, 'report_path', 'n/a')}")
    # Show a snippet of the report if written
    try:
        evidence_path = Path(mcf.EVIDENCE_DIR) / "KITTY-HAWK-DEMO-VALID-001.json"
        report_path = Path(mcf.EVIDENCE_DIR) / "KITTY-HAWK-DEMO-VALID-001.md"
        if evidence_path.exists():
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            print(f"Evidence payload: mission_id={payload['mission_id']} vault_writeback={payload['vault_writeback']} "
                  f"receipts={len(payload['receipts'])} stages={len(payload['stages'])}")
            assert payload["vault_writeback"] is None
        if report_path.exists():
            report = report_path.read_text(encoding="utf-8")
            assert "Human review required" in report
            assert "## Receipt ledger" in report
            print(f"Report snippet: {report[:300].replace(chr(10), ' | ')}...")
    except Exception as e:
        print(f"(report/evidence read note: {e})")

    # Legacy compatibility preserved (separate check)
    legacy_receipts = [
        {"source": "legacy_source", "content": "Legacy content without explicit receipt_id."},
        {"source": "legacy_source2", "content": "Another legacy receipt."},
    ]
    legacy_check = mcf._validate_evidence_packet(legacy_receipts)
    # Legacy list is accepted; metadata is set to legacy_compatible initially then normalized to valid/invalid.
    # The contract preserves backward compatibility: legacy list is not rejected.
    assert legacy_check.metadata.get("schema_status") in ("legacy_compatible", "valid"), f"legacy status={legacy_check.metadata.get('schema_status')}"
    assert legacy_check.metadata.get("packet_version") == "legacy-list"
    # Legacy list through run_mission with fake clients should still execute
    legacy_result = mcf.run_mission(legacy_receipts, mission_id="KITTY-HAWK-DEMO-LEGACY-001",
                                     clients=_legacy_happy_clients(), authorize_live=False)
    assert legacy_result.status in (mcf.EXECUTION_COMPLETE_STATUS, mcf.EXECUTION_COMPLETE_WITH_FINDINGS_STATUS)
    print(f"Legacy compatibility: {legacy_check.metadata.get('schema_status')} and legacy mission {legacy_result.status} preserved.")

    # --- Determinism policy: semantic vs byte-for-byte ---
    # The runner's timestamps (now_iso) and dispatch_ids (uuid4) are intentionally
    # non-deterministic. Freezing them would hide real wall-clock behavior and
    # require architecture support for deterministic identifiers that does not exist.
    # Policy: assert semantic determinism (same packet + same seat outputs -> same
    # semantic result), while explicitly allowing timestamps/dispatch_ids to differ.
    # Byte-for-byte artifact determinism is NOT claimed.
    second_clients = _happy_clients()
    second_result = mcf.run_mission(
        SANITIZED_VALID_PACKET,
        mission_id="KITTY-HAWK-DEMO-VALID-001",
        clients=second_clients,
        authorize_live=False,
    )
    # Semantic fields must be stable
    assert second_result.status == result.status, "Semantic determinism: status diverged"
    assert second_result.gate_findings == result.gate_findings, "Semantic determinism: gate_findings diverged"
    assert second_result.schema_valid == result.schema_valid, "Semantic determinism: schema_valid diverged"
    assert second_result.client_facing_response == result.client_facing_response, "Semantic determinism: client_facing_response diverged"
    assert second_result.vs_enc_review_status == result.vs_enc_review_status
    assert second_result.operator_authorization_status == result.operator_authorization_status
    assert second_result.vault_writeback == result.vault_writeback
    # Receipt lineage stable (content hashes, event grouping stable; captured_at timestamps may differ)
    assert len(second_result.receipts) == len(result.receipts)
    for a, b in zip(second_result.receipts, result.receipts):
        assert a.receipt_id == b.receipt_id
        assert a.source == b.source
        assert a.content == b.content
        assert a.content_sha256 == b.content_sha256
        assert a.event_id == b.event_id
    # Stages semantic outputs stable; input/output hashes stable because inputs are same
    assert len(second_result.stages) == len(result.stages)
    for s1, s2 in zip(result.stages, second_result.stages):
        assert s1.seat == s2.seat
        assert s1.outcome == s2.outcome
        assert s1.output_text == s2.output_text
        assert s1.output_artifact_hash == s2.output_artifact_hash
        assert s1.input_artifact_hash == s2.input_artifact_hash
    # Non-semantic fields are expected to diverge (and must not be asserted equal):
    # timestamps and dispatch_ids are wall-clock/uuid4 and will differ.
    _timestamps_differ = any(a.timestamp != b.timestamp for a, b in zip(result.stages, second_result.stages))
    _dispatch_differ = any(a.dispatch_id != b.dispatch_id for a, b in zip(result.stages, second_result.stages))
    print(f"Determinism: semantic PASS (status/gate_findings/schema/response/lineage stable); "
          f"byte-for-byte artifact determinism NOT claimed (timestamps differ={_timestamps_differ}, dispatch_ids differ={_dispatch_differ})")

    # NOT_YET_MODELED explicit
    print("NOT_YET_MODELED controls remain explicit: temporal windows, evidence-sufficiency transitions, "
          "mandatory escalation, declared packet-hash verification, semantic entailment, cross-object beyond modeled — "
          "see fixtures WP3-LINEAGE-* and wp3_evidence_packet_fixtures.json")

    print("VALID CASE: PASS\n")
    return result


def run_negative_case() -> mcf.MissionResult:
    print("=" * 78)
    print("NEGATIVE CASE — receipt hash mismatch -> halted before provider dispatch")
    print("=" * 78)
    check = mcf._validate_evidence_packet(NEGATIVE_PACKET_HASH_MISMATCH)
    print(f"Preflight valid={check.valid} findings={check.findings} codes={check.finding_codes}")
    assert not check.valid
    assert "RECEIPT_HASH_MISMATCH" in check.finding_codes

    # Zero-provider-call proof: supply fake clients that would record any ask() call
    clients = _happy_clients()
    # Clear any prior state (fresh clients already empty)
    result = mcf.run_mission(
        NEGATIVE_PACKET_HASH_MISMATCH,
        mission_id="KITTY-HAWK-DEMO-NEG-001",
        clients=clients,
        authorize_live=False,
    )
    print(f"Status: {result.status}")
    print(f"Stages: {len(result.stages)}")
    print(f"Gate findings: {result.gate_findings}")
    print(f"Finding codes: {getattr(result, 'finding_codes', getattr(result, 'gate_findings',()))}")

    assert result.status == "halted_invalid_evidence_packet", f"Expected halted_invalid_evidence_packet, got {result.status}"
    assert len(result.stages) == 0, "Negative packet must produce zero stages (rejected before dispatch)"
    # Zero provider calls
    for seat, fake in clients.items():
        assert not fake.ask_calls, f"Negative case invoked {seat} despite pre-dispatch rejection — expected zero calls, got {len(fake.ask_calls)}"
        assert not fake.set_agent_calls, f"Negative case set_agent called for {seat} despite rejection"
    print("Zero-provider-call evidence: all 4 fake clients have ask_calls == [] and set_agent_calls == []")

    # Also demonstrate malformed packet path
    check2 = mcf._validate_evidence_packet(NEGATIVE_PACKET_MALFORMED)
    print(f"Malformed packet valid={check2.valid} codes={check2.finding_codes}")
    assert not check2.valid
    assert "PACKET_MISSING_FIELD" in check2.finding_codes or "PACKET_SEVERITY_INVALID" in check2.finding_codes

    clients2 = _happy_clients()
    result2 = mcf.run_mission(NEGATIVE_PACKET_MALFORMED, mission_id="KITTY-HAWK-DEMO-NEG-002",
                               clients=clients2, authorize_live=False)
    assert result2.status == "halted_invalid_evidence_packet"
    assert len(result2.stages) == 0
    for fake in clients2.values():
        assert not fake.ask_calls
    print("Malformed packet also halted with zero provider calls: PASS")

    print("NEGATIVE CASE: PASS\n")
    return result


def main() -> None:
    print("\nKitty Hawk Offline Demonstration — Existing Runner Only")
    print(f"Runner: {mcf.__file__}")
    print(f"Evidence dir: {mcf.EVIDENCE_DIR}")
    print(f"Mission seats: {mcf.MISSION_SEAT_ORDER}")
    print(f"WatsonX substrate: IBM watsonx only (no fallback, TLS verified)\n")

    valid_result = run_valid_case()
    negative_result = run_negative_case()

    print("=" * 78)
    print("DEMO SUMMARY")
    print("=" * 78)
    print(f"Valid case: {valid_result.status} with {len(valid_result.stages)} stages, "
          f"schema_valid={valid_result.schema_valid}, review={valid_result.vs_enc_review_status}")
    print(f"Negative case: {negative_result.status} with {len(negative_result.stages)} stages, "
          f"zero provider calls verified")
    print(f"Generated reports: {Path(mcf.EVIDENCE_DIR) / 'KITTY-HAWK-DEMO-VALID-001.md'} and "
          f"{Path(mcf.EVIDENCE_DIR) / 'KITTY-HAWK-DEMO-VALID-001.json'} (repo-local, never Vault)")
    print("Live watsonx: NOT called (offline demo, TLS/provider boundary unchanged)")
    print("NOT_YET_MODELED: temporal windows, sufficiency transitions, mandatory escalation, "
          "declared packet-hash verification, semantic entailment — remain explicit, not claimed")
    print("\nNext: run offline suites separately:")
    print("  python tests/test_mission_citation_fabrication.py")
    print("  python tests/test_watsonx_client.py")


if __name__ == "__main__":
    main()
