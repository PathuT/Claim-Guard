"""Supervisor: routes a claim through the fixed agent sequence
docs/architecture.md §7 specifies (intake -> medical_reviewer -> coverage ->
fraud -> payout), and assembles the final decision.

Deliberately plain Python, not an Agno Team. Every real agno.team.TeamMode
(coordinate/route/broadcast/tasks — confirmed by reading agno/team/mode.py
directly, not guessed) has an LLM "leader" deciding which member runs and in
what order. That's the wrong tool for a flow the architecture doc specifies
as fixed, not something to be decided at runtime: "The LLM is an untrusted
decision-maker. Enforcement is deterministic code" (docs/architecture.md §2)
applies to *sequencing* here, the same way it applies to settlement math in
settlement.py. Each step below still calls a real Agno Agent making a real
LLM call — only the order they run in, and whether the next step runs at
all, is fixed code, not an LLM's choice.

M4 scope was intake -> medical_reviewer -> coverage only (docs/plan.md M4's
"Done when: S01 produces the correct ₹37,300 assessment, payout still
stubbed"). M5 completes the sequence: fraud screens on pseudonymised data,
the tier (T0-T3, docs/use-case.md §6) decides auto-approve vs. pending_human,
the claim state machine (api/state_machine.py) records that transition as a
real governed `set_claim_state` call, and — only for an auto-approved
T2-or-below claim — payout actually moves money through the same governed
chain fraud/payout already proved out independently.

Fraud and payout are the two steps that go through the real
governance/token/gateway chain (governance/client.py), not plain function
arguments — see agents/fraud.py and agents/payout.py's own module
docstrings for why. Everything upstream (intake/medical_reviewer/coverage)
keeps M4's plain-argument pattern; wiring them onto the real chain too is
future work, not required for M5's own "done when" (S01 pays automatically;
S02/S03 stop at pending_human; S06 is never paid) — none of those three
outcomes depend on intake/medical_reviewer/coverage's own tool calls being
real, only on fraud's screening and payout's PAY-rule enforcement being real.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opentelemetry import trace

from api.state_machine import ClaimStateContext, transition
from governance.client import ToolCallDenied, new_req_id

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
    """The fixed sequence: intake extracts -> medical_reviewer assesses the
    medical facts -> settlement.py computes the payable amount
    deterministically -> coverage narrates the result -> fraud screens on
    pseudonymised data -> tier decides auto vs. human -> state machine
    records the transition -> (T2 only) payout actually pays.

    `claim_pseudo_id`: this claim's own claim_pseudo_id, precomputed by the
    caller the same way fraud.py's docstring describes (from
    data_gateway.pseudonymise.pseudonymise(claim_id, salt="claim_id") —
    supervisor is allowed to compute this because it's deterministic and
    keyless-reversible only with the gateway's own key, so knowing a
    person's pseudonym still tells the supervisor nothing new it didn't
    already have as the one component holding the real claim_id).
    `registered_account_ref` / `remaining_sum_insured`: trusted values the
    caller assembled from Postgres for the payout step, mirroring how
    `policy` is assembled for settlement.py.
    `db`: optional session, passed straight through to every transition()
    call so the claim's `status` column is actually persisted in Postgres,
    not just governed/audited — see api/state_machine.transition()'s own
    docstring for why this is a separate parameter rather than always-on
    (existing callers, e.g. every M4/M5 manual test, keep working exactly
    as before with db=None).

    Each agent is built fresh per call (matches intake.py/medical_reviewer.py/
    coverage.py/fraud.py's own build_*_agent() pattern) rather than shared
    across calls, since Agno agents are cheap to construct and this avoids
    any cross-claim state leaking between runs.
    """
    req_id = new_req_id()

    # M6: one root span per claim flow, carrying req_id/claim_id — every
    # Agno agent call (auto-instrumented) and every governance/token/gateway
    # call this function makes (governance/client.py injects a traceparent
    # from whatever span is active) nests under this one, so a single
    # trace_id covers the whole claim end to end (docs/plan.md M6: "one
    # trace per req_id across all services"). Without this, each of the
    # calls below started its own independent root span/trace.
    with tracer.start_as_current_span("claim.flow") as flow_span:
        flow_span.set_attribute("req_id", req_id)
        flow_span.set_attribute("claim_id", claim_id)

        intake_agent = build_intake_agent()
        intake_result = run_intake(intake_agent, claim_id, bill_text, discharge_summary_text)

        medical_reviewer_agent = build_medical_reviewer_agent()
        finding = run_medical_review(
            medical_reviewer_agent,
            claim_id=claim_id,
            diagnosis_text=intake_result.diagnosis_text,
            admission_date=intake_result.admission_date,
            discharge_date=intake_result.discharge_date,
            length_of_stay_hours=intake_result.length_of_stay_hours,
            policy_start_date=policy.start_date.isoformat(),
        )

        assessment = compute_settlement(
            claim_id=claim_id,
            claimed_amount=intake_result.bill_total,
            line_items=intake_result.line_items,
            admission_date_str=intake_result.admission_date,
            discharge_date_str=intake_result.discharge_date,
            finding=finding,
            policy=policy,
        )

        coverage_agent = build_coverage_agent()
        explanation = explain_assessment(coverage_agent, assessment)

        fraud_agent = build_fraud_agent()
        fraud_screen = run_fraud_screen(fraud_agent, claim_id_pseudo=claim_pseudo_id, req_id=req_id)
        fraud_screen.claim_id = claim_id  # supervisor substitutes the real id back in — see fraud.py's docstring

        tier = _tier(assessment, fraud_screen)

        state_ctx = ClaimStateContext(
            claim_id=claim_id,
            current_state="assessing",
            completed_steps={"medical_review", "coverage_assessment", "fraud_screen"},
        )

        payout_result: dict | None = None
        if tier == "T2":
            payout_ctx = PayoutContext(
                assessed_payable=assessment.payable_amount,
                registered_account_ref=registered_account_ref,
                remaining_sum_insured=remaining_sum_insured,
                fraud_flags=[flag.type for flag in fraud_screen.flags],
                already_paid=False,
            )
            try:
                # Attempt the real, governed payout call BEFORE committing the
                # auto_approved state transition — if PAY-*/DATA-* deny it for
                # a reason _tier's own (necessarily simpler) logic didn't
                # anticipate, the claim never enters auto_approved at all; it
                # falls through to the pending_human branch below instead of
                # getting stuck in an approved-but-unpaid state.
                payout_result = execute_payout(
                    claim_id, amount=assessment.payable_amount,
                    account_ref=registered_account_ref, req_id=req_id, ctx=payout_ctx,
                )
            except ToolCallDenied:
                tier = "T3"  # governance itself disagreed with _tier's T2 call — fail safe to human review
            else:
                transition(state_ctx, "auto_approved", req_id=req_id, db=db)
                state_ctx.current_state = "auto_approved"
                transition(state_ctx, "paid", req_id=req_id, db=db)
                final_state = "paid"

        if tier == "T3":
            transition(state_ctx, "pending_human", req_id=req_id, db=db)
            final_state = "pending_human"

        flow_span.set_attribute("tier", tier)
        flow_span.set_attribute("final_state", final_state)

        return ClaimFlowResult(
            claim_id=claim_id,
            intake_result=intake_result,
            finding=finding,
            assessment=assessment,
            explanation=explanation,
            fraud_screen=fraud_screen,
            tier=tier,
            final_state=final_state,
            payout_result=payout_result,
        )
