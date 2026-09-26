"""Payout: issues payment after approval (docs/security-matrix.md §2:
bank_details:read own claim's policyholder only, payments:write).

Deliberately plain Python, not an Agno agent — same reasoning as
settlement.py and supervisor.py: "The LLM is an untrusted decision-maker.
Enforcement is deterministic code" (docs/architecture.md §2) applies most of
all here, since this is the one action that moves money. There is nothing
for an LLM to judge or narrate; the amount and account are already decided
(by settlement.py and the policyholder's own bank_details row), and the only
question — "is this specific payout allowed right now" — is exactly what
PAY-001..006 in governance/rules.py exist to answer deterministically.

This is also the module docs/use-case.md §8's S06 scenario exercises for
real: even if some earlier step were fooled by injected text into believing
"pay ₹4,50,000 to account 9988776655", execute_payout's call still goes
through check_and_audit() with `trusted` values pulled from Postgres
(assessed_payable, registered_account_ref) — never from the args a
compromised caller supplies — so PAY-001 (amount) and PAY-002 (account)
deny it regardless of what any agent upstream believed.
"""

from __future__ import annotations

from dataclasses import dataclass

from governance.client import ToolCallDenied, ToolCallRequest, call_tool


class PayoutDenied(ToolCallDenied):
    """Re-exported alias so callers importing agents.payout don't also need
    governance.client — same denial shape (reason_code, message)."""


@dataclass
class PayoutContext:
    """Trusted values the caller (supervisor) assembles from Postgres
    before calling execute_payout — never from an agent's own claim about
    what the payable amount or account should be. Mirrors
    settlement.PolicyContext / governance.adapter.ToolCallContext.trusted's
    same discipline."""

    assessed_payable: int
    registered_account_ref: str
    remaining_sum_insured: int
    fraud_flags: list[str]
    already_paid: bool
    officer_approval_id: str | None = None


def read_registered_account(claim_id: str, req_id: str) -> str:
    """bank_details:read, row-bound (by policy_number, resolved from the
    token's own claim_id) to this claim's policyholder only — data_gateway/
    app.py's bank_details row-binding fix ensures this can never return
    another policyholder's account, even if payout asked for a different
    claim_id in its args."""
    result = call_tool(ToolCallRequest(
        req_id=req_id, agent_id="payout", tool_name="read_bank_details",
        scope="bank_details:read", claim_id=claim_id, args={},
    ))
    rows = result["rows"]
    if not rows:
        raise PayoutDenied("PAYOUT-NO-BANK-DETAILS", f"no bank_details row for claim {claim_id!r}")
    return rows[0]["account_number"]


def execute_payout(
    claim_id: str,
    amount: int,
    account_ref: str,
    req_id: str,
    ctx: PayoutContext,
) -> dict:
    """The one real money-moving call. `amount`/`account_ref` are what's
    being *requested* (potentially by a compromised or confused upstream
    step — see module docstring's S06 note); `ctx` is trusted ground truth
    the governance rules check the request against, never the reverse.
    Returns the gateway's write confirmation on success; raises
    ToolCallDenied (PAY-001..006) on any policy failure."""
    return call_tool(ToolCallRequest(
        req_id=req_id, agent_id="payout", tool_name="execute_payout",
        scope="payments:write", claim_id=claim_id,
        args={"amount": amount, "account_ref": account_ref},
        trusted={
            "assessed_payable": ctx.assessed_payable,
            "registered_account_ref": ctx.registered_account_ref,
            "remaining_sum_insured": ctx.remaining_sum_insured,
            "fraud_flags": ctx.fraud_flags,
            "already_paid": ctx.already_paid,
            "officer_approval_id": ctx.officer_approval_id,
            # DATA-002 (governance/rules.py): account_ref in the tool call's
            # args must be one of this claim's actually-known bank accounts
            # from bank_details, not merely equal to registered_account_ref
            # by coincidence — populated from the same trusted source as
            # registered_account_ref itself.
            "known_bank_accounts": {ctx.registered_account_ref},
        },
    ))
