"""PAY-*, STATE-*, DATA-* rule implementations from docs/security-matrix.md §8.

Each rule is a function `(ToolCallContext) -> RuleResult` that:
  - returns allowed=True immediately if it doesn't apply to this tool call
    (e.g. PAY-001 only ever fires for execute_payout)
  - otherwise checks the agent's *requested* args against `ctx.trusted`
    values — never trusts args alone, per the adapter's core invariant.

GOV-001/002/003 live in adapter.py/tool_allowlist.py/auth.matrix.py instead,
since they're about tool/scope allowlists, not payout/state/data logic.
GOV-004 (the compliance kill switch on automated payouts, ADR-012) lives here
because, like the PAY rules, it is a check of an execute_payout call against a
trusted value — the freeze state check_and_audit() reads from
governance/controls.py, never from the caller.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .controls import PayoutFreezeState

if TYPE_CHECKING:
    from .adapter import ToolCallContext

PAYOUT_AUTO_LIMIT = 50_000  # security-matrix.md §6 (action tiers), T2 ceiling


@dataclass
class RuleResult:
    rule_id: str
    allowed: bool
    reason: str = ""


def _ok(rule_id: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, allowed=True)


def _deny(rule_id: str, reason: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, allowed=False, reason=reason)


# --- GOV-004: compliance kill switch — automated payouts frozen ---
def gov_004_automated_payouts_frozen(ctx: ToolCallContext) -> RuleResult:
    """Denies an AUTOMATED execute_payout while compliance has frozen
    automated payouts. An officer-approved payout (officer_approval_id in
    trusted context, supplied only by api/officer.py) is a human decision
    and still goes through — the switch stops agents moving money on their
    own, it does not take the humans out of the loop.

    `ctx.trusted["payout_freeze"]` is populated by check_and_audit() from
    governance/controls.py, overwriting anything a caller put there. Anything
    other than a PayoutFreezeState (absent, a bare bool, a dict) means the
    trusted store was not consulted -> deny (invariant 7)."""
    if ctx.tool_name != "execute_payout":
        return _ok("GOV-004")
    freeze = ctx.trusted.get("payout_freeze")
    if not isinstance(freeze, PayoutFreezeState):
        return _deny("GOV-004", "payout freeze state was not read from the trusted governance controls store (fail closed)")
    if not freeze.frozen or ctx.trusted.get("officer_approval_id"):
        return _ok("GOV-004")
    who = f" by {freeze.set_by}" if freeze.set_by else ""
    when = f" at {freeze.set_at}" if freeze.set_at else ""
    return _deny(
        "GOV-004",
        f"automated payouts are frozen by compliance{who}{when} — reason: {freeze.reason or 'none recorded'}; "
        "only an officer-approved payout may proceed",
    )


# --- PAY-001: payout amount must equal the assessed payable ---
def pay_001_amount_matches_assessment(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "execute_payout":
        return _ok("PAY-001")
    requested_amount = ctx.args.get("amount")
    assessed_payable = ctx.trusted.get("assessed_payable")
    if assessed_payable is None:
        return _deny("PAY-001", "no assessed_payable on record for this claim (fail closed)")
    if requested_amount != assessed_payable:
        return _deny("PAY-001", f"requested amount {requested_amount!r} != assessed payable {assessed_payable!r}")
    return _ok("PAY-001")


# --- PAY-002: payout account must equal the policy's registered account ---
def pay_002_account_matches_registered(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "execute_payout":
        return _ok("PAY-002")
    requested_account = ctx.args.get("account_ref")
    registered_account = ctx.trusted.get("registered_account_ref")
    if registered_account is None:
        return _deny("PAY-002", "no registered account on record for this claim's policy (fail closed)")
    if requested_account != registered_account:
        return _deny("PAY-002", f"requested account {requested_account!r} != registered account {registered_account!r}")
    return _ok("PAY-002")


# --- PAY-003: payout > 50,000 requires an officer approval record ---
def pay_003_high_value_requires_approval(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "execute_payout":
        return _ok("PAY-003")
    amount = ctx.args.get("amount")
    if amount is None or amount <= PAYOUT_AUTO_LIMIT:
        return _ok("PAY-003")
    if not ctx.trusted.get("officer_approval_id"):
        return _deny("PAY-003", f"payout {amount} > ₹{PAYOUT_AUTO_LIMIT} requires an officer approval record")
    return _ok("PAY-003")


# --- PAY-004: any fraud flag requires an officer approval record ---
def pay_004_fraud_flag_requires_approval(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "execute_payout":
        return _ok("PAY-004")
    if ctx.trusted.get("fraud_flags") and not ctx.trusted.get("officer_approval_id"):
        return _deny("PAY-004", f"claim has fraud flags {ctx.trusted['fraud_flags']!r} and no officer approval record")
    return _ok("PAY-004")


# --- PAY-005: no second payout for the same claim ---
def pay_005_no_duplicate_payout(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "execute_payout":
        return _ok("PAY-005")
    if ctx.trusted.get("already_paid"):
        return _deny("PAY-005", f"claim {ctx.claim_id!r} has already been paid")
    return _ok("PAY-005")


# --- PAY-006: payout must not exceed remaining sum insured ---
def pay_006_within_remaining_sum_insured(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "execute_payout":
        return _ok("PAY-006")
    amount = ctx.args.get("amount")
    remaining = ctx.trusted.get("remaining_sum_insured")
    if remaining is None:
        return _deny("PAY-006", "no remaining_sum_insured on record for this policy (fail closed)")
    if amount is not None and amount > remaining:
        return _deny("PAY-006", f"payout {amount} exceeds remaining sum insured {remaining}")
    return _ok("PAY-006")


# --- STATE-001: no transition to rejected without an officer decision record ---
def state_001_rejection_requires_officer_decision(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "set_claim_state" or ctx.args.get("new_state") != "rejected":
        return _ok("STATE-001")
    if not ctx.trusted.get("officer_decision_id"):
        return _deny("STATE-001", "transition to 'rejected' requires an officer decision record")
    return _ok("STATE-001")


# --- STATE-002: no transition to approved/paid skipping required steps ---
_REQUIRED_STEPS_FOR_STATE: dict[str, tuple[str, ...]] = {
    "approved": ("medical_review", "coverage_assessment", "fraud_screen"),
    "paid": ("medical_review", "coverage_assessment", "fraud_screen"),
}


def state_002_no_skipped_steps(ctx: ToolCallContext) -> RuleResult:
    if ctx.tool_name != "set_claim_state":
        return _ok("STATE-002")
    new_state = ctx.args.get("new_state")
    required = _REQUIRED_STEPS_FOR_STATE.get(new_state)
    if required is None:
        return _ok("STATE-002")
    completed = set(ctx.trusted.get("completed_steps", []))
    missing = [step for step in required if step not in completed]
    if missing:
        return _deny("STATE-002", f"transition to {new_state!r} skips required steps: {missing}")
    return _ok("STATE-002")


# --- DATA-001: medical_records:* only for intake(write)/medical_reviewer(read) ---
def data_001_medical_records_restricted(ctx: ToolCallContext) -> RuleResult:
    requested_scope = ctx.args.get("scope", "")
    if not requested_scope.startswith("medical_records:"):
        return _ok("DATA-001")
    allowed = (ctx.agent_id == "intake" and requested_scope == "medical_records:write") or (
        ctx.agent_id == "medical_reviewer" and requested_scope == "medical_records:read"
    )
    if not allowed:
        return _deny("DATA-001", f"{ctx.agent_id!r} may not request {requested_scope!r}")
    return _ok("DATA-001")


# --- DATA-002: tool args must not contain an account number not from bank_details ---
def data_002_account_number_must_be_trusted(ctx: ToolCallContext) -> RuleResult:
    account_in_args = ctx.args.get("account_ref") or ctx.args.get("account_number")
    if account_in_args is None:
        return _ok("DATA-002")
    known_accounts = ctx.trusted.get("known_bank_accounts", set())
    if account_in_args not in known_accounts:
        return _deny("DATA-002", f"account {account_in_args!r} is not a known bank_details account for this claim")
    return _ok("DATA-002")


# GOV-004 first: while the kill switch is on, a frozen automated payout is
# reported as GOV-004 (the emergency stop) regardless of which PAY rule would
# also have refused it — one unambiguous reason for the audit log and the
# Live Run view.
ALL_RULES: list[Callable[[ToolCallContext], RuleResult]] = [
    gov_004_automated_payouts_frozen,
    pay_001_amount_matches_assessment,
    pay_002_account_matches_registered,
    pay_003_high_value_requires_approval,
    pay_004_fraud_flag_requires_approval,
    pay_005_no_duplicate_payout,
    pay_006_within_remaining_sum_insured,
    state_001_rejection_requires_officer_decision,
    state_002_no_skipped_steps,
    data_001_medical_records_restricted,
    data_002_account_number_must_be_trusted,
]


def run_all_rules(ctx: ToolCallContext) -> list[RuleResult]:
    """Runs every rule, always in full (not short-circuiting on the first
    deny) so a caller/test can see every applicable result — adapter.py's
    check_and_audit() is the one that stops at the first denial."""
    return [rule(ctx) for rule in ALL_RULES]
