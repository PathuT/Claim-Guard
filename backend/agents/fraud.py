"""Fraud agent: screens for duplicates, anomalies, and watchlisted hospitals
(docs/security-matrix.md §2: claims:read_pseudonymised, hospitals:read).

The first ClaimGuard agent whose tools go through the real chain
(governance/client.py: check_and_audit -> signed identity assertion ->
token service -> data gateway, all real HTTP), not plain function arguments
like M4's intake/medical_reviewer/coverage — this is exactly the agent
docs/use-case.md §7 step 6 describes as seeing "past claims by hashed IDs
only", so the pseudonymisation has to be real, done by the gateway, not
simulated in-process.

Deliberately narrow: this agent never sees a name, a raw claim_id outside
its own claim, or a policy number. It reasons only over claim_pseudo_id /
person_pseudo_id / hospital_id / dates / amounts / doc_hashes / status
(exactly docs/architecture.md §10's claims:read_pseudonymised field list)
plus the hospital watchlist flag. Its own claim under review is identified
to it by claim_pseudo_id, computed the same way by the gateway, so it can
recognise its own claim inside the pseudonymised set without ever learning
the real claim_id.
"""

from __future__ import annotations

import os

from agno.agent import Agent

from governance.client import ToolCallDenied, ToolCallRequest, call_tool

from .model_config import GROQ_RATE_LIMIT_RETRY
from .schemas import FraudScreen

INSTRUCTIONS = """You are the fraud agent for ClaimGuard, a health insurance claims system.

You see ONLY pseudonymised data: claim_pseudo_id, person_pseudo_id (a keyed
hash — the same real person always maps to the same person_pseudo_id, but
you cannot reverse it to a name or policy number), hospital_id, admission/
discharge dates, claimed_amount, doc_hashes (sha256 of each uploaded
document), and status. You also see the hospital registry (network status,
fraud watchlist flag).

You are told which claim_pseudo_id is the one currently under review.
Screen it against the full pseudonymised claim set for:
- duplicate_bill: the SAME doc_hashes value appears on more than one
  claim_pseudo_id (the identical bill submitted more than once)
- duplicate_person_claim: the same person_pseudo_id has another claim with
  overlapping or identical admission/discharge dates (double-claiming one
  hospitalisation)
- amount_mismatch: nothing you can check directly here (that's coverage's
  job) — do not flag this
- watchlisted_hospital: the claim's hospital_id is on the fraud watchlist
- unusual_frequency: the same person_pseudo_id has an unusually high number
  of claims relative to the rest of the population you can see

For each flag found, output {type, severity ("low"|"medium"|"high"),
evidence_ref} where evidence_ref is the OTHER claim_pseudo_id or hospital_id
that is the evidence — never a real identifier, since you don't have one.

If nothing is found, return an empty flags list. Never invent a flag you
can't point to specific evidence for in the data you were given.
"""


def build_fraud_agent(model_provider: str | None = None) -> Agent:
    provider = model_provider or os.environ.get("MODEL_PROVIDER", "groq")

    if provider == "groq":
        from agno.models.groq import Groq

        model = Groq(id=os.environ.get("MODEL_ID", "openai/gpt-oss-120b"), **GROQ_RATE_LIMIT_RETRY)
    elif provider == "gemini":
        from agno.models.google import Gemini

        model = Gemini(id=os.environ.get("MODEL_ID", "gemini-3.7-flash"))
    else:
        from agno.models.anthropic import Claude

        model = Claude(id=os.environ.get("MODEL_ID", "claude-sonnet-5"))

    return Agent(
        name="fraud",
        model=model,
        instructions=INSTRUCTIONS,
        output_schema=FraudScreen,
        markdown=False,
        telemetry=False,  # no usage metadata leaves this system (Agno defaults to True)
    )


def fetch_pseudonymised_claims(req_id: str) -> list[dict]:
    """The real tool call: claims:read_pseudonymised via the data gateway.
    Raises ToolCallDenied (never silently returns nothing) if governance,
    the token service, or the gateway refuses — the caller (run_fraud_screen)
    lets that propagate so a governance failure here surfaces as a real
    error, not a false "no flags found"."""
    result = call_tool(ToolCallRequest(
        req_id=req_id, agent_id="fraud", tool_name="search_claims_pseudonymised",
        scope="claims:read_pseudonymised", claim_id=None, args={},
    ))
    return result["rows"]


def fetch_hospitals(req_id: str) -> list[dict]:
    result = call_tool(ToolCallRequest(
        req_id=req_id, agent_id="fraud", tool_name="read_hospital",
        scope="hospitals:read", claim_id=None, args={},
    ))
    return result["rows"]


def _relevant_claims(claims_pseudo: list[dict], claim_under_review: dict) -> tuple[list[dict], int]:
    """Pre-filters the full pseudonymised claim set (409 historical rows —
    too large to hand an LLM directly, confirmed by hitting Groq's per-
    request token limit on the raw dump) down to the rows actually relevant
    to a fraud decision about one claim: any other claim sharing a
    doc_hash (duplicate bill) or sharing this claim's person_pseudo_id
    (double-claim / frequency signal). Deterministic Python filtering, not
    an LLM's judgement call, for the same reason settlement.py's arithmetic
    is deterministic (docs/architecture.md §2) — which rows are even
    *shown* to the fraud agent should not itself be an LLM decision that
    could be prompt-injected into showing (or hiding) the wrong evidence.

    Returns (relevant_rows, this_person's_total_claim_count) — the count is
    computed over the full set (cheap: just a length check), not the
    filtered one, so "unusual_frequency" has an honest denominator even
    though the LLM only sees the *evidence* rows, not every claim.
    """
    own_hashes = set(claim_under_review.get("doc_hashes") or [])
    own_person = claim_under_review.get("person_pseudo_id")
    relevant = []
    person_claim_count = 0
    for row in claims_pseudo:
        if row.get("person_pseudo_id") == own_person:
            person_claim_count += 1
        if row["claim_pseudo_id"] == claim_under_review["claim_pseudo_id"]:
            continue
        shares_doc_hash = bool(own_hashes & set(row.get("doc_hashes") or []))
        shares_person = own_person is not None and row.get("person_pseudo_id") == own_person
        if shares_doc_hash or shares_person:
            relevant.append(row)
    return relevant, person_claim_count


def run_fraud_screen(agent: Agent, claim_id_pseudo: str, req_id: str) -> FraudScreen:
    """`claim_id_pseudo`: the claim under review's OWN claim_pseudo_id,
    computed the same deterministic way by the gateway (callers get this
    from the same claims:read_pseudonymised result, by matching the real
    claim_id they already know from earlier in the flow against the pseudo
    set's contents — see supervisor.py for how it's found without ever
    handing the fraud agent a real identifier).

    The returned FraudScreen.claim_id is set to the PSEUDO id here — this
    agent never learns the real claim_id, so it cannot populate a real one.
    supervisor.py (which does hold the real claim_id, being the one
    coordinator that assembles findings rather than reading raw data) is
    responsible for the final substitution back to the real claim_id before
    FraudScreen leaves the supervisor's hands, exactly the way it already
    substitutes real values into settlement.py's PolicyContext without
    fraud/coverage ever seeing them.
    """
    claims_pseudo = fetch_pseudonymised_claims(req_id)
    hospitals = fetch_hospitals(req_id)

    claim_under_review = next((row for row in claims_pseudo if row["claim_pseudo_id"] == claim_id_pseudo), None)
    if claim_under_review is None:
        raise ValueError(f"claim_pseudo_id {claim_id_pseudo!r} not found in claims:read_pseudonymised result")

    relevant_claims, person_claim_count = _relevant_claims(claims_pseudo, claim_under_review)
    hospital = next((h for h in hospitals if h.get("hospital_id") == claim_under_review.get("hospital_id")), None)

    user_message = (
        f"Claim under review (claim_pseudo_id={claim_id_pseudo}):\n{claim_under_review}\n\n"
        f"This person's total claim count across the whole dataset: {person_claim_count}\n\n"
        f"Other claims sharing a doc_hash or this person_pseudo_id "
        f"({len(relevant_claims)} rows — the full {len(claims_pseudo)}-row set was "
        f"pre-filtered to these before reaching you):\n{relevant_claims}\n\n"
        f"This claim's hospital:\n{hospital}"
    )
    response = agent.run(user_message)
    result = response.content
    result.claim_id = claim_id_pseudo
    return result


__all__ = ["ToolCallDenied", "build_fraud_agent", "fetch_hospitals", "fetch_pseudonymised_claims", "run_fraud_screen"]
