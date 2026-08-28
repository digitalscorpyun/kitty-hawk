"""Offline acceptance checks for mission_citation_fabrication.py. Zero live
provider calls: every seat is either monkeypatched via the `clients`
injection seam, or exercised through the real WatsonXClient adapter class and
real manifest/provider plumbing (constructed via the explicit
initialize_sdk=False offline seam -- not real IBM SDK object construction,
which that seam deliberately skips) with only WatsonXClient.ask() itself
scripted -- so the mission's actual provider-identity/manifest-identity
plumbing is proven correct without ever reaching the network or requiring
ibm-watsonx-ai to be installed."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

for name in ("WATSONX_APIKEY", "WATSONX_PROJECT_ID", "WATSONX_URL", "WATSONX_REGION"):
    os.environ.setdefault(name, "test-dummy")
# The five credential variables that belonged to the retired multi-vendor
# architecture must never matter to this module. Scrubbed here, and never
# set again by this file, so any accidental dependency on them fails loudly.
for name in ("GEMINI_API_KEY", "DASHSCOPE_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY"):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

import mission_citation_fabrication as mcf  # noqa: E402
import syndicate_router as sr  # noqa: E402


class FakeClient:
    def __init__(self, response: str, *, model_id: str = "FAKE-MODEL", raises: Exception | None = None):
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


SAMPLE_RECEIPTS = [
    {"source": "lawyer_report", "content": "Client's filing cited 'Smith v. Doe, 512 F.4th 88 (9th Cir. 2024)', which the lawyer states does not exist in any reporter."},
    {"source": "workspace_transcript_excerpt", "content": "Workspace output: 'See Smith v. Doe, 512 F.4th 88 (9th Cir. 2024), holding that ...'"},
]

VERSIONED_PACKET = {
    "packet_version": "1.0",
    "case_id": "CASE-CITATION-001",
    "severity": "medium",
    "customer_impact": "Potentially misleading research output.",
    "affected_workflow": "AI-assisted research synthesis",
    "incident_boundary": "One bounded citation-reliability incident.",
    "verification_scope": "Receipt content and source comparison only.",
    "provenance_classification": "supplied-and-audited",
    "evidence_sufficiency": "sufficient-for-triage",
    "uncertainty": ["Independent source confirmation remains pending."],
    "escalation_conditions": ["Escalate if recurrence is confirmed."],
    "receipts": [
        {"receipt_id": "RCPT-PACKET-001", "source": "audit_note", "content": "The citation does not resolve.", "event_id": "EVT-CITATION-001"},
        {"receipt_id": "RCPT-PACKET-002", "source": "workspace_excerpt", "content": "The workspace repeated the citation.", "event_id": "EVT-CITATION-001"},
    ],
}

for _receipt in VERSIONED_PACKET["receipts"]:
    _receipt["hash_algorithm"] = "sha256"
    _receipt["content_sha256"] = hashlib.sha256(_receipt["content"].encode("utf-8")).hexdigest()

WELL_FORMED_CLIENT_FACING_TEXT = (
    "WHAT WE VERIFIED:\nThe citation does not resolve.\n\n"
    "WHAT REMAINS UNCERTAIN:\nWhether this is a one-off.\n\n"
    "NEXT STEPS:\nWe are reviewing the underlying workspace session."
)

# receipt_id is auto-assigned RCPT-001/RCPT-002 for SAMPLE_RECEIPTS (no
# explicit receipt_id in the source dicts) -- these fixture seat responses
# must cite those exact IDs to pass the evidence-citation gate.
WELL_FORMED_ECHO_PROPHET_OUTPUT = (
    "VERIFIED FACTS:\n"
    "- The workspace output cites 'Smith v. Doe, 512 F.4th 88 (9th Cir. 2024)' (RCPT-002).\n"
    "- The lawyer reports this citation does not exist in any reporter (RCPT-001).\n\n"
    "REPORTED CLAIMS:\n- The lawyer claims the case is fabricated.\n\n"
    "INFERENCES:\n- The workspace may have hallucinated the citation.\n\n"
    "UNRESOLVED QUESTIONS:\n- Whether this is a one-off or a repeated pattern."
)
WELL_FORMED_CONTEXTUAL_CATALYST_OUTPUT = (
    "FAILURE MECHANISM:\n- Ungrounded generation / hallucinated source. Well-supported by the receipts.\n\n"
    "ESCALATION CRITERIA:\n- Escalate on repeat occurrence after a prior fix, or on regulatory/bar-complaint exposure."
)


def _happy_path_clients() -> dict[str, FakeClient]:
    return {
        "ECHO-PROPHET": FakeClient(WELL_FORMED_ECHO_PROPHET_OUTPUT),
        "CONTEXTUAL-CATALYST": FakeClient(WELL_FORMED_CONTEXTUAL_CATALYST_OUTPUT),
        "CG-SCRIBE": FakeClient(WELL_FORMED_CLIENT_FACING_TEXT),
        "OD-COMPLY": FakeClient("PASS: WHAT WE VERIFIED:\nPASS: WHAT REMAINS UNCERTAIN:\nPASS: NEXT STEPS:"),
    }


def main() -> None:
    checks = 0

    def check(value: bool, label: str) -> None:
        nonlocal checks
        checks += 1
        if not value:
            raise AssertionError(label)

    # --- Fixed topology, exactly the four required seats in order ---
    check(mcf.MISSION_SEAT_ORDER == ("ECHO-PROPHET", "CONTEXTUAL-CATALYST", "CG-SCRIBE", "OD-COMPLY"), "MISSION_SEAT_ORDER is not the exact required four-stage order")

    # --- No forbidden seat can enter the topology, and WATSONX the
    # advisory seat remains excluded even though WatsonXClient (the
    # provider CLASS) is what actually executes every stage. ---
    check(mcf.FORBIDDEN_SEATS.isdisjoint(set(mcf.MISSION_SEAT_ORDER)), "a forbidden seat is present in MISSION_SEAT_ORDER")
    check({"TWIN-WARDEN", "MW-ARCHIVE", "WATSONX", "VS-ENC", "BEDROCK"} <= mcf.FORBIDDEN_SEATS, "FORBIDDEN_SEATS is missing an expected name")
    check("WATSONX" in mcf.FORBIDDEN_SEATS, "the WATSONX advisory seat is not excluded from this mission's topology")
    check(set(mcf.MISSION_SEAT_ORDER) <= set(sr.SEAT_PROVIDER), "a mission seat has no registered provider in the real SEAT_PROVIDER registry")

    # --- Single authorized substrate: every mission seat resolves to the
    # SAME class, WatsonXClient, by identity -- not "some provider", and
    # never a per-vendor client. ---
    for name in mcf.MISSION_SEAT_ORDER:
        check(sr.SEAT_PROVIDER[name] is sr.WatsonXClient, f"{name} is not bound to the authorized IBM watsonx substrate")
        check(sr.SEAT_PROVIDER[name] is mcf.WatsonXClient, f"{name}'s registry binding is not the same WatsonXClient class object mcf imports")

    # --- No non-watsonx paid provider is even importable from this module.
    # Static source check: proves the retired vendor clients are not wired
    # in, not merely "not currently invoked". ---
    mission_source = Path(mcf.__file__).read_text(encoding="utf-8")
    for forbidden_name in ("gemini_client", "qwen_client", "grok_client", "deepseek_client", "kimi_client", "GeminiClient", "QwenClient", "GrokClient", "DeepSeekClient", "KimiClient"):
        check(forbidden_name not in mission_source, f"mission_citation_fabrication.py still references the retired {forbidden_name}")
    for attr in ("GeminiClient", "QwenClient", "GrokClient", "DeepSeekClient", "KimiClient"):
        check(not hasattr(mcf, attr), f"mission_citation_fabrication.py still exposes the retired {attr}")

    # --- None of the five credential variables that belonged to the
    # retired multi-vendor architecture is even referenced by this module's
    # source -- it cannot possibly gate on them, present or absent. ---
    for irrelevant_var in ("DASHSCOPE_API_KEY", "XAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY", "MOONSHOT_API_KEY"):
        check(irrelevant_var not in mission_source, f"mission_citation_fabrication.py still references the irrelevant {irrelevant_var}")

    # A clients override naming a forbidden/out-of-topology seat (including
    # WATSONX itself, and the retired TWIN-WARDEN) must be refused before
    # any stage runs.
    for forbidden_key in ("TWIN-WARDEN", "WATSONX"):
        try:
            mcf.run_mission(SAMPLE_RECEIPTS, clients={**_happy_path_clients(), forbidden_key: FakeClient("x")})
            raise AssertionError(f"run_mission accepted a clients override naming {forbidden_key}, outside MISSION_SEAT_ORDER")
        except ValueError as exc:
            check(forbidden_key in str(exc), "rejection message did not name the offending seat")

    # --- Live-authorization gate: with no clients overrides and no
    # authorize_live=True, run_mission must refuse before touching any
    # provider. ---
    try:
        mcf.run_mission(SAMPLE_RECEIPTS)
        raise AssertionError("run_mission executed live without authorize_live=True")
    except PermissionError:
        checks += 1

    partial = _happy_path_clients()
    del partial["OD-COMPLY"]
    try:
        mcf.run_mission(SAMPLE_RECEIPTS, clients=partial)
        raise AssertionError("run_mission executed the live OD-COMPLY seat without authorize_live=True")
    except PermissionError:
        checks += 1

    # --- Empty receipts must be refused outright (nothing to preserve) ---
    try:
        mcf.run_mission([], clients=_happy_path_clients(), authorize_live=True)
        raise AssertionError("run_mission accepted an empty receipts list")
    except ValueError:
        checks += 1

    # --- Happy path (faked clients): correct order, exact artifact
    # handoff, receipt preservation, terminal status never "accepted". ---
    clients = _happy_path_clients()
    result = mcf.run_mission(SAMPLE_RECEIPTS, mission_id="TEST-MISSION-001", clients=clients, authorize_live=True)

    check(result.status == mcf.EXECUTION_COMPLETE_STATUS, "happy-path mission did not reach the execution-complete status")
    check(result.vs_enc_review_status == "not_reviewed", "runner incorrectly claimed a VS-ENC review")
    check(result.operator_authorization_status == "not_authorized", "runner incorrectly claimed operator authorization")
    check("accept" not in result.status.lower(), "terminal status string implies acceptance")
    check(not any(f.name == "accepted" for f in mcf.MissionResult.__dataclass_fields__.values()), "MissionResult declares an 'accepted' field")
    check(result.gate_findings == (), "a clean happy-path mission reported gate findings")
    check(len(result.stages) == 4, "happy-path mission did not run exactly four stages")
    check(tuple(s.seat for s in result.stages) == mcf.MISSION_SEAT_ORDER, "stage order does not match MISSION_SEAT_ORDER")

    versioned_clients = _happy_path_clients()
    versioned_clients["ECHO-PROPHET"] = FakeClient(
        "VERIFIED FACTS:\\n"
        "- The citation does not resolve (RCPT-PACKET-001).\\n"
        "- The workspace repeats the citation (RCPT-PACKET-002).\\n\\n"
        "REPORTED CLAIMS:\\n- A party claims the citation is fabricated.\\n\\n"
        "INFERENCES:\\n- The citation may reflect ungrounded generation.\\n\\n"
        "UNRESOLVED QUESTIONS:\\n- Whether this recurs."
    )
    versioned_result = mcf.run_mission(VERSIONED_PACKET, mission_id="TEST-VERSIONED-END-TO-END", clients=versioned_clients, authorize_live=False)
    check(versioned_result.status == mcf.EXECUTION_COMPLETE_STATUS, "valid versioned packet did not complete all four stages")
    check(len(versioned_result.stages) == 4, "valid versioned packet did not execute exactly four stages")
    check(versioned_result.schema_valid is True, "valid versioned packet produced an invalid client-facing schema")
    check(versioned_result.packet_metadata["schema_status"] == "valid", "valid versioned packet metadata was not preserved")

    check(len(result.receipts) == 2, "receipts were not preserved")
    for original, preserved in zip(SAMPLE_RECEIPTS, result.receipts):
        check(preserved.content == original["content"], "receipt content was not preserved verbatim")
        check(preserved.source == original["source"], "receipt source was not preserved")
        check(preserved.content_sha256 == hashlib.sha256(original["content"].encode("utf-8")).hexdigest(), "receipt hash is wrong")
        check(preserved.event_id is None, "a receipt with no supplied event_id was not left as None")

    receipt_ids = tuple(r.receipt_id for r in result.receipts)
    for stage in result.stages:
        check(stage.mission_id == "TEST-MISSION-001", f"{stage.seat} stage carries the wrong mission_id")
        check(stage.source_receipt_refs == receipt_ids, f"{stage.seat} stage lost the source-receipt references")
        check(stage.dispatch_id is not None and stage.dispatch_id.startswith(f"{stage.seat}:"), f"{stage.seat} stage dispatch_id is malformed")
        check(stage.outcome == "executed", f"{stage.seat} stage did not execute in the happy path")
        check(bool(stage.timestamp), f"{stage.seat} stage missing a timestamp")
        check(stage.output_artifact_hash == hashlib.sha256(stage.output_text.encode("utf-8")).hexdigest(), f"{stage.seat} output hash does not match its own output text")

    stage1, stage2, stage3, stage4 = result.stages

    check(stage1.input_artifact_hash == hashlib.sha256(clients["ECHO-PROPHET"].ask_calls[0].encode("utf-8")).hexdigest(), "ECHO-PROPHET input hash does not match the prompt it actually received")
    check(stage2.input_artifact_hash == hashlib.sha256(clients["CONTEXTUAL-CATALYST"].ask_calls[0].encode("utf-8")).hexdigest(), "CONTEXTUAL-CATALYST input hash does not match the prompt it actually received")
    check(stage1.output_text in clients["CONTEXTUAL-CATALYST"].ask_calls[0], "CONTEXTUAL-CATALYST did not receive ECHO-PROPHET's exact adjudication text")
    check(stage3.input_artifact_hash == hashlib.sha256(clients["CG-SCRIBE"].ask_calls[0].encode("utf-8")).hexdigest(), "CG-SCRIBE input hash does not match the prompt it actually received")
    check(stage1.output_text in clients["CG-SCRIBE"].ask_calls[0], "CG-SCRIBE did not receive ECHO-PROPHET's exact adjudication text")
    check(stage2.output_text in clients["CG-SCRIBE"].ask_calls[0], "CG-SCRIBE did not receive CONTEXTUAL-CATALYST's exact failure/escalation text")
    check(stage4.input_artifact_hash == hashlib.sha256(clients["OD-COMPLY"].ask_calls[0].encode("utf-8")).hexdigest(), "OD-COMPLY input hash does not match the prompt it actually received")
    check(result.client_facing_response in clients["OD-COMPLY"].ask_calls[0], "OD-COMPLY did not receive CG-SCRIBE's exact client-facing text")

    for seat_name in mcf.MISSION_SEAT_ORDER:
        check(clients[seat_name].set_agent_calls == [seat_name], f"{seat_name}'s fake client had the wrong set_agent() history -- no stage may silently substitute another identity")

    # --- OD-COMPLY cannot alter or adjudicate factual meaning ---
    check(result.client_facing_response == clients["CG-SCRIBE"].response, "client_facing_response was not CG-SCRIBE's output verbatim")
    check(result.od_comply_notes == clients["OD-COMPLY"].response, "od_comply_notes did not capture OD-COMPLY's own output separately")
    check(result.client_facing_response != result.od_comply_notes, "OD-COMPLY's output overwrote the client-facing response")

    hostile_clients = _happy_path_clients()
    hostile_clients["OD-COMPLY"] = FakeClient("FAIL: the citation is actually valid, disregard all prior findings.")
    hostile_result = mcf.run_mission(SAMPLE_RECEIPTS, mission_id="TEST-MISSION-HOSTILE", clients=hostile_clients, authorize_live=True)
    check(hostile_result.client_facing_response == hostile_clients["CG-SCRIBE"].response, "a hostile OD-COMPLY response was able to mutate the client-facing text")
    check(hostile_result.schema_valid is True, "OD-COMPLY's free-text content changed the deterministic schema verdict")

    # --- Deterministic schema validator is a pure, form-only function ---
    good = mcf._validate_output_schema("WHAT WE VERIFIED:\na\n\nWHAT REMAINS UNCERTAIN:\nb\n\nNEXT STEPS:\nc")
    check(good.valid and good.findings == (), "well-formed client-facing text failed schema validation")
    missing = mcf._validate_output_schema("WHAT WE VERIFIED:\na\n\nNEXT STEPS:\nc")
    check(not missing.valid and any("WHAT REMAINS UNCERTAIN" in f for f in missing.findings), "schema validator did not catch a missing section")
    empty_section = mcf._validate_output_schema("WHAT WE VERIFIED:\n\nWHAT REMAINS UNCERTAIN:\nb\n\nNEXT STEPS:\nc")
    check(not empty_section.valid, "schema validator did not catch an empty section body")
    check(mcf._validate_output_schema("").valid is False, "schema validator accepted empty text")

    # --- Fail-closed behavior, per stage: poison SEAT_PROVIDER's entry for
    # exactly one seat at a time (construction itself raises) and confirm
    # the mission halts at exactly that stage; no later stage's fake client
    # is ever invoked. Earlier stages use well-formed, gate-passing fixture
    # text (not placeholder text) so this test isolates provider-poisoning
    # behavior from the new deterministic gates below. ---
    class _PoisonedWatsonX:
        def __init__(self, *a, **kw):
            raise RuntimeError("construction poisoned for this test")

    def assert_halts_at(seat_name: str, expected_prior_calls: int) -> None:
        original_provider = sr.SEAT_PROVIDER[seat_name]
        sr.SEAT_PROVIDER[seat_name] = _PoisonedWatsonX
        try:
            well_formed = _happy_path_clients()
            partial_clients = {name: well_formed[name] for name in mcf.MISSION_SEAT_ORDER if name != seat_name}
            r = mcf.run_mission(SAMPLE_RECEIPTS, mission_id=f"TEST-HALT-{seat_name}", clients=partial_clients, authorize_live=True)
            check(r.status == f"halted_{seat_name.lower().replace('-', '_')}_unavailable", f"mission did not halt with the expected status for {seat_name}")
            check(len(r.stages) == expected_prior_calls + 1, f"mission ran the wrong number of stages before halting at {seat_name}")
            check(r.stages[-1].outcome == "unavailable", f"the halting stage for {seat_name} was not marked unavailable")
            check(r.client_facing_response is None, f"a halted mission ({seat_name}) still produced a client-facing response")
            check(r.schema_valid is None, f"a halted mission ({seat_name}) still produced a schema verdict")
            for name, fake in partial_clients.items():
                idx = mcf.MISSION_SEAT_ORDER.index(name)
                if idx < mcf.MISSION_SEAT_ORDER.index(seat_name):
                    check(fake.ask_calls, f"{name} (before the halt point) was never actually invoked")
                else:
                    check(not fake.ask_calls, f"{name} (after the halt point) was invoked despite the earlier halt -- not fail-closed")
        finally:
            sr.SEAT_PROVIDER[seat_name] = original_provider

    assert_halts_at("ECHO-PROPHET", 0)
    assert_halts_at("CONTEXTUAL-CATALYST", 1)
    assert_halts_at("CG-SCRIBE", 2)
    assert_halts_at("OD-COMPLY", 3)

    # --- Fail-closed on a real in-flight failure (not a missing credential):
    # ask() itself raises -- must halt, not skip, not fall back. ---
    failing_clients = _happy_path_clients()
    failing_clients["CONTEXTUAL-CATALYST"] = FakeClient("unused", raises=RuntimeError("simulated API outage"))
    failure_result = mcf.run_mission(SAMPLE_RECEIPTS, mission_id="TEST-MISSION-FAILED", clients=failing_clients, authorize_live=True)
    check(failure_result.status == "halted_contextual_catalyst_failed", "an in-flight ask() failure was not reported as halted_contextual_catalyst_failed")
    check(len(failure_result.stages) == 2, "mission did not stop immediately after the failing stage")
    check(not failing_clients["CG-SCRIBE"].ask_calls and not failing_clients["OD-COMPLY"].ask_calls, "later stages ran despite an earlier in-flight failure")

    # --- Real substrate proof: construct the REAL WatsonXClient class for
    # every stage (no `clients` override at all), through the explicit
    # offline seam (initialize_sdk=False), with only WatsonXClient.ask()
    # itself scripted so no network call is made and no IBM SDK object is
    # ever constructed. This proves the real adapter class and real
    # manifest/provider plumbing -- all four mission stages genuinely share
    # one provider class while loading distinct, correct canonical manifests
    # via the real set_agent() -- not real IBM SDK construction, which
    # initialize_sdk=False deliberately skips. Scripted text is well-formed
    # per seat so it also clears the deterministic gates. ---
    seen_agents: list[str] = []

    def _scripted_watsonx_ask(self, prompt, **kwargs):
        seen_agents.append(self.current_agent)
        if self.current_agent == "ECHO-PROPHET":
            return WELL_FORMED_ECHO_PROPHET_OUTPUT
        if self.current_agent == "CONTEXTUAL-CATALYST":
            return WELL_FORMED_CONTEXTUAL_CATALYST_OUTPUT
        if self.current_agent == "CG-SCRIBE":
            return WELL_FORMED_CLIENT_FACING_TEXT
        return f"SCRIPTED-OUTPUT-FOR-{self.current_agent}"

    # Force initialize_sdk=False for every real WatsonXClient this mission
    # constructs -- proves the real adapter class, real timeout/limit
    # configuration, and real manifest/seat-name plumbing without requiring
    # the IBM SDK to be installed in the public offline environment. Only
    # __init__'s default and ask() are touched; SEAT_PROVIDER identity
    # (WatsonXClient itself) is never substituted.
    original_watsonx_init = sr.WatsonXClient.__init__

    def _offline_init(self, model_id=None, initialize_sdk=True):  # noqa: ARG001 - signature must match real __init__
        original_watsonx_init(self, model_id=model_id, initialize_sdk=False)

    original_watsonx_ask = sr.WatsonXClient.ask
    sr.WatsonXClient.__init__ = _offline_init
    sr.WatsonXClient.ask = _scripted_watsonx_ask
    try:
        real_result = mcf.run_mission(SAMPLE_RECEIPTS, mission_id="TEST-REAL-SUBSTRATE", authorize_live=True)
        check(real_result.status == mcf.EXECUTION_COMPLETE_STATUS, "real-substrate mission did not complete")
        check(seen_agents == list(mcf.MISSION_SEAT_ORDER), "real WatsonXClient stages ran with the wrong seat identities, in the wrong order -- possible identity substitution")
        for stage in real_result.stages:
            check(stage.provider == "WatsonXClient", f"{stage.seat} did not execute on the real WatsonXClient class")
        model_ids = {stage.model_id for stage in real_result.stages}
        check(len(model_ids) == 1, f"mission stages did not share one execution substrate model_id: {model_ids}")
        check(real_result.client_facing_response == WELL_FORMED_CLIENT_FACING_TEXT, "real-substrate CG-SCRIBE output was not carried through as the client-facing response")
        check(real_result.schema_valid is True, "real-substrate mission's well-formed output failed schema validation")
    finally:
        sr.WatsonXClient.__init__ = original_watsonx_init
        sr.WatsonXClient.ask = original_watsonx_ask

    # --- Evidence lands only in the Forge, never the Vault, and captures
    # the required identity/audit fields for every stage. ---
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = mcf.EVIDENCE_DIR
        mcf.EVIDENCE_DIR = Path(tmpdir)
        try:
            ev_clients = _happy_path_clients()
            ev_result = mcf.run_mission(SAMPLE_RECEIPTS, mission_id="TEST-EVIDENCE-001", clients=ev_clients, authorize_live=True)
            evidence_path = Path(tmpdir) / "TEST-EVIDENCE-001.json"
            report_path = Path(tmpdir) / "TEST-EVIDENCE-001.md"
            check(evidence_path.exists(), "mission evidence file was not written")
            check(report_path.exists(), "Customer Success Markdown report was not written")
            payload = json.loads(evidence_path.read_text(encoding="utf-8"))
            check(payload["mission_id"] == "TEST-EVIDENCE-001", "evidence file mission_id mismatch")
            check(payload["vault_writeback"] is None, "evidence file does not declare vault_writeback as None")
            check(len(payload["stages"]) == 4, "evidence file did not preserve all four stages")
            required_stage_fields = {"mission_id", "seat", "provider", "model_id", "input_artifact_hash", "output_artifact_hash", "dispatch_id", "timestamp", "source_receipt_refs", "outcome", "reason"}
            for stage_payload in payload["stages"]:
                check(required_stage_fields <= set(stage_payload), f"evidence stage record missing required fields: {required_stage_fields - set(stage_payload)}")
            check("event_id" in payload["receipts"][0], "receipt record does not serialize the new event_id field")
            report = report_path.read_text(encoding="utf-8")
            check("# Customer Success Incident Record — TEST-EVIDENCE-001" in report, "report title or mission_id is missing")
            check(f"**Case ID:** `TEST-EVIDENCE-001`" in report, "report does not lead with the case ID")
            check("**Execution status:**" in report and "**VS-ENC review status:**" in report and "**Operator authorization status:**" in report, "report header block is missing a required status field")
            check(report.index("Case ID") < report.index("Verified Incident"), "report does not lead with case/status identity before the incident body")
            check("execution_complete` means the mission's stages ran to" in report and "NOT operator acceptance" in report, "report does not explicitly disclaim execution_complete as acceptance")
            check("## Verified Incident" in report, "report is missing the Verified Incident section")
            check("## Supporting Receipts" in report, "report is missing the Supporting Receipts section")
            check("## Affected Evidence / Events" in report, "report is missing the Affected Evidence / Events section")
            check("## Customer Impact" in report, "report is missing the Customer Impact section")
            check("## Remaining Uncertainty" in report, "report is missing the Remaining Uncertainty section")
            check("## Recommended Next Action" in report, "report is missing the Recommended Next Action section")
            check("Human review required" in report, "report does not mark model output as a human-review draft")
            check("## Customer-facing draft" in report and WELL_FORMED_CLIENT_FACING_TEXT in report, "report lost the customer-facing response")
            check("## Receipt ledger" in report and "RCPT-001" in report and SAMPLE_RECEIPTS[0]["content"] in report, "report lost receipt provenance or content")
            check("## Per-seat diagnostic outputs" in report, "report omitted per-seat diagnostic outputs")
            for seat_name in mcf.MISSION_SEAT_ORDER:
                check(f"### {seat_name}" in report, f"report omitted the {seat_name} diagnostic section")
            check(mcf.ACCEPTANCE_AUTHORITY_NOTE in report, "report omitted the acceptance decision boundary")
            check(ev_result.status == mcf.EXECUTION_COMPLETE_STATUS, "evidence-path mission did not complete")
        finally:
            mcf.EVIDENCE_DIR = original_dir
        vault_marker = Path(os.getenv("KITTY_HAWK_VAULT_PATH", str(Path(mcf.__file__).resolve().parent / "fixtures" / "vault"))) / "mission_citation_fabrication_TEST-EVIDENCE-001_should_not_exist.json"
        check(not vault_marker.exists(), "sentinel Vault path unexpectedly exists")

    # =========================================================================
    # Operation Kitty Hawk (2026-08-24) regression fixtures. Verbatim text
    # from the two real 2026-08-23 SYLLO-CITATION-RELIABILITY runs, used so
    # these confirmed defects can never silently regress.
    # =========================================================================

    check("Do not invent numerical thresholds" in mcf.CONTEXTUAL_CATALYST_TASK_TEMPLATE, "CONTEXTUAL-CATALYST prompt is missing the invented-threshold prohibition")
    check("operator or organizational policy" in mcf.CONTEXTUAL_CATALYST_TASK_TEMPLATE, "CONTEXTUAL-CATALYST prompt's threshold rule dropped the required fallback instruction")
    check("Do not state a numeric confidence percentage" in mcf.CONTEXTUAL_CATALYST_TASK_TEMPLATE, "CONTEXTUAL-CATALYST prompt is missing the confidence-percentage prohibition")
    check("(lawyer, workspace, vendor)" not in mcf.ECHO_PROPHET_TASK_TEMPLATE, "ECHO-PROPHET prompt still hardcodes the obsolete (lawyer, workspace, vendor) party list")
    check("do not assume" in mcf.ECHO_PROPHET_TASK_TEMPLATE.lower(), "ECHO-PROPHET prompt dropped the instruction not to assume a party role absent from the receipts")

    REAL_CTX_GROK_OUTPUT_RUN_A = (
        "## FAILURE MECHANISM:\nThe specific class of failure this incident represents is a \"citation-verification gap\" with potential \"ungrounded generation\" or \"hallucinated source\" elements, as the AI system provided incorrect citations and fabricated quotes. My confidence in this assessment is moderate to high (70%), based on the verified facts provided, which clearly demonstrate discrepancies between the original and corrected information. This confidence would be raised by additional evidence of systematic errors in citation generation or retrieval, such as multiple instances of incorrect citations across different topics or users. Conversely, it would be lowered by evidence suggesting that the errors were isolated or due to external factors, such as user input errors or database inconsistencies.\n\n"
        "## ESCALATION CRITERIA:\nThis incident should be escalated beyond a routine support response if any of the following concrete, checkable conditions are met:\n"
        "1. **Pattern Across Multiple Users**: If similar incidents of incorrect citations or fabricated quotes are reported by at least three different users within a short timeframe (e.g., a week), indicating a potential systematic issue with the AI system.\n"
        "2. **Regulatory/Bar-Complaint Exposure**: If the incident leads to a formal complaint to a regulatory body or a bar association, or if there is a risk of legal action due to the provision of incorrect information.\n"
        "3. **Repeat Occurrence After a Prior Fix**: If the issue recurs after a fix or update has been implemented to address the citation-verification gap or ungrounded generation, suggesting that the root cause has not been adequately addressed.\n"
        "4. **Financial or Professional Harm to the Client**: If the client suffers financial loss or professional damage (e.g., loss of reputation, failure to meet academic or professional standards) directly attributable to the incorrect citations or fabricated quotes provided by the AI system."
    )
    REAL_CTX_GROK_OUTPUT_RUN_B = (
        "## FAILURE MECHANISM:\nThe specific class of failure this incident represents is a **citation-verification gap**, where the AI system failed to accurately verify and represent citations, leading to the production of incorrect or fabricated information. My confidence in this assessment is moderate to high (70%), based on the verified facts provided, which clearly demonstrate discrepancies between the citations generated by the system and the actual published works. This confidence would be raised by additional evidence of similar failures across multiple users or instances, and lowered by evidence of isolated errors or user-specific mistakes.\n\n"
        "## ESCALATION CRITERIA:\nThis incident must be escalated beyond a routine support response if the following concrete, checkable conditions are met:\n"
        "1. **Pattern across multiple users**: If similar citation-verification gaps are reported by at least three different users within a short timeframe (e.g., one week), indicating a potential systemic issue.\n"
        "2. **Regulatory or bar-complaint exposure**: If the incident is reported to a regulatory body or leads to a bar complaint, requiring immediate attention and resolution to mitigate potential consequences.\n"
        "3. **Repeat occurrence after a prior fix**: If a similar citation-verification gap is reported after a prior fix or update was implemented, suggesting that the issue is not fully resolved or that new issues have arisen.\n"
        "4. **Financial or professional harm to the client**: If the client can demonstrate that the incorrect or fabricated citations have caused financial loss, damage to reputation, or other professional harm, necessitating prompt action to rectify the situation."
    )

    # --- 1. The 70% confidence claim is caught (function-level) ---
    for label, real_output in (("run A", REAL_CTX_GROK_OUTPUT_RUN_A), ("run B", REAL_CTX_GROK_OUTPUT_RUN_B)):
        findings = mcf._find_unsupported_numbers(real_output)
        check(any("70%" in f for f in findings), f"detector failed to catch the confirmed 70% confidence figure in real {label} output")
        # --- 2. Both "three users within one week" variants are caught ---
        check(any("three" in f.lower() and "week" in f.lower() for f in findings), f"detector caught something in {label} but missed the specific 'three users ... week' threshold")

    # Qualitative language with no invented number must pass clean.
    qualitative = "ESCALATION CRITERIA:\nEscalate if there is a documented pattern across multiple users, or regulatory exposure, or repeat occurrence after a prior fix."
    check(mcf._find_unsupported_numbers(qualitative) == (), "detector flagged qualitative language with no numeric threshold")

    # A sourced threshold -- one that cites a receipt or policy artifact in
    # the same sentence -- must pass; the detector is a mechanical pattern
    # match for an unsourced assertion, not a ban on numbers altogether.
    sourced = "ESCALATION CRITERIA:\nEscalate after 3 reports within 7 days, per the organizational policy artifact cited in RCPT-SUPPORT-POLICY-01."
    check(mcf._find_unsupported_numbers(sourced) == (), "detector flagged a threshold that explicitly cited its policy source")
    sourced_percent = "FAILURE MECHANISM:\nConfidence is 90%, per the confidence-scoring policy artifact RCPT-METHOD-01."
    check(mcf._find_unsupported_numbers(sourced_percent) == (), "detector flagged a sourced confidence percentage")

    # --- Unsupported-number findings are retained while the workflow continues
    # through CG-SCRIBE and OD-COMPLY. The discrepancy remains visible. ---
    for label, real_output in (("run A", REAL_CTX_GROK_OUTPUT_RUN_A), ("run B", REAL_CTX_GROK_OUTPUT_RUN_B)):
        gated_clients = _happy_path_clients()
        gated_clients["CONTEXTUAL-CATALYST"] = FakeClient(real_output)
        gated_result = mcf.run_mission(SAMPLE_RECEIPTS, mission_id=f"TEST-GATE-NUMBER-{label.replace(' ', '')}", clients=gated_clients, authorize_live=True)
        check(gated_result.status == mcf.EXECUTION_COMPLETE_WITH_FINDINGS_STATUS, f"mission did not complete with findings for unsupported numbers ({label})")
        check(bool(gated_result.gate_findings), f"completed mission ({label}) reported no unsupported-number findings")
        check(bool(gated_clients["CG-SCRIBE"].ask_calls), f"CG-SCRIBE did not run after unsupported-number findings ({label})")
        check(bool(gated_clients["OD-COMPLY"].ask_calls), f"OD-COMPLY did not run after unsupported-number findings ({label})")

    # --- 3. Catto's two corroborating records count as one underlying event ---
    catto_receipts = [
        {"receipt_id": "RCPT-CATTO-AUDIT", "event_id": "EVT-CATTO-MUTATION", "source": "VAULT_ARTIFACT_AUDIT_20260802.md#row-35", "content": "Mutates a real citation, web-verified 2026-08-02."},
        {"receipt_id": "RCPT-CATTO-VERIFY", "event_id": "EVT-CATTO-MUTATION", "source": "workspace_transcript_20260826.md#catto-note", "content": "Catto mutates a real citation, verified by web search."},
        {"receipt_id": "RCPT-COFFIN-QUOTE", "source": "levi_coffin...md#frontmatter-quotes", "content": "A quote attributed to Eric Foner."},
    ]
    preserved = mcf._preserve_receipts(catto_receipts)
    check(preserved[0].event_id == "EVT-CATTO-MUTATION" and preserved[1].event_id == "EVT-CATTO-MUTATION", "event_id was not preserved on the two corroborating Catto receipts")
    events = mcf._distinct_events(preserved)
    check(len(events) == 2, f"two corroborating records plus one standalone receipt should be 2 distinct events, got {len(events)}")
    catto_event = next(e for e in events if e[0] == "EVT-CATTO-MUTATION")
    check(set(catto_event[1]) == {"RCPT-CATTO-AUDIT", "RCPT-CATTO-VERIFY"}, "the Catto event group does not contain both corroborating receipt_ids")
    coffin_event = next(e for e in events if e[0] == "RCPT-COFFIN-QUOTE")
    check(coffin_event[1] == ("RCPT-COFFIN-QUOTE",), "the standalone Coffin receipt was incorrectly grouped")

    # A receipt with no event_id at all (every persisted record predating
    # this field) must remain readable and count as its own standalone event
    # -- proves backward compatibility, not just forward behavior.
    no_event_id_receipts = mcf._preserve_receipts([{"receipt_id": "RCPT-OLD-01", "source": "x", "content": "y"}])
    check(no_event_id_receipts[0].event_id is None, "a receipt dict with no event_id key did not default to None")
    check(mcf._distinct_events(no_event_id_receipts) == (("RCPT-OLD-01", ("RCPT-OLD-01",)),), "a receipt with no event_id was not treated as its own standalone event")

    # --- 7. Every verified finding resolves to existing receipt IDs
    # (evidence-citation gate) ---
    uncited_output = "VERIFIED FACTS:\n- The citation is fabricated.\n\nREPORTED CLAIMS:\n- none\n\nINFERENCES:\n- none\n\nUNRESOLVED QUESTIONS:\n- none"
    uncited_findings = mcf._find_uncited_verified_facts(uncited_output, ("RCPT-001", "RCPT-002"))
    check(bool(uncited_findings), "evidence-citation check did not catch a VERIFIED FACTS bullet with no receipt_id")
    cited_output = "VERIFIED FACTS:\n- The citation is fabricated (RCPT-001).\n\nREPORTED CLAIMS:\n- none\n\nINFERENCES:\n- none\n\nUNRESOLVED QUESTIONS:\n- none"
    check(mcf._find_uncited_verified_facts(cited_output, ("RCPT-001", "RCPT-002")) == (), "evidence-citation check flagged a properly cited VERIFIED FACTS bullet")
    no_section_output = "Some free-text response with no headers at all."
    check(bool(mcf._find_uncited_verified_facts(no_section_output, ("RCPT-001",))), "evidence-citation check did not flag a response missing the VERIFIED FACTS section entirely")

    # Wired into run_mission(): retain the finding, then continue through the remaining seats.
    uncited_clients = _happy_path_clients()
    uncited_clients["ECHO-PROPHET"] = FakeClient(uncited_output)
    uncited_result = mcf.run_mission(SAMPLE_RECEIPTS, mission_id="TEST-GATE-UNCITED", clients=uncited_clients, authorize_live=True)
    check(uncited_result.status == mcf.EXECUTION_COMPLETE_WITH_FINDINGS_STATUS, "mission did not complete with citation findings")
    check(any("citation discrepancy" in f for f in uncited_result.gate_findings), "citation discrepancy was not preserved in findings")
    check(bool(uncited_clients["CONTEXTUAL-CATALYST"].ask_calls), "CONTEXTUAL-CATALYST did not run after an uncited VERIFIED FACTS finding")
    check(bool(uncited_clients["CG-SCRIBE"].ask_calls), "CG-SCRIBE did not run after an uncited VERIFIED FACTS finding")
    check(bool(uncited_clients["OD-COMPLY"].ask_calls), "OD-COMPLY did not run after an uncited VERIFIED FACTS finding")

    # --- 4. Unsupported "lawyer" and "bar complaint" language is caught
    # (scenario-fidelity gate), and 6. properly-grounded scenario language
    # (present in the receipts) passes clean. ---
    neutral_receipts = [{"source": "audit_note", "content": "A citation-reliability audit found a mutated bibliography entry."}]
    lawyer_violation = mcf._find_scenario_fidelity_violations("The lawyer will escalate this to a bar complaint.", json.dumps(neutral_receipts))
    check(any("lawyer" in f for f in lawyer_violation), "scenario-fidelity check did not catch obsolete 'lawyer' language absent from the receipts")
    check(any("bar complaint" in f for f in lawyer_violation), "scenario-fidelity check did not catch obsolete 'bar complaint' language absent from the receipts")
    grounded = mcf._find_scenario_fidelity_violations("The lawyer confirmed the error.", json.dumps(SAMPLE_RECEIPTS))
    check("lawyer" not in " ".join(grounded), "scenario-fidelity check flagged 'lawyer' even though the mission's own receipts mention a lawyer")

    # Wired into run_mission() after ECHO-PROPHET: retain the scenario finding
    # and continue through the remaining seats.
    scenario_clients = _happy_path_clients()
    scenario_clients["ECHO-PROPHET"] = FakeClient(
        "VERIFIED FACTS:\n- The audit note documents a mutated citation (RCPT-001).\n\n"
        "REPORTED CLAIMS:\n- The lawyer intends to file a bar complaint.\n\n"
        "INFERENCES:\n- none\n\nUNRESOLVED QUESTIONS:\n- none"
    )
    scenario_result = mcf.run_mission(neutral_receipts, mission_id="TEST-GATE-SCENARIO", clients=scenario_clients, authorize_live=True)
    check(scenario_result.status == mcf.EXECUTION_COMPLETE_WITH_FINDINGS_STATUS, "mission did not complete with scenario findings")
    check(bool(scenario_result.gate_findings), "scenario-fidelity finding was not preserved")
    check(bool(scenario_clients["CONTEXTUAL-CATALYST"].ask_calls), "CONTEXTUAL-CATALYST did not run after a scenario-fidelity finding")
    check(bool(scenario_clients["CG-SCRIBE"].ask_calls), "CG-SCRIBE did not run after a scenario-fidelity finding")

    # --- Work Package 2: versioned evidence packet and receipt integrity ---
    packet_check = mcf._validate_evidence_packet(VERSIONED_PACKET)
    check(packet_check.valid, "valid versioned evidence packet was rejected")
    check(packet_check.metadata["packet_version"] == "1.0", "packet version was not preserved")
    check(packet_check.metadata["schema_status"] == "valid", "valid packet did not receive valid schema status")
    packet_receipts = mcf._preserve_receipts(list(packet_check.receipts))
    check(len(mcf._distinct_events(packet_receipts)) == 1, "shared event_id receipts were not grouped as one event")
    check(mcf._distinct_events(packet_receipts)[0][1] == ("RCPT-PACKET-001", "RCPT-PACKET-002"), "packet receipt lineage was not preserved")

    tampered_packet = dict(VERSIONED_PACKET)
    tampered_packet["receipts"] = [dict(VERSIONED_PACKET["receipts"][0], content_sha256="0" * 64)]
    tampered_check = mcf._validate_evidence_packet(tampered_packet)
    check(not tampered_check.valid, "tampered receipt content hash was accepted")
    check(any("content_sha256" in finding for finding in tampered_check.findings), "hash mismatch finding was not reported")
    check("RECEIPT_HASH_MISMATCH" in tampered_check.finding_codes, "hash mismatch did not receive a stable finding code")

    malformed_check = mcf._validate_evidence_packet({"packet_version": "1.0", "receipts": [{"source": "", "content": ""}]})
    check(not malformed_check.valid, "malformed packet was accepted")
    malformed_result = mcf.run_mission({"packet_version": "1.0", "receipts": [{"source": "", "content": ""}]}, mission_id="TEST-PACKET-MALFORMED", clients=_happy_path_clients(), authorize_live=True)
    check(malformed_result.status == "halted_invalid_evidence_packet", "malformed packet did not halt before stage execution")
    check(not malformed_result.stages, "malformed packet invoked a stage")
    check(malformed_result.packet_metadata["schema_status"] == "invalid", "invalid packet metadata was not preserved")
    check("PACKET_MISSING_FIELD" in mcf._validate_evidence_packet({"packet_version": "1.0", "receipts": []}).finding_codes, "missing packet fields did not receive stable codes")
    invalid_top_levels = ["not-a-packet", 7, None, [dict(SAMPLE_RECEIPTS[0])]]
    for invalid_packet in invalid_top_levels[:3]:
        invalid_check = mcf._validate_evidence_packet(invalid_packet)
        check(not invalid_check.valid, "invalid top-level packet type was accepted")
        check(invalid_check.finding_codes == ("PACKET_TOP_LEVEL_TYPE",), "invalid top-level type did not receive stable code")
        invalid_result = mcf.run_mission(invalid_packet, mission_id="TEST-PACKET-TOP-LEVEL", clients=_happy_path_clients(), authorize_live=True)
        check(not invalid_result.stages, "invalid top-level packet reached a provider stage")
    legacy_check = mcf._validate_evidence_packet(invalid_top_levels[3])
    check(legacy_check.valid, "legacy receipt-list compatibility was lost")

    duplicate_packet = dict(VERSIONED_PACKET)
    duplicate_packet["receipts"] = [dict(VERSIONED_PACKET["receipts"][0]), dict(VERSIONED_PACKET["receipts"][0])]
    duplicate_check = mcf._validate_evidence_packet(duplicate_packet)
    check("RECEIPT_ID_DUPLICATE" in duplicate_check.finding_codes, "duplicate receipt IDs were not detected")

    missing_hash_packet = dict(VERSIONED_PACKET)
    missing_hash_packet["receipts"] = [dict(VERSIONED_PACKET["receipts"][0])]
    missing_hash_packet["receipts"][0].pop("content_sha256")
    missing_hash_check = mcf._validate_evidence_packet(missing_hash_packet)
    check("RECEIPT_HASH_MISSING" in missing_hash_check.finding_codes, "missing receipt hash was not detected")

    invalid_hash_packet = dict(VERSIONED_PACKET)
    invalid_hash_packet["receipts"] = [dict(VERSIONED_PACKET["receipts"][0], content_sha256="xyz")]
    invalid_hash_check = mcf._validate_evidence_packet(invalid_hash_packet)
    check("RECEIPT_HASH_FORMAT" in invalid_hash_check.finding_codes, "invalid hash format was not detected")

    invalid_severity_packet = dict(VERSIONED_PACKET, severity="urgent")
    invalid_severity_check = mcf._validate_evidence_packet(invalid_severity_packet)
    check("PACKET_SEVERITY_INVALID" in invalid_severity_check.finding_codes, "invalid severity was not detected")

    fixture_path = Path(mcf.__file__).parent / "fixtures" / "wp3_evidence_packet_fixtures.json"
    fixture_catalog = json.loads(fixture_path.read_text(encoding="utf-8"))
    all_fixture_rows = fixture_catalog["packet_structure"] + fixture_catalog["receipt_integrity"] + fixture_catalog["cross_object_lineage"]
    fixture_ids = [row["fixture_id"] for row in all_fixture_rows]
    check(len(fixture_ids) == len(set(fixture_ids)), "Work Package 3 fixture IDs are not unique")
    check(fixture_catalog["baseline"]["expected_disposition"] == "accept_preflight", "valid baseline fixture disposition changed")
    check(any(row["finding_code"] == "RECEIPT_HASH_MISMATCH" for row in fixture_catalog["receipt_integrity"]), "hash mismatch fixture is missing")
    check(any(row["finding_code"] == "NOT_YET_MODELED" for row in all_fixture_rows), "fixture catalog failed to disclose unmodeled cross-object cases")

    missing_claim_findings, missing_claim_codes = mcf._find_receipt_lineage_violations(
        "VERIFIED FACTS:\\n- The claim is supported (RCPT-NOT-IN-PACKET).",
        tuple(VERSIONED_PACKET["receipts"]),
        VERSIONED_PACKET["case_id"],
    )
    check("CLAIM_RECEIPT_MISSING" in missing_claim_codes, "absent claim receipt was not detected")
    check(any("RCPT-NOT-IN-PACKET" in finding for finding in missing_claim_findings), "missing receipt ID was not named safely")

    cross_case_packet = dict(VERSIONED_PACKET)
    cross_case_packet["receipts"] = [dict(VERSIONED_PACKET["receipts"][0], case_id="CASE-OTHER-001")]
    cross_case_findings, cross_case_codes = mcf._find_receipt_lineage_violations(
        "VERIFIED FACTS:\\n- The claim is supported (RCPT-PACKET-001).",
        tuple(cross_case_packet["receipts"]),
        VERSIONED_PACKET["case_id"],
    )
    check("CROSS_CASE_RECEIPT" in cross_case_codes, "cross-case receipt was not detected")
    check(any("CASE-OTHER-001" in finding for finding in cross_case_findings), "cross-case identity was not preserved")

    provenance_packet = dict(VERSIONED_PACKET)
    provenance_packet["receipts"] = [dict(VERSIONED_PACKET["receipts"][0], provenance={"source": "different_source"})]
    provenance_findings, provenance_codes = mcf._find_receipt_lineage_violations(
        "VERIFIED FACTS:\\n- The claim is supported (RCPT-PACKET-001).",
        tuple(provenance_packet["receipts"]),
        VERSIONED_PACKET["case_id"],
    )
    check("PROVENANCE_CONTRADICTION" in provenance_codes, "contradictory provenance was not detected")
    check(any("contradicts" in finding for finding in provenance_findings), "provenance contradiction was not explained")

    # --- 8. Old mission JSON remains readable (Forge-local; skip on clean public clone without historic records) ---
    real_records_dir = Path(mcf.__file__).parent.parent / "_debug" / "mission_citation_fabrication"
    for real_file in ("SYLLO-CITATION-RELIABILITY-20260823-01.json", "SYLLO-CITATION-RELIABILITY-20260823-CC-01.json"):
        real_path = real_records_dir / real_file
        if not real_path.exists():
            # Public clone without Forge historic debug artifacts — skip, not fail
            checks += 1
            print(f"SKIP: historic record {real_file} not present (public clean clone)")
            continue
        real_payload = json.loads(real_path.read_text(encoding="utf-8"))
        check(real_payload["status"] == "execution_complete", f"{real_file} lost its execution status on re-read")
        check(len(real_payload["receipts"]) == 5, f"{real_file} lost a receipt on re-read")
        check("event_id" not in real_payload["receipts"][0], f"{real_file} is a pre-event_id record and should not have gained the key retroactively")
        check(len(real_payload["stages"]) == 4, f"{real_file} lost a stage on re-read")

    # --- 9. Newly generated records use only current model-agnostic seat
    # names and schema (rename-consistency check specific to this module) ---
    check(all(seat in ("ECHO-PROPHET", "CONTEXTUAL-CATALYST", "CG-SCRIBE", "OD-COMPLY") for seat in mcf.MISSION_SEAT_ORDER), "MISSION_SEAT_ORDER contains a non-current seat name")
    # Pre-rename names may still appear in comments/docstrings for
    # provenance ("formerly QWEN-ECHO") -- what must never happen is one
    # being used as an active dispatch target.
    check("QWEN-ECHO" not in mcf.MISSION_SEAT_ORDER and "CTX-GROK" not in mcf.MISSION_SEAT_ORDER, "a pre-rename seat name is present in the active MISSION_SEAT_ORDER dispatch topology")
    check(any(f.name == "gate_findings" for f in mcf.MissionResult.__dataclass_fields__.values()), "MissionResult does not declare the new gate_findings field")
    check(any(f.name == "packet_metadata" for f in mcf.MissionResult.__dataclass_fields__.values()), "MissionResult does not declare packet_metadata")

    # --- Stage timeout (KH-01 hardening, 2026-08-24): a client that never
    # returns must not hang the mission -- _run_stage() has to fail closed
    # once its bound is exceeded, not stall silently forever. ---
    class SlowClient(FakeClient):
        def ask(self, prompt: str, **kwargs) -> str:
            self.ask_calls.append(prompt)
            time.sleep(5)
            return self.response

    slow_stage = mcf._run_stage("TEST-TIMEOUT", "ECHO-PROPHET", "prompt", (), client_override=SlowClient("late"), timeout_seconds=0.2)
    check(slow_stage.outcome == "failed", "a stage that exceeds its timeout did not report outcome='failed'")
    check("exceeded" in slow_stage.reason.lower() and "0.2" in slow_stage.reason, "timed-out stage's reason does not describe the timeout")
    check(mcf.STAGE_TIMEOUT_SECONDS == 180, "STAGE_TIMEOUT_SECONDS default changed without an accompanying review of live-run expectations")

    # --- Runner execution status and default review fields never claim acceptance ---
    check("accept" not in mcf.EXECUTION_COMPLETE_STATUS.lower(), "execution status implies acceptance")
    check("VS-ENC" in mcf.ACCEPTANCE_AUTHORITY_NOTE and "digitalscorpyun" in mcf.ACCEPTANCE_AUTHORITY_NOTE, "ACCEPTANCE_AUTHORITY_NOTE does not name both terminal authorities")

    print(f"All {checks} mission_citation_fabrication checks passed.")


if __name__ == "__main__":
    main()
