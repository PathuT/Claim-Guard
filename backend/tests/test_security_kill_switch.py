"""Security tests for the compliance payout kill switch (GOV-004, ADR-012).

Covers the three parts end to end:
  - governance/controls.py: fail-closed reads, atomic writes
  - GOV-004 through the real check_and_audit() entrypoint: automated payouts
    frozen, officer-approved payouts unaffected, the freeze state comes from
    the trusted store only (a caller-supplied value cannot override it)
  - api/governance_controls.py: the toggle is governed + audited and
    requires a reason

Every test runs against a throwaway controls file (GOVERNANCE_CONTROLS_PATH)
and a throwaway FlightRecorder — never the real governance_controls.json or
flight_recorder.db, and no server or LLM is involved.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from governance.adapter import (
    GovernanceDenied,
    ToolCallContext,
    _tool_call_counts,
    check_and_audit,
)
from governance.controls import (
    CONTROLS_PATH_ENV,
    PayoutFreezeState,
    controls_path,
    read_payout_freeze,
    write_payout_freeze,
)
from governance.flight_recorder import reset_recorder_for_tests
from governance.rules import gov_004_automated_payouts_frozen


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv(CONTROLS_PATH_ENV, str(tmp_path / "governance_controls.json"))
    recorder = reset_recorder_for_tests(str(tmp_path / "flight_recorder.db"))
    _tool_call_counts.clear()
    yield recorder
    _tool_call_counts.clear()
    recorder.close()


def _payout_ctx(req_id: str = "req_kill_switch", **trusted_overrides) -> ToolCallContext:
    """An automated T2 payout that satisfies every PAY/DATA rule, so GOV-004
    is the only thing that can refuse it."""
    trusted = {
        "assessed_payable": 37_300,
        "registered_account_ref": "ACC-123",
        "remaining_sum_insured": 500_000,
        "fraud_flags": [],
        "already_paid": False,
        "officer_approval_id": None,
        "known_bank_accounts": {"ACC-123"},
    }
    trusted.update(trusted_overrides)
    return ToolCallContext(
        req_id=req_id, agent_id="payout", tool_name="execute_payout",
        args={"amount": 37_300, "account_ref": "ACC-123"}, claim_id="CLM-2026-000001", trusted=trusted,
    )


def _freeze(reason: str = "suspected payout-fraud wave under investigation") -> None:
    write_payout_freeze(frozen=True, reason=reason, set_by="compliance-divya")


# --- controls store ---

def test_security_kill_switch_missing_file_is_not_frozen():
    assert not controls_path().exists()
    state = read_payout_freeze()
    assert state.frozen is False and state.fail_closed is False


def test_security_kill_switch_write_is_atomic_and_round_trips(tmp_path):
    _freeze("incident INC-42")
    state = read_payout_freeze()
    assert state.frozen is True and state.fail_closed is False
    assert state.reason == "incident INC-42" and state.set_by == "compliance-divya" and state.set_at
    # the temp file was renamed into place, nothing left behind, and fail_closed is never persisted
    assert sorted(p.name for p in tmp_path.iterdir() if "governance_controls" in p.name) == ["governance_controls.json"]
    assert "fail_closed" not in json.loads(controls_path().read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"reason": "no frozen key"}',
        '{"frozen": "false"}',  # a string is not a boolean
        '{"frozen": 0}',
        '{"frozen": false, "reason": 42}',
        "",
    ],
)
def test_security_kill_switch_corrupt_state_reads_as_frozen(content):
    controls_path().write_text(content, encoding="utf-8")
    state = read_payout_freeze()
    assert state.frozen is True
    assert state.fail_closed is True


# --- GOV-004 through check_and_audit ---

def test_security_gov004_automated_payout_denied_when_frozen():
    _freeze("suspected payout-fraud wave under investigation")
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(_payout_ctx())
    assert exc.value.rule_id == "GOV-004"
    assert "automated payouts are frozen by compliance" in exc.value.message
    assert "suspected payout-fraud wave under investigation" in exc.value.message


def test_security_gov004_automated_payout_allowed_when_not_frozen():
    check_and_audit(_payout_ctx())  # no file at all -> not frozen -> no raise
    write_payout_freeze(frozen=False, reason="incident closed", set_by="compliance-divya")
    check_and_audit(_payout_ctx(req_id="req_kill_switch_2"))  # explicitly resumed -> no raise


def test_security_gov004_officer_approved_payout_allowed_while_frozen():
    _freeze()
    check_and_audit(_payout_ctx(officer_approval_id="officer-decision-abc"))  # human decision -> no raise


def test_security_gov004_caller_supplied_freeze_state_cannot_override_store():
    _freeze()
    for spoofed in (False, {"frozen": False}, PayoutFreezeState(frozen=False)):
        with pytest.raises(GovernanceDenied) as exc:
            check_and_audit(_payout_ctx(req_id=f"req_spoof_{type(spoofed).__name__}", payout_freeze=spoofed))
        assert exc.value.rule_id == "GOV-004"


def test_security_gov004_caller_trusted_dict_not_mutated():
    trusted_before = _payout_ctx().trusted
    ctx = ToolCallContext(
        req_id="req_no_mutation", agent_id="payout", tool_name="execute_payout",
        args={"amount": 37_300, "account_ref": "ACC-123"}, claim_id="CLM-2026-000001", trusted=trusted_before,
    )
    check_and_audit(ctx)
    assert "payout_freeze" not in trusted_before


def test_security_gov004_corrupt_state_file_denies_payout():
    controls_path().write_text("{corrupted", encoding="utf-8")
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(_payout_ctx())
    assert exc.value.rule_id == "GOV-004"
    assert "unreadable" in exc.value.message


def test_security_gov004_takes_precedence_over_pay_rules_when_frozen():
    """While frozen, an automated payout that PAY-001 would also refuse is
    reported as GOV-004 — one unambiguous reason for the emergency stop."""
    _freeze()
    ctx = _payout_ctx()
    ctx.args["amount"] = 450_000
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(ctx)
    assert exc.value.rule_id == "GOV-004"


def test_security_gov004_does_not_affect_other_tools_when_frozen():
    _freeze()
    check_and_audit(ToolCallContext(req_id="req_other_tool", agent_id="fraud", tool_name="read_hospital", args={}))


def test_security_gov004_rule_fails_closed_without_trusted_state():
    """Called outside check_and_audit (so the trusted store was never read):
    the rule itself refuses rather than assuming 'not frozen'."""
    result = gov_004_automated_payouts_frozen(_payout_ctx())
    assert result.allowed is False and result.rule_id == "GOV-004"


def test_security_gov004_denial_is_audited(_isolated):
    _freeze("incident INC-7")
    with pytest.raises(GovernanceDenied):
        check_and_audit(_payout_ctx())
    blocked = _isolated.query_logs(policy_verdict="blocked", limit=10)
    assert len(blocked) == 1
    assert blocked[0]["tool_name"] == "execute_payout"
    assert blocked[0]["violation_reason"].startswith("GOV-004:")
    assert "incident INC-7" in blocked[0]["violation_reason"]


def test_security_gov001_agent_cannot_lift_the_freeze():
    """No agent holds set_payout_freeze — only the compliance_officer console role."""
    for agent_id in ("payout", "supervisor", "claims_officer"):
        with pytest.raises(GovernanceDenied) as exc:
            check_and_audit(ToolCallContext(
                req_id=f"req_lift_{agent_id}", agent_id=agent_id, tool_name="set_payout_freeze",
                args={"frozen": False, "officer_id": "x", "reason": "please"},
            ))
        assert exc.value.rule_id == "GOV-001"


# --- toggle endpoint (api/governance_controls.py) ---

@pytest.fixture
def client() -> TestClient:
    from api.governance_controls import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_security_toggle_get_reports_state(client):
    assert client.get("/governance/payout-freeze").json()["frozen"] is False
    controls_path().write_text("{corrupted", encoding="utf-8")
    body = client.get("/governance/payout-freeze").json()
    assert body["frozen"] is True and body["fail_closed"] is True


@pytest.mark.parametrize("reason", ["", "   "])
def test_security_toggle_rejects_empty_reason(client, _isolated, reason):
    response = client.post("/governance/payout-freeze", json={"frozen": True, "officer_id": "compliance-divya", "reason": reason})
    assert response.status_code == 422
    assert response.json()["detail"]["reason_code"] == "CONTROLS-NO-REASON"
    assert not controls_path().exists()  # nothing written
    assert _isolated.query_logs(limit=10) == []  # and no allow entry was recorded


def test_security_toggle_rejects_empty_officer(client):
    response = client.post("/governance/payout-freeze", json={"frozen": True, "officer_id": " ", "reason": "incident"})
    assert response.status_code == 422
    assert not controls_path().exists()


def test_security_toggle_freeze_and_resume_are_audited(client, _isolated):
    response = client.post(
        "/governance/payout-freeze",
        json={"frozen": True, "officer_id": "compliance-divya", "reason": "payout anomaly INC-9"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["frozen"] is True and body["set_by"] == "compliance-divya" and body["reason"] == "payout anomaly INC-9"
    assert read_payout_freeze().frozen is True
    assert client.get("/governance/payout-freeze").json()["frozen"] is True

    # the freeze now actually stops an automated payout
    with pytest.raises(GovernanceDenied) as exc:
        check_and_audit(_payout_ctx())
    assert exc.value.rule_id == "GOV-004" and "payout anomaly INC-9" in exc.value.message

    response = client.post(
        "/governance/payout-freeze",
        json={"frozen": False, "officer_id": "compliance-divya", "reason": "INC-9 closed"},
    )
    assert response.status_code == 200 and response.json()["frozen"] is False
    check_and_audit(_payout_ctx(req_id="req_after_resume"))  # no raise

    toggles = [e for e in _isolated.query_logs(limit=50) if e["tool_name"] == "set_payout_freeze"]
    assert len(toggles) == 2
    assert all(e["agent_id"] == "compliance_officer" and e["policy_verdict"] == "allowed" for e in toggles)
    audit_ids = {e["trace_id"] for e in toggles}
    assert body["audit_trace_id"] in audit_ids
    recorded_reasons = {json.loads(e["tool_args"])["reason"] if isinstance(e["tool_args"], str) else e["tool_args"]["reason"] for e in toggles}
    assert recorded_reasons == {"payout anomaly INC-9", "INC-9 closed"}
    assert _isolated.verify_integrity()["valid"] is True


def test_security_toggle_resume_recovers_from_corrupt_state(client):
    controls_path().write_text("{corrupted", encoding="utf-8")
    response = client.post(
        "/governance/payout-freeze",
        json={"frozen": False, "officer_id": "compliance-divya", "reason": "controls file repaired after disk fault"},
    )
    assert response.status_code == 200
    state = read_payout_freeze()
    assert state.frozen is False and state.fail_closed is False
