"""PAY-*, STATE-*, DATA-* rule implementations from docs/security-matrix.md §8.

Each rule is a function `(ToolCallContext) -> RuleResult` that:
  - returns allowed=True immediately if it doesn't apply to this tool call
    (e.g. PAY-001 only ever fires for execute_payout)
  - otherwise checks the agent's *requested* args against `ctx.trusted`
    values — never trusts args alone, per the adapter's core invariant.

GOV-001/002/003 live in adapter.py/tool_allowlist.py/auth.matrix.py instead,
since they're about tool/scope allowlists, not payout/state/data logic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


ALL_RULES: list[Callable[[ToolCallContext], RuleResult]] = [
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
