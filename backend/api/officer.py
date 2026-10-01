"""Officer decision API (docs/plan.md M5: "Officer decision API; token
revocation at terminal/pending_human states").

The only way a claim leaves `pending_human` (docs/architecture.md §8: "There
is no edge from assessing to rejected. Only an officer creates rejected" —
invariant 6). Every decision here is itself a real `set_claim_state` call
through api/state_machine.transition(), so STATE-001 ("no rejection without
an officer decision record") is enforced by the same governance path a
supervisor-driven transition goes through, not a separate, weaker check.

For an `approved`/`approved_partial` decision on a high-value or
fraud-flagged claim, the officer's own decision *is* the officer_approval_id
PAY-003/PAY-004 require — this endpoint is what supplies it, then calls
payout for real, exactly like the supervisor's own T2 payout path.

set_claim_state calls here go through as agent_id="supervisor", not a new
"officer_api" identity: security-matrix.md §7's tool allowlist grants
set_claim_state to supervisor specifically (the coordinating role, not any
specific human), and this endpoint is enacting a human's decision through
that same coordinating role, not acting as a distinct autonomous agent that
would need its own AGT identity/token-service scope entry. `req.officer_id`
is what's recorded in `officer_decision_id`/the audit trail as the actual
accountable human (docs/use-case.md §10's "human accountable for
repudiations"), not the tool-call identity.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.officer_assistant import (
    MAX_HISTORY_CHARS,
    MAX_HISTORY_MESSAGES,
    MAX_QUESTION_CHARS,
    answer_question,
    build_claim_context,
)
from agents.payout import PayoutContext, execute_payout
from api.claim_context import remaining_sum_insured as compute_remaining_sum_insured
from data_gateway.db import get_session
from data_gateway.models import BankDetail, Claim, ClaimDocument, Policyholder
from governance.adapter import GovernanceDenied, ToolCallContext, check_and_audit
from governance.client import ToolCallDenied, new_req_id
from observability.live_events import emit
from observability.terminal_log import quiet_polling_access_logs
from observability.tracing import setup_tracing

from .state_machine import ClaimStateContext, InvalidTransition, transition

setup_tracing(service_name="claimguard-officer-api")
# Terminal: keep the story, drop the console's polling GETs (observability/terminal_log.py).
quiet_polling_access_logs()

app = FastAPI(title="ClaimGuard Officer Decision API")
tracer = trace.get_tracer("claimguard.officer_api")

# M8: the Next.js console's officer view calls this API directly from the
# browser (localhost:3005 in dev) — same rationale as api/agentos.py's
# CORS setup.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3005", "http://127.0.0.1:3005"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_db() -> Session:
    db = get_session()
    try:
        yield db
    finally:
        db.close()

DecisionType = Literal["approved", "approved_partial", "rejected"]

# pending_human -> {approved, approved_partial, rejected} per api/state_machine.TRANSITIONS —
# repeated here as the request schema's own literal type, not imported, so the
# API's OpenAPI schema documents the valid values directly.
_DECISION_TO_STATE: dict[DecisionType, str] = {
    "approved": "approved",
    "approved_partial": "approved_partial",
    "rejected": "rejected",
}


class OfficerDecisionRequest(BaseModel):
    claim_id: str
    officer_id: str
    decision: DecisionType
    completed_steps: list[str]  # what the claim actually completed before reaching pending_human
    reason: str  # required for every decision, not just rejection — IRDAI "clear reasons" (docs/use-case.md §10)
    # For approved/approved_partial only: the amount to actually pay (may
    # differ from the original assessed_payable for approved_partial) and
    # the trusted values payout's PAY-* rules check against.
    payout_amount: int | None = None
    registered_account_ref: str | None = None
    remaining_sum_insured: int | None = None
    fraud_flags: list[str] | None = None
    already_paid: bool = False


class OfficerReviewResponse(BaseModel):
    claim_id: str
    policy_number: str
    status: str
    claimed_amount: int
    stated_illness: str
    assessment: dict | None
    # Trusted, server-computed payout context (docs/engineering-guide.md invariant 7):
    # the officer decides an amount and outcome; these are never the
    # Console's to supply, so the review endpoint hands them back for the
    # Console to echo verbatim in its POST /decisions call, exactly the way
    # api/agentos.py's own submit_claim computes and uses them itself.
    registered_account_ref: str
    remaining_sum_insured: int


@app.get("/claims/{claim_id}/review", response_model=OfficerReviewResponse)
def get_claim_for_review(claim_id: str, db: Session = Depends(_get_db)) -> OfficerReviewResponse:
    """M8 (Console): everything the officer T3 queue's detail view and
    decision form need for one claim — the claim + its assessment (flags,
    deductions, fraud_flags, medical_finding) plus the trusted
    registered_account_ref/remaining_sum_insured a payout decision needs.
    Previously these last two were computed only inside api/agentos.py's
    own submit_claim, entirely private to that one request — no caller,
    including a human officer, had any way to know them without re-deriving
    them insecurely client-side (found while wiring up the officer console
    view; fixed by pulling that computation into api/claim_context.py,
    shared by both API modules now)."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail={"reason_code": "OFFICER-NO-SUCH-CLAIM", "message": f"claim {claim_id!r} does not exist"})

    policyholder = db.get(Policyholder, claim.policy_number)
    bank_detail = db.get(BankDetail, claim.policy_number)
    if policyholder is None or bank_detail is None:
        raise HTTPException(status_code=500, detail={"reason_code": "OFFICER-MISSING-POLICY-DATA", "message": f"policy {claim.policy_number!r} is missing policyholder/bank_details rows"})

    return OfficerReviewResponse(
        claim_id=claim.claim_id, policy_number=claim.policy_number, status=claim.status,
        claimed_amount=claim.claimed_amount, stated_illness=claim.stated_illness,
        assessment=claim.assessment,
        registered_account_ref=bank_detail.account_number,
        remaining_sum_insured=compute_remaining_sum_insured(db, claim.policy_number, policyholder.sum_insured),
    )


class AssistantMessage(BaseModel):
    role: Literal["officer", "assistant"]
    content: str = Field(max_length=MAX_HISTORY_CHARS)


class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[AssistantMessage] = Field(default_factory=list, max_length=MAX_HISTORY_MESSAGES)


class AssistantStep(BaseModel):
    tool: str
    decision: Literal["allow", "deny"]
    rule_id: str | None = None


class AssistantResponse(BaseModel):
    claim_id: str
    answer: str
    steps: list[AssistantStep]  # the agent's tool calls, each checked and audited by AGT
    replaced: bool  # the model's answer quoted an amount not in the claim, so it was replaced
    unexpected_amounts: list[int]


@app.post("/claims/{claim_id}/assistant", response_model=AssistantResponse)
def ask_claim_assistant(claim_id: str, req: AssistantRequest, db: Session = Depends(_get_db)) -> AssistantResponse:
    """ADR-014: an agent with read-only tools answers questions about one
    claim. Its tools read the same data GET /claims/{id}/review returns,
    minus the fields the model must never see (agents/officer_assistant.py);
    every tool call goes through the AGT adapter. No writes, no data scope."""
    if not req.question.strip():
        raise HTTPException(status_code=422, detail={"reason_code": "ASSISTANT-EMPTY-QUESTION", "message": "ask a question about this claim"})

    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail={"reason_code": "OFFICER-NO-SUCH-CLAIM", "message": f"claim {claim_id!r} does not exist"})
    policyholder = db.get(Policyholder, claim.policy_number)
    if policyholder is None:
        raise HTTPException(status_code=500, detail={"reason_code": "OFFICER-MISSING-POLICY-DATA", "message": f"policy {claim.policy_number!r} has no policyholder row"})

    context = build_claim_context(
        claim_id=claim.claim_id, status=claim.status, assessment=claim.assessment,
        remaining_sum_insured=compute_remaining_sum_insured(db, claim.policy_number, policyholder.sum_insured),
    )

    req_id = new_req_id()
    with tracer.start_as_current_span("officer.assistant") as span:
        span.set_attribute("req_id", req_id)
        span.set_attribute("claim_id", claim_id)
        span.set_attribute("question_chars", len(req.question))
        span.set_attribute("history_messages", len(req.history))
        try:
            result = answer_question(
                context, claim_id, req.question.strip(), [m.model_dump() for m in req.history], req_id=req_id,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed: no answer rather than a guess
            span.set_attribute("error", type(exc).__name__)
            emit("agent", f"Officer assistant could not answer about {claim_id}", f"{type(exc).__name__}: {exc}"[:300], level="error")
            raise HTTPException(status_code=502, detail={"reason_code": "ASSISTANT-UNAVAILABLE", "message": "The assistant could not answer right now. Try again."}) from None
        span.set_attribute("model_called", result.model_called)
        span.set_attribute("tools_called", [s.tool for s in result.steps])
        span.set_attribute("tools_denied", [s.tool for s in result.steps if s.decision == "deny"])
        span.set_attribute("replaced", result.replaced)
        span.set_attribute("unexpected_amounts", result.unexpected_amounts)

    tools_used = ", ".join(s.tool for s in result.steps) or "no tools"
    if result.replaced:
        emit("guardrail", f"Officer assistant answer replaced for {claim_id}",
             f"quoted amount(s) not in the settlement: {result.unexpected_amounts}", level="warn")
    else:
        emit("agent", f"Officer assistant answered a question about {claim_id}", f"read-only · tools: {tools_used}", level="success")

    return AssistantResponse(
        claim_id=claim_id, answer=result.answer,
        steps=[AssistantStep(tool=s.tool, decision=s.decision, rule_id=s.rule_id) for s in result.steps],
        replaced=result.replaced, unexpected_amounts=result.unexpected_amounts,
    )


class BreakGlassRequest(BaseModel):
    officer_id: str
    reason: str  # required — security-matrix.md §9: "audited break-glass (reason required)"


class BreakGlassResponse(BaseModel):
    claim_id: str
    discharge_summary_text: str
    audit_trace_id: str  # the exact governance.decision trace this access is recorded under


@app.post("/claims/{claim_id}/break-glass/discharge-summary", response_model=BreakGlassResponse)
def break_glass_discharge_summary(claim_id: str, req: BreakGlassRequest, db: Session = Depends(_get_db)) -> BreakGlassResponse:
    """docs/plan.md M8 / docs/security-matrix.md §9: the one console
    capability that deliberately bypasses the normal "only intake/
    medical_reviewer ever see medical_records" restriction (docs/engineering-guide.md
    invariant 4, enforced for agents by DATA-001) — for a human officer,
    reading Postgres directly (same trusted-assembler pattern as every
    other endpoint here), gated on a required reason and logged through the
    exact same governance audit path (check_and_audit) an agent's tool call
    goes through, under a distinct agent_id ("claims_officer") and tool_name
    ("break_glass_discharge_summary_access") registered in
    governance/tool_allowlist.py for exactly this. Appears in the
    Compliance role's audit log (GET /audit on api/agentos.py) exactly like
    any other governed decision — this endpoint is itself the "medical-data
    access report" entry for a break-glass read, not a separate reporting
    mechanism.

    Not gated by DATA-001/the token service/data gateway at all: those
    exist to constrain AUTONOMOUS AGENTS, and a human officer's own audited
    exception is a different, already-accountable actor (docs/use-case.md
    §10's "human accountable for repudiations") — the reason + audit trail
    ARE the control here, not a scope denial.
    """
    if not req.reason.strip():
        raise HTTPException(status_code=422, detail={"reason_code": "OFFICER-BREAK-GLASS-NO-REASON", "message": "a reason is required to open the full discharge summary"})

    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail={"reason_code": "OFFICER-NO-SUCH-CLAIM", "message": f"claim {claim_id!r} does not exist"})

    doc = db.execute(
        select(ClaimDocument).where(ClaimDocument.claim_id == claim_id, ClaimDocument.doc_type == "discharge_summary")
    ).scalars().first()
    if doc is None:
        raise HTTPException(status_code=404, detail={"reason_code": "OFFICER-NO-DISCHARGE-SUMMARY", "message": f"claim {claim_id!r} has no discharge_summary document"})

    req_id = new_req_id()
    ctx = ToolCallContext(
        req_id=req_id, agent_id="claims_officer", tool_name="break_glass_discharge_summary_access",
        args={"officer_id": req.officer_id, "reason": req.reason}, claim_id=claim_id,
    )
    try:
        trace_id = check_and_audit(ctx)
    except GovernanceDenied as exc:
        # Not expected in practice (GOV-001 only fires for an
        # unregistered agent/tool pairing, and claims_officer/this tool
        # name is registered specifically for this) — kept fail-closed
        # anyway per docs/engineering-guide.md invariant 7, rather than assuming this
        # branch is unreachable.
        raise HTTPException(status_code=403, detail={"reason_code": exc.rule_id, "message": exc.message}) from None

    return BreakGlassResponse(claim_id=claim_id, discharge_summary_text=doc.extracted_text, audit_trace_id=trace_id)


class OfficerDecisionResponse(BaseModel):
    claim_id: str
    officer_decision_id: str
    new_state: str
    payout_result: dict | None = None


@app.post("/decisions", response_model=OfficerDecisionResponse)
def decide(req: OfficerDecisionRequest, db: Session = Depends(_get_db)) -> OfficerDecisionResponse:
    officer_decision_id = f"officer-decision-{uuid.uuid4()}"
    req_id = new_req_id()
    new_state = _DECISION_TO_STATE[req.decision]

    with tracer.start_as_current_span("human.decision") as span:
        span.set_attribute("officer_id", req.officer_id)
        span.set_attribute("claim_id", req.claim_id)
        span.set_attribute("decision", req.decision)

        state_ctx = ClaimStateContext(
            claim_id=req.claim_id,
            current_state="pending_human",
            completed_steps=set(req.completed_steps),
            officer_decision_id=officer_decision_id,
        )
        try:
            transition(state_ctx, new_state, req_id=req_id, agent_id="supervisor", db=db)
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail={"reason_code": "INVALID-TRANSITION", "message": str(exc)}) from None
        except ToolCallDenied as exc:
            raise HTTPException(status_code=403, detail={"reason_code": exc.reason_code, "message": exc.message}) from None

        payout_result: dict | None = None
        if req.decision in ("approved", "approved_partial"):
            if req.payout_amount is None or req.registered_account_ref is None or req.remaining_sum_insured is None:
                raise HTTPException(
                    status_code=422,
                    detail={"reason_code": "OFFICER-MISSING-PAYOUT-CONTEXT", "message": "approved/approved_partial requires payout_amount, registered_account_ref, remaining_sum_insured"},
                )
            payout_ctx = PayoutContext(
                assessed_payable=req.payout_amount,
                registered_account_ref=req.registered_account_ref,
                remaining_sum_insured=req.remaining_sum_insured,
                fraud_flags=req.fraud_flags or [],
                already_paid=req.already_paid,
                officer_approval_id=officer_decision_id,  # supplies the PAY-003/004 approval record
            )
            try:
                payout_result = execute_payout(
                    req.claim_id, amount=req.payout_amount,
                    account_ref=req.registered_account_ref, req_id=req_id, ctx=payout_ctx,
                )
            except ToolCallDenied as exc:
                raise HTTPException(status_code=403, detail={"reason_code": exc.reason_code, "message": exc.message}) from None

            paid_ctx = ClaimStateContext(claim_id=req.claim_id, current_state=new_state, completed_steps=set(req.completed_steps))
            transition(paid_ctx, "paid", req_id=req_id, agent_id="supervisor", db=db)
            new_state = "paid"

        return OfficerDecisionResponse(
            claim_id=req.claim_id, officer_decision_id=officer_decision_id,
            new_state=new_state, payout_result=payout_result,
        )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
