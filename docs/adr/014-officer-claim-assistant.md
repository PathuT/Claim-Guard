# ADR-014: Read-only claim assistant for the officer

- **Status:** accepted
- **Date:** 2026-09-28

## Context
A claims officer deciding a T3 claim reads the settlement, deductions with clause ids,
fraud signals and the medical reviewer's structured finding on the Officer page.
Officers asked for a faster way to get answers such as "why is this with me instead of
auto-paid?" or "which clause caused the biggest deduction?" without reading every field.

A chatbot is one more LLM call, and it could quietly widen access. If it had tools, its
own data access, or any raw text the page keeps back, it would need its own identity,
scope and audit path, which amounts to a seventh agent. The question is how to give
officers natural-language answers without adding any access.

## Decision
Add a read-only assistant panel to the Officer page, scoped to the one claim that is
open, over data the page already shows.

- **No new access.** `POST /claims/{id}/assistant` on the officer API
  (`backend/api/officer.py`) reads the claim the same way `GET /claims/{id}/review`
  already does. `agents/officer_assistant.py` copies an allowlist of named fields into
  the prompt: status, claimed/payable/co-pay, deductions with clause ids,
  recommended decision, flags, fraud signals, the structured medical finding and the
  bill's line items and dates. The assistant has no tools, no AGT identity, no
  token-service scope and never calls the data gateway, so `security-matrix.md` does
  not change.
- **Never sent to the model:** the bank account number (`registered_account_ref`), the
  medical reviewer's `notes_for_officer` (schemas.py: "never passed to other agents"),
  the claimant-written `stated_illness`, document text and diagnosis text (invariant 4).
  Because fields are copied by name, a field added to `claims.assessment` later stays
  out until someone adds it on purpose.
- **Same guardrail as ADR-011.** Every ₹ amount in the answer must be in the claim's
  data (the settlement's allowed amounts, the remaining sum insured, the bill total and
  line items). If one is not, the answer is replaced with a notice naming the amount.
- **Fail closed.** A claim with no assessment gets a fixed answer without a model call.
  A model error or empty answer returns 502 `ASSISTANT-UNAVAILABLE`, never a guess.
- **No actions.** It cannot approve, reject or pay; the decision form stays the only way
  a T3 claim moves.
- **Same model config as the agents** (`MODEL_PROVIDER`/`MODEL_ID`, Groq retries), so
  no new key or vendor.
- **Observable.** An `officer.assistant` span (claim id, question length, whether the
  answer was replaced; never the question or answer text) plus Agno's own spans, which
  the redaction processor already masks. Terminal log lines use the same `emit` as the
  guardrails.

## Alternatives considered
- **A seventh agent with gateway access**, so it could answer anything: needs a new
  identity, scopes and trust thresholds for a convenience feature, and widens who reads
  what.
- **Forwarding the whole review response to the model:** simpler, but it would send
  the bank account number and the officer notes to the model provider.
- **Including the discharge summary via break-glass:** an audited human exception
  would become routine machine access.
- **Cross-claim questions** ("all T3 claims with fraud flags this week"): needs a list
  endpoint and a wider data set. Deferred.
- **Policyholder-facing chat:** a new consumer-facing surface with its own abuse cases,
  and not what the officer asked for.

## Consequences
- Officers get quick, grounded answers with no change to access, scopes or the audit
  model.
- An answer can only be as good as the fields it sees. It cannot explain the medical
  reasoning beyond the structured finding, and says so.
- The ₹ check can replace an honest answer that computed a new figure (for example a
  sum of two line items), as with ADR-011: the cost is a notice, never a wrong number.
- One more model call per question, against the same Groq rate limit as claim runs.
