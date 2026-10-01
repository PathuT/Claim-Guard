# ADR-014: Officer claim assistant — an agent with governed, read-only tools

- **Status:** accepted
- **Date:** 2026-09-28

## Context
A claims officer deciding a T3 claim reads the settlement, deductions with clause ids,
fraud signals and the medical reviewer's structured finding on the Officer page. Officers
wanted a faster way to get answers such as "why is this with me instead of auto-paid?" or
"which clause caused the biggest deduction?".

An assistant is one more model in the system, and the easy designs widen access: giving it
the whole review response would send the bank account number and the reviewer's notes to
the model provider; giving it its own data access would make it a seventh data-holding
agent with new scopes. The question is how to give officers an agent that plans and looks
things up, without adding any access.

## Decision
Add an **Agno agent with six read-only tools** to the Officer page, scoped to the one claim
that is open.

- **Agentic.** The model starts with only the claim id and the question. It chooses which
  tools to call (at most 8 calls per question), then answers from what they returned:
  `get_claim_overview`, `get_settlement`, `get_fraud_signals`, `get_medical_finding`,
  `get_bill`, `get_routing_reasons`.
- **Every tool call is governed** (invariant 1). Each call goes through
  `check_and_audit()` as agent `officer_assistant`: GOV-001 allowlist
  (`security-matrix.md` §7), GOV-002 per-request budget, a hash-chained audit entry and a
  `governance.decision` span. A denial is returned to the model as a structured denial,
  never data; an error in the check is a denial (invariant 7). The assistant is denied
  every action and restricted tool (payout, state changes, bank details, medical records,
  break-glass), proven by tests.
- **No new data access.** The tools never touch a data store. `POST /claims/{id}/assistant`
  on the officer API reads the claim the same way `GET /claims/{id}/review` already does
  and builds an allowlisted claim view; each tool returns one slice of it. The assistant
  holds no data scope and no token, so the agent × collection matrix does not change.
- **Never in the claim view:** the bank account number, the medical reviewer's
  `notes_for_officer` (schemas.py: "never passed to other agents"), the claimant-written
  `stated_illness`, document text and diagnosis text (invariant 4). Fields are copied by
  name, so a field added to `claims.assessment` later stays out until added on purpose.
- **Routing answers come from code, not the model.** `get_routing_reasons` runs the same
  `decide_tier()` the claim-assessment workflow ran.
- **Same ₹ guardrail as ADR-011.** Every amount in the answer must exist in the claim's
  data (settlement amounts, remaining sum insured, bill figures, the ₹50,000 auto-pay
  ceiling), or the answer is replaced with a notice naming the amount.
- **Fail closed.** A claim with no assessment gets a fixed answer with no model call. A
  model error or empty answer returns 502 `ASSISTANT-UNAVAILABLE`, never a guess.
- **No actions.** It cannot approve, reject or pay; the decision form stays the only way a
  T3 claim moves.
- **Same model config as the claim agents** (`MODEL_PROVIDER` / `MODEL_ID`).
- **Visible.** The answer lists the tools the agent called and whether AGT allowed each;
  an `officer.assistant` span records the tools called (never the question or answer
  text); Agno's spans pass through the redaction processor.

## Alternatives considered
- **A single model call with the claim pasted into the prompt** (the first version):
  simpler, but every answer sends every field, and nothing about the model's behaviour is
  governed or audited.
- **A seventh agent with data-gateway access:** a new identity, scopes and trust
  thresholds for a convenience feature, and a wider read surface.
- **Forwarding the whole review response:** would send bank details and officer notes to
  the model provider.
- **Including the discharge summary via break-glass:** an audited human exception would
  become routine machine access.
- **Cross-claim questions** ("all T3 claims with fraud flags this week"): needs a list
  endpoint over many claims. Deferred.

## Consequences
- Officers get grounded answers and can see exactly what the agent looked up; every
  lookup is in the same audit log as the claim agents' tool calls.
- Answers are limited to the fields in the claim view; the assistant says so when asked
  for anything else.
- The ₹ check can replace an honest answer that computed a new figure (e.g. a sum of two
  line items), as with ADR-011: the cost is a notice, never a wrong number.
- Several model round trips per question (one per tool step), against the same provider
  rate limit as claim runs.
