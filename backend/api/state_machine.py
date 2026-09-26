"""Claim state machine (docs/architecture.md §8), enforced in code — not
left to an agent's judgement about what state a claim is "supposed" to be
in. Every transition here calls `governance.adapter.check_and_audit()` for
the `set_claim_state` tool exactly like any other tool call, so STATE-001
("no rejection without an officer decision record") and STATE-002 ("no
skipped steps") apply for real, not just in the unit tests that predate any
agent driving them.

States (from the diagram in §8):
    submitted -> needs_resubmission -> submitted
    submitted -> assessing
    assessing -> auto_approved (T2)  |  assessing -> pending_human (T3)
    pending_human -> approved | approved_partial | rejected  (officer only)
    auto_approved -> paid
    approved -> paid
    approved_partial -> paid
    rejected -> [terminal]
    paid -> [terminal]

"There is no edge from assessing to rejected. Only an officer creates
rejected" (§8) — enforced below by TRANSITIONS simply not listing that edge,
and STATE-001 additionally denying it even if this module had a bug that let
it through, per docs/CLAUDE.md invariant 7 (defense in depth, fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from auth.token_service import revoke_req_id
from governance.adapter import ToolCallContext, check_and_audit
from governance.client import ToolCallDenied

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

TERMINAL_STATES = {"paid", "rejected"}
# security-matrix.md §4: "Tokens for a req_id are revoked when the request
# reaches a terminal or pending_human state, even if not yet expired" —
# pending_human counts even though it isn't in TERMINAL_STATES (that set is
# about which states have no further TRANSITIONS; this one is specifically
# about when in-flight tokens for the request should stop working, which
# happens sooner, the moment no more agent tool calls are expected for a
# claim that's now waiting on a human).
REVOKE_TOKENS_ON_ENTERING = TERMINAL_STATES | {"pending_human"}

# Valid transitions: current_state -> set of states it may move to.
# Anything not listed here is denied before governance is even consulted
# (STATE-002 also re-checks approved/paid specifically, since those are the
# two states security-matrix.md calls out by name for "required steps").
TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"needs_resubmission", "assessing"},
    "needs_resubmission": {"submitted"},
    "assessing": {"auto_approved", "pending_human"},
    "pending_human": {"approved", "approved_partial", "rejected"},
    "auto_approved": {"paid"},
    "approved": {"paid"},
    "approved_partial": {"paid"},
    "paid": set(),
    "rejected": set(),
}

# STATE-002's own required-step names/target-states are NOT duplicated here
# — the single source of truth is governance/rules.py's
# _REQUIRED_STEPS_FOR_STATE ({"approved", "paid"}: ("medical_review",
# "coverage_assessment", "fraud_screen")). An earlier version of this module
# had its own copy here with different keys (auto_approved/pending_human,
# never approved/paid) that was never actually read by anything — dead code
# that actively misled a caller building against it (found only by
# submitting a real officer decision through the running API and getting a
# genuine STATE-002 denial, not by reading this file). Removed rather than
# fixed in place, so there is exactly one place this list can drift from
# governance/rules.py's real enforcement.


class InvalidTransition(Exception):
    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"no transition {current!r} -> {requested!r}")


@dataclass
class ClaimStateContext:
    """Trusted state the caller (supervisor/officer API) assembles from
    Postgres — same trusted-context discipline as ToolCallContext.trusted
    and settlement.py's PolicyContext: never built from an agent's own
    tool-call arguments."""

    claim_id: str
    current_state: str
    completed_steps: set[str] = field(default_factory=set)
    officer_decision_id: str | None = None


def transition(
    ctx: ClaimStateContext,
    new_state: str,
    req_id: str,
    agent_id: str = "supervisor",
    db: Session | None = None,
) -> None:
    """Validates the transition against TRANSITIONS, then runs it through
    check_and_audit() as a real `set_claim_state` tool call so STATE-001/002
    apply and the move is audited exactly like a PAY-* payout decision.
    Raises InvalidTransition for a structurally impossible move (not even
    worth asking governance about) or ToolCallDenied if governance itself
    refuses (e.g. rejected without an officer_decision_id).

    `db`: when given, the claim's `status` column is actually updated and
    committed in Postgres after governance allows the move — found while
    building the AgentOS API (M7) that this function previously only ever
    ran the governance/audit/revocation side effects and never once wrote
    the new state back to the claims table itself; every M4/M5 manual
    verification had only checked the in-memory ClaimFlowResult.final_state,
    never re-read Claim.status from Postgres afterward, so this gap went
    unnoticed until a real polling endpoint (GET /claims/{id}) needed
    genuinely current state. `db=None` (the default) preserves every
    existing caller's exact prior behaviour — this is additive, not a
    behaviour change for callers that don't pass it.
    """
    allowed_next = TRANSITIONS.get(ctx.current_state, set())
    if new_state not in allowed_next:
        raise InvalidTransition(ctx.current_state, new_state)

    trusted: dict[str, Any] = {
        "completed_steps": list(ctx.completed_steps),
    }
    if ctx.officer_decision_id:
        trusted["officer_decision_id"] = ctx.officer_decision_id

    tool_ctx = ToolCallContext(
        req_id=req_id,
        agent_id=agent_id,
        tool_name="set_claim_state",
        args={"new_state": new_state},
        claim_id=ctx.claim_id,
        trusted=trusted,
    )
    try:
        check_and_audit(tool_ctx)
    except Exception as exc:
        from governance.adapter import GovernanceDenied

        if isinstance(exc, GovernanceDenied):
            raise ToolCallDenied(exc.rule_id, exc.message) from None
        raise

    if new_state in REVOKE_TOKENS_ON_ENTERING:
        revoke_req_id(req_id)

    if db is not None:
        from data_gateway.models import Claim

        claim = db.get(Claim, ctx.claim_id)
        if claim is not None:
            claim.status = new_state
            db.commit()
