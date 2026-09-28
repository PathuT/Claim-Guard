"""Officer claim assistant (ADR-014): an Agno agent with read-only tools.

Covers what the tools can return, that every tool call goes through the AGT
adapter (allowlist, budget, audit), and the ₹-amount check on the answer.
No DB, no network: tools read an in-memory claim view, and a fake agent
stands in for the model."""

from __future__ import annotations

import json
import tempfile
from types import SimpleNamespace

import pytest

from agents.officer_assistant import (
    ASSISTANT_AGENT_ID,
    ASSISTANT_TOOLS,
    NO_ASSESSMENT_ANSWER,
    answer_question,
    build_claim_context,
    build_prompt,
    build_tools,
    check_answer,
)
from governance.adapter import (
    GovernanceDenied,
    ToolCallContext,
    _tool_call_counts,
    check_and_audit,
)
from governance.flight_recorder import reset_recorder_for_tests
from governance.tool_allowlist import TOOL_CALL_BUDGET_PER_REQUEST, tool_allowed

NOTES = "Platelet trend consistent with dengue admission; history of similar episode in 2024."

ASSESSMENT = {
    "claim_id": "CLM-TEST-1",
    "claimed_amount": 38_500,
    "deductions": [
        {"amount": 700, "reason": "Non-payable consumables (toiletries)", "clause_id": "5.C1"},
        {"amount": 500, "reason": "Registration fee not payable", "clause_id": "5.C2"},
    ],
    "co_pay_amount": 0,
    "payable_amount": 37_300,
    "recommended_decision": "approve",
    "flags": [],
    "fraud_flags": [{"type": "watchlisted_hospital", "severity": "high", "evidence_ref": "hospital:H-021"}],
    "medical_finding": {
        "claim_id": "CLM-TEST-1", "icd10": "A90", "diagnosis_category": "infectious_disease",
        "length_of_stay_hours": 72, "stay_justified": True, "day_care_procedure": False,
        "pre_existing_suspected": False, "excluded_treatment": False, "accident_related": False,
        "confidence": 0.93, "notes_for_officer": NOTES,
    },
    "intake_summary": {
        "line_items": [{"label": "Room rent (semi-private) 3 days", "amount": 13_500}],
        "bill_total": 38_500, "admission_date": "10-09-2026", "discharge_date": "13-09-2026",
        "length_of_stay_hours": 72,
    },
    "processing_ms": 41_000,
}


def _context(**overrides):
    assessment = {**ASSESSMENT, **overrides}
    return build_claim_context(claim_id="CLM-TEST-1", status="pending_human", assessment=assessment, remaining_sum_insured=4_62_700)


@pytest.fixture
def recorder():
    rec = reset_recorder_for_tests(tempfile.mktemp(suffix=".db"))
    _tool_call_counts.clear()
    yield rec
    _tool_call_counts.clear()
    rec.close()


def _tools(context, req_id="req_assistant_test"):
    steps: list = []
    return {fn.__name__: fn for fn in build_tools(context, req_id=req_id, steps=steps)}, steps


class FakeAgent:
    """Stands in for the model. `calls` names the tools it 'decides' to use."""

    def __init__(self, reply, tools=(), calls=()):
        self.reply = reply
        self.tools = {fn.__name__: fn for fn in tools}
        self.calls = calls
        self.prompts: list[str] = []
        self.tool_results: dict[str, dict] = {}

    def run(self, message):
        self.prompts.append(message)
        for name in self.calls:
            self.tool_results[name] = json.loads(self.tools[name]())
        return SimpleNamespace(content=self.reply)


def _factory(reply, calls=()):
    made: list[FakeAgent] = []

    def factory(tools):
        agent = FakeAgent(reply, tools, calls)
        made.append(agent)
        return agent

    return factory, made


# --- What the model can see ----------------------------------------------------


def test_claim_view_never_carries_officer_notes_or_unlisted_fields():
    dumped = json.dumps(_context())
    assert NOTES not in dumped
    assert "notes_for_officer" not in dumped
    assert "processing_ms" not in dumped


def test_claim_view_is_none_without_an_assessment():
    assert build_claim_context(claim_id="C", status="submitted", assessment=None, remaining_sum_insured=1) is None


def test_prompt_holds_the_claim_id_and_question_but_no_claim_data():
    prompt = build_prompt("CLM-TEST-1", "and the co-pay?", [
        {"role": "officer", "content": "why deducted?"},
        {"role": "assistant", "content": "clause 5.C1"},
    ])
    assert "CLM-TEST-1" in prompt
    assert "37300" not in prompt and "37,300" not in prompt
    assert prompt.index("Officer: why deducted?") < prompt.index("Assistant: clause 5.C1") < prompt.index("OFFICER'S QUESTION:")


def test_medical_finding_tool_returns_the_structured_finding_only(recorder):
    tools, _ = _tools(_context())
    finding = json.loads(tools["get_medical_finding"]())
    assert finding["icd10"] == "A90"
    assert "notes_for_officer" not in finding
    assert NOTES not in json.dumps(finding)


def test_routing_reasons_use_the_pipelines_own_tiering(recorder):
    tools, _ = _tools(_context())
    routing = json.loads(tools["get_routing_reasons"]())
    assert routing["tier"] == "T3"
    assert any("fraud flag" in r for r in routing["reasons"])


def test_routing_reasons_note_when_tiering_alone_would_have_auto_paid(recorder):
    tools, _ = _tools(_context(fraud_flags=[]))
    routing = json.loads(tools["get_routing_reasons"]())
    assert routing["tier"] == "T2" and routing["reasons"] == []
    assert "note" in routing


# --- Governance: every tool call goes through the AGT adapter ------------------


def test_every_assistant_tool_is_on_its_allowlist():
    assert all(tool_allowed(ASSISTANT_AGENT_ID, name) for name in ASSISTANT_TOOLS)


@pytest.mark.parametrize("tool", [
    "execute_payout", "set_claim_state", "read_bank_details", "read_medical_record",
    "break_glass_discharge_summary_access", "set_payout_freeze",
])
def test_security_assistant_cannot_reach_any_action_or_restricted_tool(recorder, tool):
    with pytest.raises(GovernanceDenied) as denied:
        check_and_audit(ToolCallContext(req_id="req_x", agent_id=ASSISTANT_AGENT_ID, tool_name=tool, args={}, claim_id="CLM-TEST-1"))
    assert denied.value.rule_id == "GOV-001"
    blocked = recorder.query_logs(policy_verdict="blocked")
    assert [(e["agent_id"], e["tool_name"]) for e in blocked] == [(ASSISTANT_AGENT_ID, tool)]


def test_each_tool_call_is_audited_and_recorded_as_a_step(recorder):
    tools, steps = _tools(_context())
    settlement = json.loads(tools["get_settlement"]())
    assert settlement["payable_amount"] == 37_300
    assert [(s.tool, s.decision) for s in steps] == [("get_settlement", "allow")]
    allowed = recorder.query_logs(policy_verdict="allowed")
    assert [(e["agent_id"], e["tool_name"]) for e in allowed] == [(ASSISTANT_AGENT_ID, "get_settlement")]


def test_security_tool_budget_denies_and_the_tool_returns_a_denial_not_data(recorder):
    tools, steps = _tools(_context(), req_id="req_budget")
    for _ in range(TOOL_CALL_BUDGET_PER_REQUEST):
        tools["get_claim_overview"]()
    over = json.loads(tools["get_settlement"]())
    assert over == {"denied": "GOV-002", "reason": over["reason"]}
    assert steps[-1].decision == "deny" and steps[-1].rule_id == "GOV-002"


# --- The agent loop and the answer check ---------------------------------------


def test_no_assessment_answers_without_building_an_agent():
    factory, made = _factory("should not be used")
    result = answer_question(None, "CLM-TEST-1", "why?", agent_factory=factory)
    assert result.answer == NO_ASSESSMENT_ANSWER
    assert result.model_called is False and made == []


def test_agent_tool_calls_are_returned_as_steps(recorder):
    factory, made = _factory(
        "Payable is ₹37,300 after ₹1,200 of deductions; it is with you because of a high-severity fraud flag.",
        calls=("get_settlement", "get_routing_reasons"),
    )
    result = answer_question(_context(), "CLM-TEST-1", "why is this with me?", agent_factory=factory)
    assert result.replaced is False
    assert [(s.tool, s.decision) for s in result.steps] == [("get_settlement", "allow"), ("get_routing_reasons", "allow")]
    assert NOTES not in made[0].prompts[0]


@pytest.mark.parametrize("answer", [
    "Payable is ₹37,300 after ₹700 and ₹500 in deductions.",
    "Deductions total ₹1,200; the bill total was ₹38,500.",
    "Remaining sum insured is ₹4,62,700. Room rent was ₹13,500.",
    "Anything above ₹50,000 always needs an officer.",
    "No amounts in this one.",
])
def test_answers_with_only_claim_amounts_pass(answer):
    assert check_answer(answer, _context()) == []


def test_invented_amount_replaces_the_answer(recorder):
    factory, _ = _factory("The payable amount is ₹45,000.")
    result = answer_question(_context(), "CLM-TEST-1", "what is payable?", agent_factory=factory)
    assert result.replaced is True
    assert result.unexpected_amounts == [45_000]
    assert "₹45,000" in result.answer and "not in this claim's settlement" in result.answer


def test_markdown_bold_is_stripped(recorder):
    factory, _ = _factory("  The claim is **pending_human** because of a fraud flag.  ")
    result = answer_question(_context(), "CLM-TEST-1", "status?", agent_factory=factory)
    assert result.answer == "The claim is pending_human because of a fraud flag."


@pytest.mark.parametrize("reply", ["", "   ", None])
def test_empty_model_output_fails_closed(recorder, reply):
    factory, _ = _factory(reply)
    with pytest.raises(ValueError):
        answer_question(_context(), "CLM-TEST-1", "anything?", agent_factory=factory)
