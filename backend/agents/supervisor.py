"""Supervisor: the claim-assessment pipeline as an Agno Workflow.

The fixed sequence docs/architecture.md §7 specifies (intake ->
medical_reviewer -> coverage -> fraud -> payout) is an `agno.workflow.
Workflow` of deterministic `Step`s plus one `Condition`:

    intake -> medical_review -> settlement -> coverage_explanation ->
    fraud_screen -> tier_decision -> Condition(T2?)
                                        yes: governed_payout
                                        no:  route_to_officer

Why a Workflow and not an Agno Team: every real `agno.team.TeamMode`
(coordinate / route / broadcast / tasks — confirmed by reading
agno/team/mode.py) has an LLM "leader" deciding which member runs and in
what order. For this flow that would be wrong three ways: it adds an LLM
call per delegation (cost, latency, and pressure on the provider's token
rate limit), and it puts sequencing — e.g. "fraud screening always runs
before payout" — into the hands of a model that reads attacker-controlled
documents. docs/architecture.md §2: "The LLM is an untrusted
decision-maker. Enforcement is deterministic code." Agno Workflows are the
framework's own deterministic orchestration: the order and the T2/T3
branch are code, and each LLM step is still a real Agno Agent run.

Each step's executor is plain Python that calls one Agno Agent (or none,
for settlement / tiering / payout). Executors rather than `Step(agent=...)`
because the agents' inputs are assembled deliberately — documents wrapped
as delimited untrusted data for intake, only the coded medical finding for
everything downstream — rather than "previous step's text in, next agent".
Step retries are disabled (max_retries=0): LLM rate limits are retried at
the model layer (agents/model_config.py), and a governed payout must never
be silently re-attempted by the orchestrator.

Trusted context (policy terms, registered account, remaining sum insured,
the DB session) travels in `additional_data["flow"]`, assembled by the
caller from Postgres — never from workflow input, which is untrusted. The
same workflow is registered in Agno's AgentOS (api/agentos.py) for
visibility; started without trusted context, its first step refuses.

Fraud and payout go through the real governance/token/gateway chain
(governance/client.py); state transitions go through api/state_machine.py,
itself a governed tool call.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agno.workflow import Condition, Step, StepInput, StepOutput, Workflow
from opentelemetry import trace

from api.state_machine import ClaimStateContext, transition
from governance.client import ToolCallDenied, new_req_id
from observability.live_events import emit, step

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from .coverage import build_coverage_agent, explain_assessment
from .fraud import build_fraud_agent, run_fraud_screen
from .intake import build_intake_agent, run_intake
from .medical_reviewer import build_medical_reviewer_agent, run_medical_review
from .payout import PayoutContext, execute_payout
from .schemas import CoverageAssessment, FraudScreen, IntakeResult, MedicalFinding
from .settlement import PolicyContext, compute_settlement

PAYOUT_AUTO_LIMIT = 50_000  # docs/use-case.md §6, T2 ceiling — same value governance/rules.py enforces

WORKFLOW_ID = "claim-assessment"

tracer = trace.get_tracer("claimguard.supervisor")


@dataclass
class ClaimFlowResult:
    claim_id: str
    intake_result: IntakeResult
    finding: MedicalFinding
    assessment: CoverageAssessment
    explanation: str
    fraud_screen: FraudScreen
    tier: str  # "T2" | "T3"
    final_state: str  # "paid" | "pending_human"
    payout_result: dict | None = None


@dataclass
class ClaimFlowContext:
    """Trusted inputs (assembled by the caller from Postgres) plus each
    step's typed result. Passed to the workflow as additional_data["flow"]."""

    claim_id: str
    bill_text: str
    discharge_summary_text: str
    policy: PolicyContext
    claim_pseudo_id: str
    registered_account_ref: str
    remaining_sum_insured: int
    req_id: str
    db: Session | None = None
    intake_result: IntakeResult | None = None
    finding: MedicalFinding | None = None
    assessment: CoverageAssessment | None = None
    explanation: str | None = None
    fraud_screen: FraudScreen | None = None
    tier: str | None = None
    tier_reasons: list[str] = field(default_factory=list)
    final_state: str | None = None
    payout_result: dict | None = None
    state: ClaimStateContext | None = None
    error: str | None = None


def _tier(assessment: CoverageAssessment, fraud_screen: FraudScreen) -> str:
    """docs/use-case.md §6: T2 is "payout <= 50,000, all checks passed, no
    flags"; T3 is everything else that isn't a plain read/write (>50,000,
    any fraud flag, any exclusion/waiting-period issue, any rejection).
    coverage's own recommended_decision already folds in every
    exclusion/waiting-period/confidence check medical_reviewer's finding
    feeds into (settlement.py computes recommended_decision FROM finding,
    so nothing here needs the finding directly) — this only adds the two
    things settlement.py can't know about: the payout ceiling and the
    fraud screen."""
    if assessment.recommended_decision != "approve":
        return "T3"
    if fraud_screen.flags:
        return "T3"
    if assessment.payable_amount > PAYOUT_AUTO_LIMIT:
        return "T3"
    return "T2"


class MissingTrustedContext(RuntimeError):
    pass


def _ctx(step_input: StepInput) -> ClaimFlowContext:
    ctx = (step_input.additional_data or {}).get("flow")
    if not isinstance(ctx, ClaimFlowContext):
        raise MissingTrustedContext(
            "claim-assessment needs trusted context assembled by the API from Postgres "
            "(start claims with POST /claims or POST /claims/{id}/live) — workflow input is untrusted"
        )
    return ctx


def _fail_closed(fn):
    """Agno keeps running later steps after a step raises and still reports
    the run `completed` (verified against agno 3.0.11). For a pipeline that
    ends in a payout that is the wrong default, so every step is wrapped: an
    exception is recorded on the context and the workflow is stopped
    (StepOutput(stop=True)) — nothing after a failed step runs, and
    run_claim_flow raises instead of returning a half-assessed claim
    (docs/CLAUDE.md invariant 7, fail closed)."""

    @functools.wraps(fn)
    def wrapper(step_input: StepInput) -> StepOutput:
        try:
            return fn(step_input)
        except Exception as exc:  # noqa: BLE001 - converted to a stopped run, re-raised by run_claim_flow
            message = f"{fn.__name__} failed: {type(exc).__name__}: {exc}"
            flow = (step_input.additional_data or {}).get("flow")
            if isinstance(flow, ClaimFlowContext):
                flow.error = message
            emit("agent", f"Workflow stopped at '{fn.__name__}' — failing closed", message[:300], level="error")
            return StepOutput(content=message, success=False, error=message, stop=True)

    return wrapper


# --- Steps -------------------------------------------------------------------


def intake(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    step("intake", "active")
    emit("agent", "Intake agent reading the documents", "Agno agent · document text passed as delimited UNTRUSTED data in the user turn, never in the system prompt")
    raw = run_intake(build_intake_agent(), ctx.claim_id, ctx.bill_text, ctx.discharge_summary_text)
    # An agent that couldn't produce its typed output (e.g. the provider
    # failed after every retry) returns text instead — fail loudly rather
    # than carry an unvalidated result into money maths.
    result = IntakeResult.model_validate_json(raw) if isinstance(raw, str) else raw
    ctx.intake_result = result
    emit(
        "agent", "Intake produced a schema-validated IntakeResult",
        f"{len(result.line_items)} bill line item(s) · bill total ₹{result.bill_total:,} · "
        f"{result.admission_date} → {result.discharge_date} · {result.length_of_stay_hours}h stay",
        level="success",
    )
    step("intake", "done", f"{len(result.line_items)} line items, bill total ₹{result.bill_total:,}", {
        "line_items": [li.model_dump() for li in result.line_items],
        "bill_total": result.bill_total,
        "length_of_stay_hours": result.length_of_stay_hours,
    })
    # Step content is the claims-side summary only — diagnosis_text is raw
    # medical text (invariant 4) and never becomes workflow output.
    return StepOutput(content={"line_items": [li.model_dump() for li in result.line_items], "bill_total": result.bill_total})


def medical_review(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    assert ctx.intake_result is not None
    step("medical", "active")
    emit("agent", "Medical reviewer assessing the diagnosis", "the ONLY agent allowed to see medical text (invariant 4) — every other agent receives its structured finding only")
    finding = run_medical_review(
        build_medical_reviewer_agent(),
        claim_id=ctx.claim_id,
        diagnosis_text=ctx.intake_result.diagnosis_text,
        admission_date=ctx.intake_result.admission_date,
        discharge_date=ctx.intake_result.discharge_date,
        length_of_stay_hours=ctx.intake_result.length_of_stay_hours,
        policy_start_date=ctx.policy.start_date.isoformat(),
    )
    if isinstance(finding, str):
        finding = MedicalFinding.model_validate_json(finding)
    ctx.finding = finding
    emit(
        "agent", f"Medical finding: ICD-10 {finding.icd10} · {finding.diagnosis_category}",
        f"confidence {finding.confidence:.0%} · stay justified={finding.stay_justified} · pre-existing={finding.pre_existing_suspected} · "
        f"excluded={finding.excluded_treatment} · day-care={finding.day_care_procedure}",
        level="success",
    )
    step("medical", "done", f"ICD-10 {finding.icd10} ({finding.diagnosis_category}), confidence {finding.confidence:.0%}", {
        "icd10": finding.icd10, "diagnosis_category": finding.diagnosis_category, "confidence": finding.confidence,
        "stay_justified": finding.stay_justified, "pre_existing_suspected": finding.pre_existing_suspected,
        "excluded_treatment": finding.excluded_treatment,
    })
    # The coded finding is exactly what downstream steps are allowed to see;
    # notes_for_officer is for humans only (schemas.py) and is left out.
    return StepOutput(content=finding.model_dump(exclude={"notes_for_officer"}))


def settlement(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    assert ctx.intake_result is not None and ctx.finding is not None
    step("settlement", "active")
    emit("rules", "Settlement computed in deterministic Python (not by the LLM)", f"plan {ctx.policy.plan} · sum insured ₹{ctx.policy.sum_insured:,} · every deduction must cite a policy clause")
    assessment = compute_settlement(
        claim_id=ctx.claim_id,
        claimed_amount=ctx.intake_result.bill_total,
        line_items=ctx.intake_result.line_items,
        admission_date_str=ctx.intake_result.admission_date,
        discharge_date_str=ctx.intake_result.discharge_date,
        finding=ctx.finding,
        policy=ctx.policy,
    )
    ctx.assessment = assessment
    for deduction in assessment.deductions:
        emit("rules", f"Deduction −₹{deduction.amount:,} · clause {deduction.clause_id}", deduction.reason)
    emit(
        "rules", f"Payable ₹{assessment.payable_amount:,} of ₹{assessment.claimed_amount:,} claimed",
        f"co-pay ₹{assessment.co_pay_amount:,} · recommended decision: {assessment.recommended_decision}"
        + (f" · flags: {', '.join(assessment.flags)}" if assessment.flags else ""),
        level="success",
    )
    step("settlement", "done", f"Payable ₹{assessment.payable_amount:,} of ₹{assessment.claimed_amount:,}", {
        "claimed_amount": assessment.claimed_amount, "payable_amount": assessment.payable_amount,
        "co_pay_amount": assessment.co_pay_amount, "deductions": [d.model_dump() for d in assessment.deductions],
        "flags": assessment.flags, "recommended_decision": assessment.recommended_decision,
    })
    return StepOutput(content=assessment.model_dump())


def coverage_explanation(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    assert ctx.assessment is not None
    step("coverage", "active")
    emit("agent", "Coverage agent writing a plain-language explanation", "Agno agent · narrates the settlement it was given; it cannot change the numbers")
    ctx.explanation = explain_assessment(build_coverage_agent(), ctx.assessment)
    step("coverage", "done", "Explanation written for the policyholder", {"explanation": ctx.explanation})
    return StepOutput(content=ctx.explanation)


def fraud_screen(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    step("fraud", "active")
    emit("agent", "Fraud agent screening on PSEUDONYMISED data", f"sees claim {ctx.claim_pseudo_id[:12]}… — never the real claim_id, names or account numbers")
    screen = run_fraud_screen(build_fraud_agent(), claim_id_pseudo=ctx.claim_pseudo_id, req_id=ctx.req_id)
    screen.claim_id = ctx.claim_id  # supervisor substitutes the real id back in — see fraud.py's docstring
    ctx.fraud_screen = screen
    if screen.flags:
        for flag in screen.flags:
            emit("agent", f"Fraud signal: {flag.type} ({flag.severity})", f"evidence {flag.evidence_ref}", level="warn")
    else:
        emit("agent", "Fraud screen clean — no duplicate bills, anomalies or watchlisted hospital", level="success")
    step("fraud", "done", f"{len(screen.flags)} fraud flag(s)" if screen.flags else "No fraud signals", {
        "flags": [f.model_dump() for f in screen.flags],
    })
    return StepOutput(content={"flags": [f.model_dump() for f in screen.flags]})


def tier_decision(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    assert ctx.assessment is not None and ctx.fraud_screen is not None
    step("tier", "active")
    ctx.tier = _tier(ctx.assessment, ctx.fraud_screen)
    reasons: list[str] = []
    if ctx.assessment.recommended_decision != "approve":
        reasons.append(f"coverage recommends '{ctx.assessment.recommended_decision}'")
    if ctx.fraud_screen.flags:
        reasons.append(f"{len(ctx.fraud_screen.flags)} fraud flag(s)")
    if ctx.assessment.payable_amount > PAYOUT_AUTO_LIMIT:
        reasons.append(f"payable ₹{ctx.assessment.payable_amount:,} > ₹{PAYOUT_AUTO_LIMIT:,} auto-pay ceiling")
    ctx.tier_reasons = reasons
    emit(
        "rules", f"Action tier {ctx.tier} decided",
        ("auto-pay allowed: payable ≤ ₹50,000, no flags, coverage approves" if ctx.tier == "T2" else "human decision required: " + "; ".join(reasons)),
        level="success" if ctx.tier == "T2" else "warn",
    )
    step("tier", "done", "T2 — safe to auto-pay" if ctx.tier == "T2" else "T3 — needs a human officer", {"tier": ctx.tier, "reasons": reasons})
    ctx.state = ClaimStateContext(
        claim_id=ctx.claim_id,
        current_state="assessing",
        completed_steps={"medical_review", "coverage_assessment", "fraud_screen"},
    )
    return StepOutput(content={"tier": ctx.tier, "reasons": reasons})


def is_auto_payable(step_input: StepInput) -> bool:
    """Condition evaluator: plain code, never an LLM, decides the money branch."""
    return _ctx(step_input).tier == "T2"


def _hand_to_officer(ctx: ClaimFlowContext) -> None:
    assert ctx.state is not None
    emit("agent", "Payout withheld — claim handed to the human officer queue", "agents may only recommend; money above the limits and every rejection need a human (invariant 6)", level="warn")
    transition(ctx.state, "pending_human", req_id=ctx.req_id, db=ctx.db)
    ctx.final_state = "pending_human"
    step("payout", "blocked", "Withheld — waiting for a claims officer", {"paid": False})


def governed_payout(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    assert ctx.assessment is not None and ctx.fraud_screen is not None and ctx.state is not None
    step("payout", "active")
    payout_ctx = PayoutContext(
        assessed_payable=ctx.assessment.payable_amount,
        registered_account_ref=ctx.registered_account_ref,
        remaining_sum_insured=ctx.remaining_sum_insured,
        fraud_flags=[flag.type for flag in ctx.fraud_screen.flags],
        already_paid=False,
    )
    try:
        # Attempt the real, governed payout call BEFORE committing the
        # auto_approved state transition — if PAY-*/DATA-* deny it for a
        # reason _tier's own (necessarily simpler) logic didn't anticipate,
        # the claim never enters auto_approved at all; it goes to a human
        # instead of getting stuck in an approved-but-unpaid state.
        ctx.payout_result = execute_payout(
            ctx.claim_id, amount=ctx.assessment.payable_amount,
            account_ref=ctx.registered_account_ref, req_id=ctx.req_id, ctx=payout_ctx,
        )
    except ToolCallDenied as denied:
        ctx.tier = "T3"  # governance itself disagreed with the T2 call — fail safe to human review
        emit("governance", "Payout refused by governance — falling back to human review", f"{denied.reason_code}: {denied.message}", level="deny")
        _hand_to_officer(ctx)
        return StepOutput(content={"paid": False, "denied_by": denied.reason_code})

    transition(ctx.state, "auto_approved", req_id=ctx.req_id, db=ctx.db)
    ctx.state.current_state = "auto_approved"
    transition(ctx.state, "paid", req_id=ctx.req_id, db=ctx.db)
    ctx.final_state = "paid"
    emit("payment", f"Mock payment of ₹{ctx.assessment.payable_amount:,} recorded to the registered account", "payments mock — no real money path (invariant 12)", level="success")
    step("payout", "done", f"₹{ctx.assessment.payable_amount:,} paid to the registered account", {"paid": True, "amount": ctx.assessment.payable_amount})
    return StepOutput(content={"paid": True, "amount": ctx.assessment.payable_amount})


def route_to_officer(step_input: StepInput) -> StepOutput:
    ctx = _ctx(step_input)
    step("payout", "active")
    _hand_to_officer(ctx)
    return StepOutput(content={"paid": False, "routed_to": "pending_human", "reasons": ctx.tier_reasons})


def build_claim_workflow() -> Workflow:
    """A fresh Workflow per claim run (no cross-claim state), built from the
    same definition AgentOS shows. Every step: max_retries=0 (see module
    docstring). telemetry=False: no usage metadata leaves this system."""

    def s(name: str, fn, description: str) -> Step:
        return Step(name=name, executor=_fail_closed(fn), description=description, max_retries=0)

    return Workflow(
        id=WORKFLOW_ID,
        name="Claim assessment",
        description="Deterministic, governed claim pipeline: 4 Agno agents + settlement, tiering and payout in code.",
        steps=[
            s("intake", intake, "Intake agent extracts bill items and facts from untrusted documents"),
            s("medical_review", medical_review, "Medical reviewer — the only step that sees medical text — returns a coded finding"),
            s("settlement", settlement, "Deterministic settlement against plan terms; each deduction cites a clause"),
            s("coverage_explanation", coverage_explanation, "Coverage agent explains the settlement in plain language"),
            s("fraud_screen", fraud_screen, "Fraud agent screens pseudonymised claims + hospital watchlist via the governed gateway"),
            s("tier_decision", tier_decision, "T2 (auto-pay) or T3 (human) — decided in code"),
            Condition(
                name="auto_pay_if_T2",
                description="Only T2 claims may be paid without a human",
                evaluator=is_auto_payable,
                steps=[s("governed_payout", governed_payout, "execute_payout through AGT PAY-001..006, token service and gateway")],
                else_steps=[s("route_to_officer", route_to_officer, "Governed transition to pending_human")],
            ),
        ],
        telemetry=False,
    )


def run_claim_flow(
    claim_id: str,
    bill_text: str,
    discharge_summary_text: str,
    policy: PolicyContext,
    claim_pseudo_id: str,
    registered_account_ref: str,
    remaining_sum_insured: int,
    db: Session | None = None,
) -> ClaimFlowResult:
    """Runs the claim-assessment Agno Workflow for one claim.

    `policy`, `claim_pseudo_id`, `registered_account_ref` and
    `remaining_sum_insured` are trusted values the caller assembled from
    Postgres (api/agentos.py) — see ClaimFlowContext. `db`, when given, makes
    every governed state transition also persist Claim.status.
    """
    req_id = new_req_id()
    ctx = ClaimFlowContext(
        claim_id=claim_id, bill_text=bill_text, discharge_summary_text=discharge_summary_text, policy=policy,
        claim_pseudo_id=claim_pseudo_id, registered_account_ref=registered_account_ref,
        remaining_sum_insured=remaining_sum_insured, req_id=req_id, db=db,
    )

    # One root span per claim flow carrying req_id/claim_id: every agent
    # call, governance decision and token/gateway call nests under it, so
    # one trace covers the claim end to end (docs/plan.md M6).
    with tracer.start_as_current_span("claim.flow") as flow_span:
        flow_span.set_attribute("req_id", req_id)
        flow_span.set_attribute("claim_id", claim_id)
        emit(
            "agent", "Agno Workflow 'claim-assessment' started",
            f"req_id={req_id} · intake → medical_review → settlement → coverage → fraud → tier → Condition(T2: payout | T3: officer) — order is code, not an LLM decision",
        )

        run = build_claim_workflow().run(input=f"assess claim {claim_id}", additional_data={"flow": ctx})

        if ctx.error or ctx.final_state is None:
            # A step failed and stopped the workflow: surface it instead of
            # returning a half-assessed claim.
            raise RuntimeError(f"claim-assessment workflow stopped for {claim_id}: {ctx.error or getattr(run, 'content', None)!r}")

        flow_span.set_attribute("tier", ctx.tier or "")
        flow_span.set_attribute("final_state", ctx.final_state)
        emit("agent", f"Agno Workflow completed — {ctx.final_state}", f"workflow run {getattr(run, 'run_id', '')} · status {getattr(run, 'status', '')}", level="success")

    assert ctx.intake_result and ctx.finding and ctx.assessment and ctx.fraud_screen and ctx.tier
    return ClaimFlowResult(
        claim_id=claim_id,
        intake_result=ctx.intake_result,
        finding=ctx.finding,
        assessment=ctx.assessment,
        explanation=ctx.explanation or "",
        fraud_screen=ctx.fraud_screen,
        tier=ctx.tier,
        final_state=ctx.final_state,
        payout_result=ctx.payout_result,
    )


__all__: list[Any] = ["ClaimFlowResult", "WORKFLOW_ID", "build_claim_workflow", "run_claim_flow"]
