"""Compliance controls API: the payout kill switch (GOV-004, ADR-012).

  GET  /governance/payout-freeze   current state (read fail-closed — an
                                   unreadable store reports FROZEN)
  POST /governance/payout-freeze   {frozen, officer_id, reason} — freeze or
                                   resume AUTOMATED payouts

Changing the switch is itself a governed, audited action: the request goes
through governance/adapter.check_and_audit() as agent_id="compliance_officer",
tool_name="set_payout_freeze" (the only pairing governance/tool_allowlist.py
grants it to), exactly like the claims officer's break-glass read in
api/officer.py. So every freeze and every resume — who, and the stated
reason — sits in the same append-only, hash-chained FlightRecorder log the
compliance page already shows, and GOV-001 refuses the tool to every agent.

The state is written only AFTER check_and_audit() allows it; a denial writes
nothing. As with every other governed action here, the audit entry records
the policy decision; if the write itself then fails, the endpoint returns
500 and the stored state is unchanged (the atomic write in
governance/controls.py never leaves a half-written file).

Officer-approved payouts are deliberately unaffected by the switch (GOV-004
only refuses execute_payout calls without an officer_approval_id).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from opentelemetry import trace
from pydantic import BaseModel

from governance.adapter import GovernanceDenied, ToolCallContext, check_and_audit
from governance.controls import (
    PayoutFreezeState,
    read_payout_freeze,
    write_payout_freeze,
)

router = APIRouter(prefix="/governance", tags=["governance-controls"])
tracer = trace.get_tracer("claimguard.governance_controls")

MAX_REASON_LENGTH = 500


class PayoutFreezeResponse(BaseModel):
    frozen: bool
    reason: str | None = None
    set_by: str | None = None
    set_at: str | None = None
    # True when `frozen` is forced because the stored state was unreadable.
    fail_closed: bool = False


class PayoutFreezeRequest(BaseModel):
    frozen: bool
    officer_id: str
    reason: str  # required and non-empty — every freeze/resume is justified in the audit log


class PayoutFreezeChangeResponse(PayoutFreezeResponse):
    audit_trace_id: str  # the governance.decision audit entry this change is recorded under


def _to_response(state: PayoutFreezeState) -> PayoutFreezeResponse:
    return PayoutFreezeResponse(**state.to_dict())


@router.get("/payout-freeze", response_model=PayoutFreezeResponse)
def get_payout_freeze() -> PayoutFreezeResponse:
    return _to_response(read_payout_freeze())


@router.post("/payout-freeze", response_model=PayoutFreezeChangeResponse)
def set_payout_freeze(req: PayoutFreezeRequest) -> PayoutFreezeChangeResponse:
    officer_id = req.officer_id.strip()
    reason = req.reason.strip()
    if not officer_id:
        raise HTTPException(status_code=422, detail={"reason_code": "CONTROLS-NO-OFFICER", "message": "an officer id is required to change the payout freeze"})
    if not reason:
        raise HTTPException(status_code=422, detail={"reason_code": "CONTROLS-NO-REASON", "message": "a reason is required to freeze or resume automated payouts"})
    if len(reason) > MAX_REASON_LENGTH:
        raise HTTPException(status_code=422, detail={"reason_code": "CONTROLS-REASON-TOO-LONG", "message": f"reason must be at most {MAX_REASON_LENGTH} characters"})

    req_id = f"req-{uuid.uuid4()}"
    with tracer.start_as_current_span("governance.control_change") as span:
        span.set_attribute("req_id", req_id)
        span.set_attribute("control", "payout_freeze")
        span.set_attribute("officer_id", officer_id)
        span.set_attribute("frozen", req.frozen)

        ctx = ToolCallContext(
            req_id=req_id, agent_id="compliance_officer", tool_name="set_payout_freeze",
            args={"frozen": req.frozen, "officer_id": officer_id, "reason": reason},
        )
        try:
            trace_id = check_and_audit(ctx)
        except GovernanceDenied as exc:
            span.set_attribute("decision", "deny")
            raise HTTPException(status_code=403, detail={"reason_code": exc.rule_id, "message": exc.message}) from None

        try:
            state = write_payout_freeze(frozen=req.frozen, reason=reason, set_by=officer_id)
        except OSError as exc:
            span.set_attribute("decision", "error")
            span.record_exception(exc)
            raise HTTPException(
                status_code=500,
                detail={"reason_code": "CONTROLS-WRITE-FAILED", "message": "could not store the payout freeze state; it is unchanged"},
            ) from None

        span.set_attribute("decision", "allow")
        span.set_attribute("audit_trace_id", trace_id)
        return PayoutFreezeChangeResponse(**state.to_dict(), audit_trace_id=trace_id)
