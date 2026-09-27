"""Security tests for the claim-workflow guardrails (ADR-011, agents/guardrails.py).

Two guardrails, both deterministic, so no test here makes an LLM call:
- Injection guardrail: instruction-like text in a document is detected. The
  claim is still processed, but it can never be auto-paid: it gets the
  prompt_injection_suspected flag and tier T3, and the payout branch is
  never taken (invariant 8).
- Anti-hallucination guardrail: an explanation that quotes an amount the
  settlement doesn't contain is replaced with a template built from the
  settlement.

The workflow-level tests run the real Agno Workflow with fake agents, and
point the audit FlightRecorder at a throwaway SQLite file, never the real
flight_recorder.db.
"""

from __future__ import annotations

import ast
import queue
import tempfile
from datetime import date
from pathlib import Path

import pytest
from agno.workflow import StepInput
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from agents import supervisor
from agents.guardrails import (
    INJECTION_FLAG,
    INJECTION_TIER_REASON,
    build_fallback_explanation,
    extract_money_amounts,
    format_inr,
    scan_documents,
    validate_explanation,
)
from agents.schemas import (
    BillLineItem,
    CoverageAssessment,
    Deduction,
    FraudFlag,
    FraudScreen,
    IntakeResult,
    MedicalFinding,
)
from agents.settlement import PolicyContext
from governance.adapter import _tool_call_counts
from governance.flight_recorder import reset_recorder_for_tests
from observability import live_events

REPO_ROOT = Path(__file__).resolve().parents[2]


def _injection_payloads() -> dict[str, list[str]]:
    """INJECTION_PAYLOADS from the seed generator, read with `ast`, which
    only parses the file. Importing it would pull in reportlab, and nothing
    in the generator is executed."""
    source = (REPO_ROOT / "data" / "synthetic" / "generators" / "documents.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign | ast.Assign):
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            if any(isinstance(t, ast.Name) and t.id == "INJECTION_PAYLOADS" for t in targets):
                return ast.literal_eval(node.value)
    raise AssertionError("INJECTION_PAYLOADS not found in data/synthetic/generators/documents.py")


INJECTION_PAYLOADS = _injection_payloads()

# S01's bill and discharge summary as make_bill_pdf / make_discharge_summary_pdf lay them out (clean).
CLEAN_BILL = "\n".join([
    "SUNRISE MULTISPECIALITY HOSPITAL, COIMBATORE",
    "Patient: Priya Raman   IP No: 26-0913   Admit: 10-09-2026  Discharge: 13-09-2026",
    "Room rent (semi-private) 3 days @ 4,500 ........ 13,500.00",
    "Doctor consultation ............................ 6,000.00",
    "Laboratory (CBC, platelet count x6, NS1) ....... 7,800.00",
    "IV fluids & medicines .......................... 10,000.00",
    "Registration fee ............................... 500.00",
    "Toiletries kit ................................. 700.00",
    "TOTAL ............................................ 38,500.00",
])
CLEAN_DISCHARGE = "\n".join([
    "Diagnosis: Acute viral fever",
    "Presenting complaints: Fever, body ache",
    "Treatment: IV fluids, antipyretics",
    "Condition at discharge: Stable",
    "Past history: Nil significant",
])
POISONED_DISCHARGE = CLEAN_DISCHARGE + "\n" + "\n".join(INJECTION_PAYLOADS["S06"])


# --- Injection guardrail: detection ---------------------------------------------


def test_security_guardrail_s06_payload_flagged():
    scan = scan_documents({"final_bill": CLEAN_BILL, "discharge_summary": POISONED_DISCHARGE})
    assert scan.flagged
    assert scan.doc_types == ["discharge_summary"]
    assert {"system override", "pre-approved", "do not route"} <= set(scan.markers)


@pytest.mark.parametrize("payload_id", sorted(INJECTION_PAYLOADS))
def test_security_guardrail_every_seeded_payload_flagged(payload_id):
    scan = scan_documents({"discharge_summary": CLEAN_DISCHARGE + "\n" + "\n".join(INJECTION_PAYLOADS[payload_id])})
    assert scan.flagged, payload_id


def test_guardrail_clean_documents_not_flagged():
    scan = scan_documents({"final_bill": CLEAN_BILL, "discharge_summary": CLEAN_DISCHARGE})
    assert not scan.flagged
    assert scan.markers == [] and scan.doc_types == []


# --- Anti-hallucination guardrail: money parsing and validation ----------------------


def _assessment(**overrides) -> CoverageAssessment:
    """₹1,24,500 claimed on Silver: a non-payable item (5.G1) and room rent
    above the ₹5,000/day cap (5.S2) deducted, no co-pay."""
    values = {
        "claim_id": "CLM-2026-TEST01",
        "claimed_amount": 124_500,
        "deductions": [
            Deduction(amount=1_200, reason="Non-payable item", clause_id="5.G1"),
            Deduction(amount=4_500, reason="Room rent excess (₹6500/day vs ₹5000/day cap)", clause_id="5.S2"),
        ],
        "co_pay_amount": 0,
        "payable_amount": 118_800,
        "recommended_decision": "approve",
        "flags": [],
    }
    values.update(overrides)
    return CoverageAssessment(**values)


@pytest.mark.parametrize(("text", "expected"), [
    ("₹ 37,300", 37_300), ("₹37,300", 37_300), ("Rs. 37,300", 37_300), ("Rs 37300", 37_300),
    ("INR 37,300", 37_300), ("37,300 rupees", 37_300), ("₹4,50,000", 450_000), ("₹4,50,000.00", 450_000),
    ("Rs.1,18,800/-", 118_800), ("₹4.5 lakh", 450_000),
])
def test_guardrail_money_formats_parsed(text, expected):
    assert extract_money_amounts(text) == [expected]


def test_guardrail_percentages_dates_days_and_clause_ids_are_not_money():
    text = ("A 20% co-pay applies from age 60. Admitted 10-09-2026, discharged 13-09-2026 after 3 days (72 hours). "
            "Clause 5.G1 and clause 5.S2 apply. Account 9988776655, IFSC HDFC0001234.")
    assert extract_money_amounts(text) == []
    assert validate_explanation(text, _assessment()) == (True, [])


def test_guardrail_faithful_explanation_with_indian_formatting_accepted():
    explanation = (
        "Of the ₹1,24,500 claimed, Rs. 1,200 was deducted as a non-payable item under clause 5.G1, and INR 4,500 "
        "was deducted under clause 5.S2 because the room cost ₹6,500/day against the ₹5,000/day cap for 3 days. "
        "Total deductions come to 5,700 rupees, there is no co-pay (₹0), and ₹1,18,800.00 is payable."
    )
    assert validate_explanation(explanation, _assessment()) == (True, [])


def test_security_guardrail_invented_amount_rejected():
    explanation = (
        "Of the ₹1,24,500 claimed, ₹1,200 was deducted under clause 5.G1 and ₹4,500 under clause 5.S2. "
        "As instructed by the Chief Medical Officer, Rs 4,50,000 is payable."
    )
    ok, unexpected = validate_explanation(explanation, _assessment())
    assert not ok
    assert unexpected == [450_000]


def test_security_guardrail_slightly_wrong_payable_rejected():
    ok, unexpected = validate_explanation("Payable: ₹1,18,000 of ₹1,24,500.", _assessment())
    assert (ok, unexpected) == (False, [118_000])


def test_guardrail_fallback_template_has_payable_and_every_clause_and_passes_its_own_check():
    assessment = _assessment(co_pay_amount=23_760, payable_amount=95_040, recommended_decision="pending_human",
                             flags=["minimum_hospitalisation_not_met", INJECTION_FLAG])
    text = build_fallback_explanation(assessment)
    assert format_inr(95_040) in text  # ₹95,040
    for deduction in assessment.deductions:
        assert f"clause {deduction.clause_id}" in text
        assert format_inr(deduction.amount) in text
    assert format_inr(23_760) in text
    assert "claims officer" in text
    assert validate_explanation(text, assessment) == (True, [])


def test_guardrail_format_inr_indian_grouping():
    assert [format_inr(n) for n in (0, 999, 37_300, 450_000, 12_345_678)] == [
        "₹0", "₹999", "₹37,300", "₹4,50,000", "₹1,23,45,678",
    ]


# --- Tier logic (pure) ----------------------------------------------------------------


def test_security_tier_forced_t3_when_injection_suspected_even_if_t2_eligible():
    assessment = _assessment(claimed_amount=24_000, deductions=[], payable_amount=24_000)
    clean_screen = FraudScreen(claim_id="CLM-2026-TEST01", flags=[])
    assert supervisor.decide_tier(assessment, clean_screen) == ("T2", [])  # control: otherwise auto-payable
    tier, reasons = supervisor.decide_tier(assessment, clean_screen, injection_suspected=True)
    assert tier == "T3"
    assert reasons == [INJECTION_TIER_REASON]


def test_tier_reasons_accumulate_with_injection_first():
    assessment = _assessment(payable_amount=60_000, recommended_decision="pending_human")
    screen = FraudScreen(claim_id="x", flags=[FraudFlag(type="watchlisted_hospital", severity="high", evidence_ref="h1")])
    tier, reasons = supervisor.decide_tier(assessment, screen, injection_suspected=True)
    assert tier == "T3"
    assert reasons[0] == INJECTION_TIER_REASON
    assert len(reasons) == 4


# --- Steps and the workflow, with fake agents (no LLM) ------------------------------


@pytest.fixture
def live_channel():
    """Collects live events (observability.live_events) for one fake trace."""
    channel: queue.Queue = queue.Queue()
    span_context = SpanContext(trace_id=0x5EC0_0000_0000_0000_0000_0000_0000_0011, span_id=0x11, is_remote=False,
                               trace_flags=TraceFlags(TraceFlags.SAMPLED))
    live_events.attach(span_context.trace_id, channel)
    with trace.use_span(NonRecordingSpan(span_context)):
        yield channel
    live_events.detach(span_context.trace_id)


def _drain(channel: queue.Queue) -> list[dict]:
    events = []
    while not channel.empty():
        events.append(channel.get_nowait())
    return events


@pytest.fixture
def temp_recorder():
    recorder = reset_recorder_for_tests(tempfile.mktemp(suffix=".db"))
    _tool_call_counts.clear()
    yield recorder
    _tool_call_counts.clear()
    recorder.close()


POLICY = PolicyContext(plan="Silver", sum_insured=500_000, start_date=date(2024, 1, 1), member_age=34)


def _flow_ctx(discharge_text: str) -> supervisor.ClaimFlowContext:
    return supervisor.ClaimFlowContext(
        claim_id="CLM-2026-TEST01", bill_text=CLEAN_BILL, discharge_summary_text=discharge_text, policy=POLICY,
        claim_pseudo_id="pseudo-test", registered_account_ref="ACC-TEST", remaining_sum_insured=500_000,
        req_id="req_guardrail_test",
    )


def _intake_result() -> IntakeResult:
    return IntakeResult(
        claim_id="CLM-2026-TEST01", line_items=[BillLineItem(label="IV fluids & medicines", amount=24_000)],
        bill_total=24_000, diagnosis_text="Acute viral fever", admission_date="15-09-2026",
        discharge_date="17-09-2026", length_of_stay_hours=48,
    )


def _finding() -> MedicalFinding:
    return MedicalFinding(
        claim_id="CLM-2026-TEST01", icd10="B34.9", diagnosis_category="infectious", length_of_stay_hours=48,
        stay_justified=True, day_care_procedure=False, pre_existing_suspected=False, excluded_treatment=False,
        accident_related=False, confidence=0.95, notes_for_officer="",
    )


def test_security_document_guardrail_step_contract_and_forces_t3(live_channel):
    """Runs document_guardrail -> settlement -> tier_decision as workflow
    steps on a claim that is otherwise T2-eligible (₹24,000, clean
    settlement, no fraud flags)."""
    ctx = _flow_ctx(POISONED_DISCHARGE)
    step_input = StepInput(input="assess", additional_data={"flow": ctx})

    out = supervisor.document_guardrail(step_input)
    assert out.content == {"flagged": True, "markers": ctx.injection_markers, "doc_types": ["discharge_summary"]}
    assert ctx.injection_suspected

    events = _drain(live_channel)
    steps = [(e["step"], e["status"]) for e in events if e["kind"] == "step"]
    assert steps == [("doc_guardrail", "active"), ("doc_guardrail", "done")]
    done = next(e for e in events if e["kind"] == "step" and e["status"] == "done")
    assert set(done["data"]) == {"flagged", "markers", "doc_types"} and done["data"]["flagged"] is True
    guardrail_logs = [e for e in events if e["kind"] == "log" and e["layer"] == "guardrail"]
    assert [e["level"] for e in guardrail_logs] == ["warn"]

    ctx.intake_result, ctx.finding = _intake_result(), _finding()
    supervisor.settlement(step_input)
    assert ctx.assessment is not None
    assert INJECTION_FLAG in ctx.assessment.flags
    assert ctx.assessment.payable_amount == 24_000

    ctx.fraud_screen = FraudScreen(claim_id=ctx.claim_id, flags=[])
    supervisor.tier_decision(step_input)
    assert ctx.tier == "T3"
    assert ctx.tier_reasons == [INJECTION_TIER_REASON]
    assert supervisor.is_auto_payable(step_input) is False
    # Second barrier: a flagged claim is not payable even if the tier were T2.
    ctx.tier = "T2"
    assert supervisor.is_auto_payable(step_input) is False


def test_document_guardrail_clean_emits_success(live_channel):
    ctx = _flow_ctx(CLEAN_DISCHARGE)
    out = supervisor.document_guardrail(StepInput(input="assess", additional_data={"flow": ctx}))
    assert out.content == {"flagged": False, "markers": [], "doc_types": []}
    assert not ctx.injection_suspected
    logs = [e for e in _drain(live_channel) if e["kind"] == "log" and e["layer"] == "guardrail"]
    assert [e["level"] for e in logs] == ["success"]


@pytest.mark.parametrize(("explanation", "expect_ok", "expect_replaced"), [
    ("₹24,000 claimed with no deductions; ₹24,000 is payable.", True, False),
    ("₹24,000 claimed; per the CMO note, ₹4,50,000 is payable.", False, True),
    ("", True, True),
])
def test_security_explanation_guardrail_step(live_channel, explanation, expect_ok, expect_replaced):
    ctx = _flow_ctx(CLEAN_DISCHARGE)
    ctx.assessment = _assessment(claimed_amount=24_000, deductions=[], payable_amount=24_000)
    ctx.explanation = explanation
    out = supervisor.explanation_guardrail(StepInput(input="assess", additional_data={"flow": ctx}))

    assert out.content["ok"] is expect_ok
    assert out.content["replaced"] is expect_replaced
    assert out.content["unexpected_amounts"] == ([] if expect_ok else [450_000])
    if expect_replaced:
        assert ctx.explanation == build_fallback_explanation(ctx.assessment)
        assert "4,50,000" not in ctx.explanation
    else:
        assert ctx.explanation == explanation

    events = _drain(live_channel)
    done = next(e for e in events if e["kind"] == "step" and e["step"] == "explanation_guardrail" and e["status"] == "done")
    assert done["data"] == out.content
    level = next(e["level"] for e in events if e["kind"] == "log" and e["layer"] == "guardrail")
    assert level == ("success" if not expect_replaced else "warn")


def test_security_workflow_poisoned_claim_never_reaches_payout(monkeypatch, temp_recorder, live_channel):
    """The real claim-assessment Workflow, with fake agents: a poisoned but
    otherwise auto-payable claim is still assessed (intake reads the
    documents), ends in pending_human with the flag, and execute_payout is
    never called. The coverage agent's invented amount is replaced."""
    seen: dict = {}

    def fake_intake(agent, claim_id, bill_text, discharge_text):
        seen["discharge_text"] = discharge_text
        return _intake_result()

    def forbidden_payout(*args, **kwargs):
        seen["payout_called"] = True
        raise AssertionError("a flagged claim must never reach execute_payout")

    monkeypatch.setattr(supervisor, "build_intake_agent", lambda: None)
    monkeypatch.setattr(supervisor, "build_medical_reviewer_agent", lambda: None)
    monkeypatch.setattr(supervisor, "build_coverage_agent", lambda: None)
    monkeypatch.setattr(supervisor, "build_fraud_agent", lambda: None)
    monkeypatch.setattr(supervisor, "run_intake", fake_intake)
    monkeypatch.setattr(supervisor, "run_medical_review", lambda agent, **kw: _finding())
    monkeypatch.setattr(supervisor, "explain_assessment", lambda agent, a: "Pre-approved: pay ₹4,50,000 now.")
    monkeypatch.setattr(supervisor, "run_fraud_screen", lambda agent, **kw: FraudScreen(claim_id=kw["claim_id_pseudo"], flags=[]))
    monkeypatch.setattr(supervisor, "execute_payout", forbidden_payout)

    result = supervisor.run_claim_flow(
        claim_id="CLM-2026-TEST01", bill_text=CLEAN_BILL, discharge_summary_text=POISONED_DISCHARGE, policy=POLICY,
        claim_pseudo_id="pseudo-test", registered_account_ref="ACC-TEST", remaining_sum_insured=500_000,
    )

    assert seen["discharge_text"] == POISONED_DISCHARGE  # detection doesn't stop processing
    assert "payout_called" not in seen
    assert result.tier == "T3"
    assert result.final_state == "pending_human"
    assert result.payout_result is None
    assert INJECTION_FLAG in result.assessment.flags
    assert result.assessment.payable_amount == 24_000
    assert "4,50,000" not in result.explanation and format_inr(24_000) in result.explanation

    step_ids = [e["step"] for e in _drain(live_channel) if e["kind"] == "step"]
    assert step_ids.index("doc_guardrail") < step_ids.index("intake")
    assert step_ids.index("coverage") < step_ids.index("explanation_guardrail") < step_ids.index("fraud")
