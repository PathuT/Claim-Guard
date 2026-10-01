"""Shared, trusted claim-context helpers used by more than one API module
(api/agentos.py's own submission flow, api/officer.py's review/decision
flow). Pulled out here rather than duplicated across both — found while
building M8's officer review endpoint, which needs the exact same
remaining_sum_insured computation api/agentos.py's submit_claim already had
as a private helper.

Both callers are trusted assemblers (docs/engineering-guide.md invariant 7): these
values are computed here from Postgres directly, never accepted as
arguments from an untrusted caller (the Console's officer view included —
see api/officer.py's own /claims/{id}/review endpoint for why the officer
decision's registered_account_ref/remaining_sum_insured are looked up
server-side, not trusted from the browser's own request body).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from data_gateway.models import Claim, Payment


def remaining_sum_insured(db: Session, policy_number: str, sum_insured: int) -> int:
    """sum_insured minus every prior payout against this policy (docs/use-
    case.md's plan terms are silent on multi-claim-per-year proration
    beyond "sum insured" being the annual cap — treated here as: every paid
    claim under this policy this run has seen so far counts against it, the
    simplest reading consistent with PAY-006's own name). Computed fresh per
    call rather than cached, since a Harbor run (or the officer console)
    submits/reviews multiple scenarios against the same two policyholders
    (Priya/Rahul) in sequence and each one's remaining balance depends on
    what already paid before it.
    """
    paid_claim_ids = db.execute(
        select(Claim.claim_id).where(Claim.policy_number == policy_number)
    ).scalars().all()
    if not paid_claim_ids:
        return sum_insured
    prior_payouts = db.execute(
        select(Payment.amount).where(Payment.claim_id.in_(paid_claim_ids))
    ).scalars().all()
    return sum_insured - sum(prior_payouts)
