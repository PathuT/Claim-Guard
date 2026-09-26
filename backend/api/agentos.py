"""AgentOS API (docs/architecture.md §3/§4: "AgentOS API | Hosts agents,
exposes claim + decision endpoints | Agno AgentOS (FastAPI) | Semi-trusted").

The one HTTP entrypoint the Next.js console (M8) and the Harbor eval adapter
(M7, evals/harbor/adapter/) both call — neither drives agents/supervisor.py
directly. `POST /claims` submits a claim by `claim_id` (looking up its
already-seeded documents/policy from Postgres — same data every scenario's
own claim_documents rows already hold, per M1's seeding), runs the full
governed supervisor flow synchronously, and returns the terminal or
pending_human result. `GET /claims/{claim_id}` re-reads the claim's current
state from Postgres for polling (Harbor's adapter "waits for a terminal or
pending_human state" per docs/architecture.md §12 — needed even though
POST already runs synchronously, since a Harbor task may re-poll after its
own officer-decision step calls api/officer.py separately).

Scope note: this reads Postgres directly (via data_gateway.db, not the
agent-facing data_gateway HTTP API) for policy/document lookups the
supervisor itself doesn't fetch — those are the caller's job per
run_claim_flow's own contract (settlement.PolicyContext, registered_account_ref,
etc. are all assembled by the caller from trusted stores, never agent
arguments). This module is that caller, playing the same "trusted assembler"
role docs/CLAUDE.md invariant 7 already establishes for api/officer.py.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry import trace
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents.settlement import PolicyContext
from agents.supervisor import run_claim_flow
from api.claim_context import remaining_sum_insured as compute_remaining_sum_insured
from api.governance_selftest import router as governance_selftest_router
from api.state_machine import ClaimStateContext, transition
from data_gateway.db import get_session
from data_gateway.models import BankDetail, Claim, ClaimDocument, Policyholder
from data_gateway.pseudonymise import pseudonymise
from observability.tracing import setup_tracing

setup_tracing(service_name="claimguard-agentos")

app = FastAPI(title="ClaimGuard AgentOS API")
tracer = trace.get_tracer("claimguard.agentos")

# M8: the Next.js console (localhost:3005 in dev) calls this API directly
# from the browser — cross-origin, so it needs CORS. Dev-only allowlist
# (no wildcard credentials, no prod origin yet); a real deployment would
# scope this to the console's actual origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3005", "http://127.0.0.1:3005"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# S07/S08 (docs/use-case.md §8): governance self-test probes, real attack
# attempts against the token service/gateway, not claim-submission flows —
# see api/governance_selftest.py's own docstring for why these live here.
app.include_router(governance_selftest_router)


class SubmitClaimRequest(BaseModel):
    claim_id: str


class SubmitClaimResponse(BaseModel):
    claim_id: str
    tier: str | None = None
    final_state: str
    payable_amount: int | None = None
    deductions: list[dict] | None = None
    flags: list[str] | None = None
    fraud_flags: list[dict] | None = None
    explanation: str | None = None
    payout_result: dict | None = None


class ClaimStatusResponse(BaseModel):
    claim_id: str
    status: str
    assessment: dict | None = None


def _get_db() -> Session:
    db = get_session()
    try:
        yield db
    finally:
        db.close()


REQUIRED_DOC_TYPES = {"final_bill", "discharge_summary"}


@app.post("/claims", response_model=SubmitClaimResponse)
def submit_claim(req: SubmitClaimRequest, db: Session = Depends(_get_db)) -> SubmitClaimResponse:
    """Submits a claim by claim_id, using its already-seeded documents/
    policy from Postgres (see module docstring). Runs the full supervisor
    flow synchronously and returns its terminal or pending_human result —
    Harbor's own adapter (docs/architecture.md §12) still polls
    GET /claims/{claim_id} afterward in case a scripted officer decision
    (api/officer.py) needs to run first for a T3 scenario.
    """
    with tracer.start_as_current_span("claim.submit") as span:
        span.set_attribute("claim_id", req.claim_id)

        claim = db.get(Claim, req.claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail={"reason_code": "AGENTOS-NO-SUCH-CLAIM", "message": f"claim {req.claim_id!r} does not exist"})

        docs = db.execute(select(ClaimDocument).where(ClaimDocument.claim_id == req.claim_id)).scalars().all()
        doc_types_present = {d.doc_type for d in docs}

        if not REQUIRED_DOC_TYPES.issubset(doc_types_present):
            # docs/architecture.md §8: submitted -> needs_resubmission when
            # documents are missing/unreadable — checked here, before the
            # supervisor (and therefore before any agent/LLM call) even
            # runs, since "missing a required document" isn't something an
            # agent needs to discover by trying and failing to extract it.
            missing = REQUIRED_DOC_TYPES - doc_types_present
            state_ctx = ClaimStateContext(claim_id=req.claim_id, current_state="submitted")
            transition(state_ctx, "needs_resubmission", req_id=f"submit-{req.claim_id}", db=db)
            span.set_attribute("final_state", "needs_resubmission")
            span.set_attribute("missing_doc_types", sorted(missing))
            return SubmitClaimResponse(claim_id=req.claim_id, final_state="needs_resubmission")

        bill_text = next(d.extracted_text for d in docs if d.doc_type == "final_bill")
        discharge_text = next(d.extracted_text for d in docs if d.doc_type == "discharge_summary")

        policyholder = db.get(Policyholder, claim.policy_number)
        bank_detail = db.get(BankDetail, claim.policy_number)
        if policyholder is None or bank_detail is None:
            raise HTTPException(status_code=500, detail={"reason_code": "AGENTOS-MISSING-POLICY-DATA", "message": f"policy {claim.policy_number!r} is missing policyholder/bank_details rows"})
        member = next((m for m in policyholder.members if m.member_id == claim.member_id), None)
        if member is None:
            raise HTTPException(status_code=500, detail={"reason_code": "AGENTOS-MISSING-MEMBER", "message": f"member {claim.member_id!r} not found under policy {claim.policy_number!r}"})

        policy = PolicyContext(
            plan=policyholder.plan, sum_insured=policyholder.sum_insured,
            start_date=policyholder.start_date, member_age=member.age,
        )
        remaining_sum_insured = compute_remaining_sum_insured(db, claim.policy_number, policyholder.sum_insured)
        claim_pseudo_id = pseudonymise(req.claim_id, salt="claim_id")

        # submitted -> assessing before the supervisor runs, matching
        # docs/architecture.md §8's diagram — the supervisor's own
        # transitions (assessing -> auto_approved/pending_human) assume
        # this step already happened.
        state_ctx = ClaimStateContext(claim_id=req.claim_id, current_state="submitted")
        transition(state_ctx, "assessing", req_id=f"submit-{req.claim_id}", db=db)

        result = run_claim_flow(
            claim_id=req.claim_id, bill_text=bill_text, discharge_summary_text=discharge_text,
            policy=policy, claim_pseudo_id=claim_pseudo_id,
            registered_account_ref=bank_detail.account_number, remaining_sum_insured=remaining_sum_insured,
            db=db,
        )

        span.set_attribute("tier", result.tier)
        span.set_attribute("final_state", result.final_state)

        # Persist the assessment (+ fraud flags) to Claim.assessment (JSONB)
        # — found while building the Harbor eval verifier that neither had
        # ever been written back to Postgres (same class of gap as
        # Claim.status before api/state_machine.transition()'s own db= fix):
        # GET /claims/{id} always returned assessment=None and no fraud
        # flags at all, so a polling caller (the eval verifier — S04/S05/
        # S10 specifically need to see the fraud flag itself, not just
        # infer it from landing at pending_human, which several different
        # reasons can also cause — or the future console) had no way to see
        # them without the original POST response still in hand. Fraud
        # flags fold into this same JSONB blob rather than a new column:
        # there is no dedicated fraud_flags column on Claim, and adding one
        # is a real schema migration for what's still freeform per-claim
        # data the model itself doesn't need to query on.
        claim.assessment = {
            "claim_id": result.assessment.claim_id,
            "claimed_amount": result.assessment.claimed_amount,
            "deductions": [d.model_dump() for d in result.assessment.deductions],
            "co_pay_amount": result.assessment.co_pay_amount,
            "payable_amount": result.assessment.payable_amount,
            "recommended_decision": result.assessment.recommended_decision,
            "flags": result.assessment.flags,
            "fraud_flags": [f.model_dump() for f in result.fraud_screen.flags],
            # M8 (Console): the officer T3 queue needs the medical
            # reviewer's own reasoning, not just coverage's flags — same
            # class of "computed but never persisted" gap M7 found twice
            # already for claim.status/claim.assessment itself.
            # notes_for_officer is explicitly meant for a human reviewer
            # (schemas.py's own docstring: "shown only to officers, never
            # passed to other agents"), so surfacing it here is the field
            # doing its documented job, not a new exposure.
            "medical_finding": result.finding.model_dump(),
            # M8 (Console): the agent-pipeline visualization needs proof
            # intake actually ran and extracted structured data, not just
            # the downstream agents' outputs. Deliberately NOT
            # result.intake_result.model_dump() as-is: IntakeResult also
            # carries diagnosis_text, the raw medical text docs/CLAUDE.md
            # invariant 4 says only medical_reviewer may ever see —
            # persisting it here into a field every Console role reads back
            # (policyholder, officer, compliance) would leak it straight
            # past that boundary. Only the claims-side fields are kept.
            "intake_summary": {
                "line_items": [li.model_dump() for li in result.intake_result.line_items],
                "bill_total": result.intake_result.bill_total,
                "admission_date": result.intake_result.admission_date,
                "discharge_date": result.intake_result.discharge_date,
                "length_of_stay_hours": result.intake_result.length_of_stay_hours,
            },
        }
        db.commit()

        return SubmitClaimResponse(
            claim_id=result.claim_id,
            tier=result.tier,
            final_state=result.final_state,
            payable_amount=result.assessment.payable_amount,
            deductions=[d.model_dump() for d in result.assessment.deductions],
            flags=result.assessment.flags,
            fraud_flags=[f.model_dump() for f in result.fraud_screen.flags],
            explanation=result.explanation,
            payout_result=result.payout_result,
        )


class ClaimSummaryResponse(BaseModel):
    claim_id: str
    policy_number: str
    member_id: str
    status: str
    claimed_amount: int
    stated_illness: str
    assessment: dict | None = None


class ClaimListResponse(BaseModel):
    claims: list[ClaimSummaryResponse]


@app.get("/claims", response_model=ClaimListResponse)
def list_claims(
    policy_number: str | None = None,
    status: str | None = None,
    db: Session = Depends(_get_db),
) -> ClaimListResponse:
    """M8 (Console): the policyholder view finds a policy's own claims by
    policy_number; the officer T3 queue lists every claim currently at
    status=pending_human. Neither existed before M8 — every other endpoint
    here requires already knowing the exact claim_id, which a human opening
    the console for the first time never does. Ordered newest-first so a
    freshly submitted claim (or a freshly queued T3 case) is easy to find
    without scrolling.
    """
    query = select(Claim)
    if policy_number is not None:
        query = query.where(Claim.policy_number == policy_number)
    if status is not None:
        query = query.where(Claim.status == status)
    query = query.order_by(Claim.created_at.desc())

    claims = db.execute(query).scalars().all()
    return ClaimListResponse(
        claims=[
            ClaimSummaryResponse(
                claim_id=c.claim_id, policy_number=c.policy_number, member_id=c.member_id,
                status=c.status, claimed_amount=c.claimed_amount, stated_illness=c.stated_illness,
                assessment=c.assessment,
            )
            for c in claims
        ]
    )


@app.get("/claims/{claim_id}", response_model=ClaimStatusResponse)
def get_claim_status(claim_id: str, db: Session = Depends(_get_db)) -> ClaimStatusResponse:
    """Polling endpoint — re-reads current state straight from Postgres, not
    from any in-memory result of the POST above, since api/officer.py may
    have moved the claim on since (pending_human -> approved/paid/rejected)."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail={"reason_code": "AGENTOS-NO-SUCH-CLAIM", "message": f"claim {claim_id!r} does not exist"})
    return ClaimStatusResponse(claim_id=claim.claim_id, status=claim.status, assessment=claim.assessment)


class AuditEntryResponse(BaseModel):
    trace_id: str
    timestamp: str
    agent_id: str
    tool_name: str
    policy_verdict: str
    violation_reason: str | None = None


class ClaimAuditResponse(BaseModel):
    claim_id: str
    entries: list[AuditEntryResponse]


@app.get("/claims/{claim_id}/audit", response_model=ClaimAuditResponse)
def get_claim_audit(claim_id: str) -> ClaimAuditResponse:
    """Read-only governance-evidence endpoint for the Harbor eval verifier
    (docs/architecture.md §12: "Governance evidence: expected audit
    entries... by rule_id"). Filters FlightRecorder's full log down to this
    claim's own entries by the `claim_id=` marker governance/adapter.py now
    writes into each entry's input_prompt field (see that module's own
    docstring for why input_prompt, not tool_args, carries it) — query_logs()
    itself has no claim_id filter, only agent_id/policy_verdict/time range.

    Deliberately excludes tool_args/result from the response: this endpoint
    is read by an eval verifier checking governance behaviour (which rule,
    allow or deny), not a place that should ever re-expose whatever
    sensitive values (account numbers, medical text) a denied or allowed
    tool call's own args happened to carry — same redact-by-default
    discipline as observability/redaction.py, applied here by simply never
    including those fields in the first place.
    """
    from governance.flight_recorder import get_recorder

    recorder = get_recorder()
    marker = f"claim_id={claim_id}"
    matching = [entry for entry in recorder.query_logs(limit=1000) if entry.get("input_prompt") and marker in entry["input_prompt"]]
    return ClaimAuditResponse(
        claim_id=claim_id,
        entries=[
            AuditEntryResponse(
                trace_id=e["trace_id"], timestamp=e["timestamp"], agent_id=e["agent_id"],
                tool_name=e["tool_name"], policy_verdict=e["policy_verdict"], violation_reason=e.get("violation_reason"),
            )
            for e in matching
        ],
    )


class AuditLogResponse(BaseModel):
    entries: list[AuditEntryResponse]


@app.get("/audit", response_model=AuditLogResponse)
def get_audit_log(policy_verdict: str | None = None, limit: int = 200) -> AuditLogResponse:
    """M8 (Console): the compliance role's audit-log viewer — the
    system-wide counterpart to /claims/{id}/audit's per-claim view.
    `policy_verdict="blocked"` narrows this to denials specifically
    (docs/plan.md M8: "audit log viewer, denials..."). Same safe field
    subset as the per-claim endpoint (no tool_args/result) for the same
    reason: this is a governance-behaviour view, not a raw-data export.

    No medical-data-specific filter is offered here because none of the
    current agent pipeline's tool calls are actually named/tagged as a
    medical_records read at the FlightRecorder level — medical_reviewer
    receives already-extracted diagnosis_text as a plain argument from
    intake, in-process, not via a gateway-mediated read_medical_records
    tool call (see agents/medical_reviewer.py). The compliance view's own
    UI says this plainly rather than fabricating a filter that would
    always return nothing.
    """
    from governance.flight_recorder import get_recorder

    recorder = get_recorder()
    entries = recorder.query_logs(policy_verdict=policy_verdict, limit=limit)
    return AuditLogResponse(
        entries=[
            AuditEntryResponse(
                trace_id=e["trace_id"], timestamp=e["timestamp"], agent_id=e["agent_id"],
                tool_name=e["tool_name"], policy_verdict=e["policy_verdict"], violation_reason=e.get("violation_reason"),
            )
            for e in entries
        ]
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
