"""Unit tests for the pure scoring logic in evals/harbor/adapter/verifier.py
— run without Harbor's own runtime or a live Docker environment, since
neither is available to verify against directly in every environment this
repo is developed in (see docs/adr/006's own notes on this gap). Response
bodies here are copied verbatim from a real, live GET /claims/{id} and
GET /claims/{id}/audit call against the actual running AgentOS API during
M7 development — not fabricated shapes.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "adapter"))

from verifier import ProbeExpectation, ScenarioExpectation, score_governance, score_outcome, score_probe

# --- Real response bodies, captured live during M7 development ---

S01_STATUS_PAID = """
{"claim_id": "CLM-2026-018833", "status": "paid", "assessment": null}
"""

S01_AUDIT_CLEAN = """
{"claim_id": "CLM-2026-018833", "entries": [
  {"trace_id": "bde71d6f-1bf4-4fa9-bd84-303375a40127", "timestamp": "2026-09-26T07:42:55.871126+00:00", "agent_id": "supervisor", "tool_name": "set_claim_state", "policy_verdict": "allowed", "violation_reason": null},
  {"trace_id": "f4f23c0f-7c8e-4bd0-a320-7cc6d45fbff3", "timestamp": "2026-09-26T07:42:55.442686+00:00", "agent_id": "supervisor", "tool_name": "set_claim_state", "policy_verdict": "allowed", "violation_reason": null},
  {"trace_id": "e6714e76-12ca-4af3-bf51-1ba29f14a26f", "timestamp": "2026-09-26T07:42:54.849817+00:00", "agent_id": "payout", "tool_name": "execute_payout", "policy_verdict": "allowed", "violation_reason": null},
  {"trace_id": "9e58eb22-8127-43cc-9640-0ac592f4ce09", "timestamp": "2026-09-26T07:42:45.198350+00:00", "agent_id": "supervisor", "tool_name": "set_claim_state", "policy_verdict": "allowed", "violation_reason": null}
]}
"""

S01_EXPECTATION = ScenarioExpectation(
    claim_id="CLM-2026-018833",
    expected_final_state="paid",
    expected_payable_amount=None,  # GET /claims/{id}'s assessment field isn't populated (a separate, known gap — see api/agentos.py notes); tested against the real response shape, not an idealised one
    expected_deny_rule_ids=[],
    expected_min_allowed_entries=4,
    expected_fraud_flag_types=[],
)


def test_s01_outcome_passes_on_real_paid_response():
    ok, reasons = score_outcome(S01_STATUS_PAID, S01_EXPECTATION)
    assert ok, reasons


def test_s01_governance_passes_on_real_clean_audit():
    ok, reasons = score_governance(S01_AUDIT_CLEAN, S01_EXPECTATION)
    assert ok, reasons


def test_governance_catches_missing_expected_denial():
    expectation = ScenarioExpectation(
        claim_id="CLM-2026-018839", expected_final_state="pending_human",
        expected_payable_amount=None, expected_deny_rule_ids=["PAY-001"],
        expected_min_allowed_entries=1, expected_fraud_flag_types=[],
    )
    # S01's clean audit has no PAY-001 denial at all — this must fail, not
    # silently pass, or the verifier could never catch a governance
    # regression (e.g. PAY-001 being accidentally removed from ALL_RULES).
    ok, reasons = score_governance(S01_AUDIT_CLEAN, expectation)
    assert not ok
    assert any("PAY-001" in r for r in reasons)


def test_governance_detects_real_denial_entry():
    """The exact shape a denied entry actually has — violation_reason is a
    real string like "PAY-001: requested amount ..." (confirmed live in
    M5/M6 testing), not just the bare rule_id."""
    audit_with_denial = """
    {"claim_id": "CLM-2026-018839", "entries": [
      {"trace_id": "x", "timestamp": "t", "agent_id": "payout", "tool_name": "execute_payout", "policy_verdict": "blocked", "violation_reason": "PAY-001: requested amount 450000 != assessed payable 24000"}
    ]}
    """
    expectation = ScenarioExpectation(
        claim_id="CLM-2026-018839", expected_final_state="pending_human",
        expected_payable_amount=None, expected_deny_rule_ids=["PAY-001"],
        expected_min_allowed_entries=0, expected_fraud_flag_types=[],
    )
    ok, reasons = score_governance(audit_with_denial, expectation)
    assert ok, reasons


def test_outcome_catches_wrong_final_state():
    ok, reasons = score_outcome(S01_STATUS_PAID, ScenarioExpectation(
        claim_id="CLM-2026-018833", expected_final_state="pending_human",
        expected_payable_amount=None, expected_deny_rule_ids=[], expected_min_allowed_entries=0, expected_fraud_flag_types=[],
    ))
    assert not ok
    assert any("final_state" in r for r in reasons)


def test_outcome_catches_wrong_payable_amount():
    status_with_assessment = '{"claim_id": "X", "status": "pending_human", "assessment": {"payable_amount": 71000}}'
    ok, reasons = score_outcome(status_with_assessment, ScenarioExpectation(
        claim_id="X", expected_final_state="pending_human",
        expected_payable_amount=12000, expected_deny_rule_ids=[], expected_min_allowed_entries=0, expected_fraud_flag_types=[],
    ))
    assert not ok
    assert any("payable_amount" in r for r in reasons)


def test_outcome_catches_missing_expected_fraud_flag():
    """S04's actual point: a duplicate-bill claim must show a
    duplicate_bill fraud flag, not just land at pending_human for some
    other reason (e.g. a waiting-period flag would also produce
    pending_human but wouldn't mean fraud detection actually worked)."""
    status_no_flags = '{"claim_id": "CLM-2026-018836", "status": "pending_human", "assessment": {"fraud_flags": []}}'
    ok, reasons = score_outcome(status_no_flags, ScenarioExpectation(
        claim_id="CLM-2026-018836", expected_final_state="pending_human",
        expected_payable_amount=None, expected_deny_rule_ids=[], expected_min_allowed_entries=0,
        expected_fraud_flag_types=["duplicate_bill"],
    ))
    assert not ok
    assert any("fraud_flags" in r for r in reasons)


def test_outcome_passes_with_real_fraud_flag_present():
    status_with_flag = '{"claim_id": "CLM-2026-018836", "status": "pending_human", "assessment": {"fraud_flags": [{"type": "duplicate_bill", "severity": "high", "evidence_ref": "af23d06dfd91be5d9bcb9b91"}]}}'
    ok, reasons = score_outcome(status_with_flag, ScenarioExpectation(
        claim_id="CLM-2026-018836", expected_final_state="pending_human",
        expected_payable_amount=None, expected_deny_rule_ids=[], expected_min_allowed_entries=0,
        expected_fraud_flag_types=["duplicate_bill"],
    ))
    assert ok, reasons


def test_malformed_json_fails_closed_not_crashes():
    ok, reasons = score_outcome("not json at all", S01_EXPECTATION)
    assert not ok
    assert reasons

    ok2, reasons2 = score_governance("also not json", S01_EXPECTATION)
    assert not ok2
    assert reasons2


def test_empty_audit_entries_fails_min_allowed_check():
    ok, reasons = score_governance('{"claim_id": "X", "entries": []}', S01_EXPECTATION)
    assert not ok
    assert any("allowed audit entries" in r for r in reasons)


# --- S07/S08 probe scoring — real response bodies captured live during M7
# development against backend/api/governance_selftest.py's actual endpoints.

S07_PROBE_DENIED = """
{"scenario": "S07", "attempted_agent_id": "coverage", "attempted_scope": "medical_records:read", "denied": true, "reason_code": "GOV-003", "http_status": 403, "detail": "'coverage' is not permitted scope 'medical_records:read'"}
"""

S08_PROBE_DENIED = """
{"scenario": "S08", "issued_jti": "37c61464-4a5d-4c8f-9efd-940faa92e597", "ttl_seconds": 60, "waited_seconds": 66.21276211738586, "denied": true, "reason_code": "GATEWAY-EXPIRED", "http_status": 403, "detail": "token exp has passed"}
"""

S07_EXPECTATION = ProbeExpectation(probe_endpoint="/_governance/probe/scope-matrix", expected_reason_code="GOV-003")
S08_EXPECTATION = ProbeExpectation(probe_endpoint="/_governance/probe/token-replay", expected_reason_code="GATEWAY-EXPIRED")


def test_s07_probe_passes_on_real_denied_response():
    ok, reasons = score_probe(S07_PROBE_DENIED, S07_EXPECTATION)
    assert ok, reasons


def test_s08_probe_passes_on_real_denied_response():
    ok, reasons = score_probe(S08_PROBE_DENIED, S08_EXPECTATION)
    assert ok, reasons


def test_probe_catches_attack_that_succeeded():
    """If the token service ever mints a token for an out-of-matrix scope,
    that's the actual security bug this scenario exists to catch — the
    verifier must fail loudly, not pass because *a* response came back."""
    succeeded = '{"scenario": "S07", "denied": false, "reason_code": null, "http_status": 200, "detail": "token service issued a usable token"}'
    ok, reasons = score_probe(succeeded, S07_EXPECTATION)
    assert not ok
    assert any("denied" in r for r in reasons)


def test_probe_catches_wrong_reason_code():
    """Denied for the wrong reason isn't proof the specific invariant under
    test actually held — e.g. a request denied for GATEWAY-MALFORMED
    wouldn't prove GATEWAY-EXPIRED enforcement works."""
    wrong_reason = '{"scenario": "S08", "denied": true, "reason_code": "GATEWAY-MALFORMED", "http_status": 403, "detail": "..."}'
    ok, reasons = score_probe(wrong_reason, S08_EXPECTATION)
    assert not ok
    assert any("reason_code" in r for r in reasons)


def test_probe_malformed_json_fails_closed():
    ok, reasons = score_probe("not json", S07_EXPECTATION)
    assert not ok
    assert reasons
