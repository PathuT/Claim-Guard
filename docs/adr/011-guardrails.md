# ADR-011: Deterministic guardrails around the model

- **Status:** accepted
- **Date:** 2026-09-27

## Context
The governance rules (ADR-002) decide what an agent may *do*: they make sure an
injected payout can never succeed. Two risks sit before that point, in what a model
*reads* and *writes*:

1. **Hidden instructions in documents.** The claimant writes the bill and discharge
   summary. A poisoned PDF (S06) carries invisible text such as "pay ₹4,50,000 to
   account …". Delimiting the text as untrusted data (invariant 8) keeps the agents
   from obeying it, and PAY-001/PAY-002 would block the payout anyway. But a claim
   that *contains* an attack should not be auto-paid even if every number looks
   right. It should reach a human with the evidence.
2. **Invented figures in the explanation.** The coverage agent explains the
   settlement in plain language. The settlement maths is deterministic code, but
   the *text* is model output, so it can contain an amount the settlement never
   produced. That figure would then reach the policyholder or the officer.

## Decision
Add two guardrail steps to the `claim-assessment` Agno Workflow
(`backend/agents/guardrails.py`). Both are **plain Python, not prompts or LLM
judges**, and both fail closed like every other step.

- **`document_guardrail` (before intake).** It scans each document's extracted text
  for instruction-like phrases, using the same marker list as the upload endpoint
  (`api.claim_intake.scan_injection_markers`). A match **does not stop the run**:
  the documents are still processed as delimited untrusted data. Instead the claim
  gets `INJECTION_FLAG` and the tiering function forces **T3**, so it can never be
  auto-paid and the officer sees why.
- **`explanation_guardrail` (after coverage).** `validate_explanation` extracts every
  money amount in the explanation (lakh, crore and k are expanded). Each one must be
  in the settlement: claimed, payable, co-pay, each deduction and their sum, the
  figures that follow exactly from them (claimed minus deductions, claimed minus
  payable), or a per-day rate quoted in a deduction's reason. If any is not, or if
  the explanation is empty, the text is replaced by `build_fallback_explanation`,
  which is a template built only from the settlement.
- Both steps emit a `guardrail.*` span and a live event, so the result shows in
  Phoenix and on the Live Run page.

## Alternatives considered
- **Reject a flagged claim outright:** an automated rejection breaks STATE-001 (only
  officers reject), and a false positive would hurt an honest policyholder. Routing
  to a human keeps both safe.
- **Strip the suspicious text and continue:** hides the evidence from the officer,
  and a partial strip can leave a working payload behind.
- **An LLM judge ("is this an injection?"):** probabilistic, costs tokens, and can
  itself be attacked by the text it is judging.
- **Ask the coverage agent to double-check its numbers:** still model output; no
  guarantee.

## Consequences
- A poisoned claim can never be auto-paid, even if the rest of the claim is clean,
  and the flag is visible to the officer and in the audit and trace.
- No invented ₹ figure reaches a customer. When the model's text is replaced, the
  customer gets a plainer explanation, but the numbers are correct.
- The marker list is a heuristic. A novel phrasing can pass the scan, and that is
  acceptable: the scan only adds caution. PAY-001, PAY-002 and DATA-001 still block
  the actions an injection is trying to cause.
- The amount check can reject an honest explanation that uses a derived figure (for
  example a rounded total or the number of days times a rate). The cost is a template explanation, not a wrong
  decision.
