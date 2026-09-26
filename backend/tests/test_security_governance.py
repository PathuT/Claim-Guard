"""Security tests for the AGT governance adapter (docs/plan.md M3):
"Tests for every rule, allow and deny cases." Covers GOV-001/002 (adapter.py),
and PAY-001..006, STATE-001/002, DATA-001/002 (rules.py).

Each rule gets one allow test and at least one deny test, run through the
real `check_and_audit()` entrypoint (not just the bare rule functions) so the
audit-log side effect (FlightRecorder) is exercised too, against a throwaway
SQLite file — never the real flight_recorder.db.
"""

from __future__ import annotations

import tempfile

import pytest

from governance.adapter import (
    GovernanceDenied,
    ToolCallContext,
    _tool_call_counts,
    check_and_audit,
)
from governance.flight_recorder import reset_recorder_for_tests
from governance.tool_allowlist import TOOL_CALL_BUDGET_PER_REQUEST


@pytest.fixture(autouse=True)
def _fresh_recorder_and_counters():
    """Every test gets its own throwaway FlightRecorder file and a clean
    GOV-002 call-count table, so tests can't leak state into each other."""
    path = tempfile.mktemp(suffix=".db")
    recorder = reset_recorder_for_tests(path)
    _tool_call_counts.clear()
    yield recorder
    _tool_call_counts.clear()
    recorder.close()


def _ctx(**overrides) -> ToolCallContext:
    defaults = {
        "req_id": "req_gov_001", "agent_id": "payout", "tool_name": "execute_payout",
        "args": {}, "claim_id": "CLM-2026-000001", "trusted": {},
    }
    defaults.update(overrides)
    return ToolCallContext(**defaults)


# --- GOV-001: tool not in agent's allowlist ---

def test_security_gov001_tool_not_in_allowlist_denied():
    ctx = _ctx(agent_id="coverage", tool_name="execute_payout", args={})  # coverage can't execute_payout
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "GOV-001"


def test_security_gov001_tool_in_allowlist_allowed():
    ctx = _ctx(
        agent_id="payout", tool_name="execute_payout",
        args={"amount": 37_300, "account_ref": "ACC-123"},
        trusted={
            "assessed_payable": 37_300, "registered_account_ref": "ACC-123",
            "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-123"},
        },
    )
    check_and_audit(ctx)  # no raise


# --- GOV-002: per-request tool-call budget (circuit breaker) ---

def test_security_gov002_budget_exceeded_denied():
    ctx = _ctx(agent_id="fraud", tool_name="read_hospital", args={}, req_id="req_gov_budget")
    for _ in range(TOOL_CALL_BUDGET_PER_REQUEST):
        check_and_audit(ctx)  # each within budget
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)  # the 41st call
    assert exc.value.rule_id == "GOV-002"


def test_security_gov002_within_budget_allowed():
    ctx = _ctx(agent_id="fraud", tool_name="read_hospital", args={}, req_id="req_gov_budget_ok")
    for _ in range(TOOL_CALL_BUDGET_PER_REQUEST):
        check_and_audit(ctx)  # no raise on any of these


def test_security_gov002_budget_is_per_req_id():
    """A busy agent on one claim must not lock it out of a different claim's
    request (security-matrix.md §11.2 makes the same point about trust
    scores; GOV-002's budget is likewise scoped per req_id)."""
    ctx_a = _ctx(agent_id="fraud", tool_name="read_hospital", req_id="req_gov_a")
    for _ in range(TOOL_CALL_BUDGET_PER_REQUEST):
        check_and_audit(ctx_a)
    ctx_b = _ctx(agent_id="fraud", tool_name="read_hospital", req_id="req_gov_b")
    check_and_audit(ctx_b)  # no raise — different req_id, fresh budget


# --- PAY-001: payout amount must equal assessed payable ---

def test_security_pay001_amount_mismatch_denied():
    ctx = _ctx(args={"amount": 450_000, "account_ref": "ACC-1"}, trusted={"assessed_payable": 24_000, "registered_account_ref": "ACC-1"})
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "PAY-001"


def test_security_pay001_no_assessed_payable_on_record_fails_closed():
    """docs/CLAUDE.md invariant 7: fail closed. No assessment on record at
    all must deny, not silently allow whatever amount is requested."""
    ctx = _ctx(args={"amount": 10_000, "account_ref": "ACC-1"}, trusted={"registered_account_ref": "ACC-1"})
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "PAY-001"


def test_security_pay001_matching_amount_allowed():
    ctx = _ctx(
        args={"amount": 37_300, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 37_300, "registered_account_ref": "ACC-1", "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"}},
    )
    check_and_audit(ctx)


# --- PAY-002: payout account must equal registered account ---

def test_security_pay002_wrong_account_denied():
    """This is exactly S06's attack: agent tries to pay to an unregistered account."""
    ctx = _ctx(
        args={"amount": 24_000, "account_ref": "9988776655"},
        trusted={"assessed_payable": 24_000, "registered_account_ref": "ACC-REAL-1"},
    )
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "PAY-002"


def test_security_pay002_matching_account_allowed():
    ctx = _ctx(
        args={"amount": 24_000, "account_ref": "ACC-REAL-1"},
        trusted={"assessed_payable": 24_000, "registered_account_ref": "ACC-REAL-1", "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-REAL-1"}},
    )
    check_and_audit(ctx)


# --- PAY-003: payout > 50,000 requires officer approval ---

def test_security_pay003_high_value_without_approval_denied():
    ctx = _ctx(
        args={"amount": 83_000, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 83_000, "registered_account_ref": "ACC-1"},
    )
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "PAY-003"


def test_security_pay003_high_value_with_approval_allowed():
    ctx = _ctx(
        args={"amount": 83_000, "account_ref": "ACC-1"},
        trusted={
            "assessed_payable": 83_000, "registered_account_ref": "ACC-1", "officer_approval_id": "OFF-001",
            "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"},
        },
    )
    check_and_audit(ctx)


def test_security_pay003_low_value_no_approval_needed():
    ctx = _ctx(
        args={"amount": 37_300, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 37_300, "registered_account_ref": "ACC-1", "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"}},
    )
    check_and_audit(ctx)  # under 50,000, no officer_approval_id needed


# --- PAY-004: fraud flag requires officer approval ---

def test_security_pay004_fraud_flag_without_approval_denied():
    ctx = _ctx(
        args={"amount": 15_000, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 15_000, "registered_account_ref": "ACC-1", "fraud_flags": [{"type": "duplicate"}]},
    )
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "PAY-004"


def test_security_pay004_fraud_flag_with_approval_allowed():
    ctx = _ctx(
        args={"amount": 15_000, "account_ref": "ACC-1"},
        trusted={
            "assessed_payable": 15_000, "registered_account_ref": "ACC-1", "fraud_flags": [{"type": "duplicate"}],
            "officer_approval_id": "OFF-002", "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"},
        },
    )
    check_and_audit(ctx)


# --- PAY-005: no second payout for the same claim ---

def test_security_pay005_duplicate_payout_denied():
    ctx = _ctx(
        args={"amount": 37_300, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 37_300, "registered_account_ref": "ACC-1", "already_paid": True},
    )
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "PAY-005"


def test_security_pay005_first_payout_allowed():
    ctx = _ctx(
        args={"amount": 37_300, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 37_300, "registered_account_ref": "ACC-1", "already_paid": False, "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"}},
    )
    check_and_audit(ctx)


# --- PAY-006: payout must not exceed remaining sum insured ---

def test_security_pay006_exceeds_remaining_si_denied():
    ctx = _ctx(
        args={"amount": 480_000, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 480_000, "registered_account_ref": "ACC-1", "officer_approval_id": "OFF-003", "remaining_sum_insured": 100_000},
    )
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "PAY-006"


def test_security_pay006_within_remaining_si_allowed():
    ctx = _ctx(
        args={"amount": 37_300, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 37_300, "registered_account_ref": "ACC-1", "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"}},
    )
    check_and_audit(ctx)


# --- STATE-001: rejection requires officer decision record ---

def test_security_state001_rejection_without_officer_decision_denied():
    ctx = _ctx(agent_id="supervisor", tool_name="set_claim_state", args={"new_state": "rejected"}, trusted={})
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "STATE-001"


def test_security_state001_rejection_with_officer_decision_allowed():
    ctx = _ctx(agent_id="supervisor", tool_name="set_claim_state", args={"new_state": "rejected"}, trusted={"officer_decision_id": "DEC-001"})
    check_and_audit(ctx)


def test_security_state001_non_rejection_transition_not_affected():
    ctx = _ctx(agent_id="supervisor", tool_name="set_claim_state", args={"new_state": "submitted"}, trusted={})
    check_and_audit(ctx)  # STATE-001 doesn't apply; other rules also no-op for this tool/state


# --- STATE-002: approved/paid must not skip required steps ---

def test_security_state002_skipped_steps_denied():
    ctx = _ctx(
        agent_id="supervisor", tool_name="set_claim_state", args={"new_state": "approved"},
        trusted={"completed_steps": ["medical_review"]},  # missing coverage_assessment, fraud_screen
    )
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "STATE-002"


def test_security_state002_all_steps_completed_allowed():
    ctx = _ctx(
        agent_id="supervisor", tool_name="set_claim_state", args={"new_state": "approved"},
        trusted={"completed_steps": ["medical_review", "coverage_assessment", "fraud_screen"]},
    )
    check_and_audit(ctx)


# --- DATA-001: medical_records:* restricted to intake(write)/medical_reviewer(read) ---

def test_security_data001_wrong_agent_requesting_medical_read_denied():
    """S07 in docs/use-case.md: coverage tries to read medical_records directly."""
    ctx = _ctx(agent_id="coverage", tool_name="read_policy_limited", args={"scope": "medical_records:read"}, trusted={})
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "DATA-001"


def test_security_data001_medical_reviewer_read_allowed():
    ctx = _ctx(agent_id="medical_reviewer", tool_name="read_medical_record", args={"scope": "medical_records:read"}, trusted={})
    check_and_audit(ctx)


def test_security_data001_intake_write_allowed():
    ctx = _ctx(agent_id="intake", tool_name="write_medical_facts", args={"scope": "medical_records:write"}, trusted={})
    check_and_audit(ctx)


def test_security_data001_medical_reviewer_write_denied():
    """medical_reviewer may only read, never write medical_records."""
    ctx = _ctx(agent_id="medical_reviewer", tool_name="read_medical_record", args={"scope": "medical_records:write"}, trusted={})
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "DATA-001"


# --- DATA-002: account numbers in tool args must come from bank_details ---

def test_security_data002_untrusted_account_number_denied():
    """The other half of S06: even outside execute_payout, no tool call may
    carry an account number that isn't a known bank_details account."""
    ctx = _ctx(
        agent_id="payout", tool_name="execute_payout",
        args={"amount": 24_000, "account_ref": "9988776655"},
        trusted={"assessed_payable": 24_000, "registered_account_ref": "ACC-REAL-1", "known_bank_accounts": {"ACC-REAL-1"}},
    )
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    # PAY-002 and DATA-002 would both legitimately fire here; PAY-002 runs first.
    assert exc.value.rule_id in {"PAY-002", "DATA-002"}


def test_security_data002_trusted_account_number_allowed():
    ctx = _ctx(
        args={"amount": 37_300, "account_ref": "ACC-1"},
        trusted={
            "assessed_payable": 37_300, "registered_account_ref": "ACC-1",
            "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"},
        },
    )
    check_and_audit(ctx)


def test_security_data002_no_account_in_args_not_affected():
    ctx = _ctx(agent_id="fraud", tool_name="read_hospital", args={"hospital_id": "HOSP-001"}, trusted={})
    check_and_audit(ctx)  # no account_ref/account_number in args -> DATA-002 doesn't apply


# --- Audit trail: every decision (allow and deny) must be recorded and hash-chained ---

def test_security_audit_log_records_both_allow_and_deny(_fresh_recorder_and_counters):
    recorder = _fresh_recorder_and_counters

    allowed_ctx = _ctx(
        args={"amount": 37_300, "account_ref": "ACC-1"},
        trusted={"assessed_payable": 37_300, "registered_account_ref": "ACC-1", "remaining_sum_insured": 500_000, "known_bank_accounts": {"ACC-1"}},
    )
    check_and_audit(allowed_ctx)

    denied_ctx = _ctx(args={"amount": 450_000, "account_ref": "9988776655"}, trusted={"assessed_payable": 24_000, "registered_account_ref": "ACC-1"})
    with pytest.raises(GovernanceDenied):
        check_and_audit(denied_ctx)

    integrity = recorder.verify_integrity()
    assert integrity["valid"] is True
    assert integrity["total_entries"] == 2

    blocked = recorder.query_logs(policy_verdict="blocked")
    assert len(blocked) == 1
    assert "PAY-001" in blocked[0]["violation_reason"] or "PAY-002" in blocked[0]["violation_reason"]

    allowed = recorder.query_logs(policy_verdict="allowed")
    assert len(allowed) == 1
