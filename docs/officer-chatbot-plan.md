# Officer chatbot — plan (future milestone, not yet built)

Status: **plan only, nothing implemented**. Written up so the idea can be picked up
later without re-deriving the scoping decisions already made in conversation.

## 1. What this is

A natural-language Q&A layer for the claims **officer**, not the policyholder. It
answers questions like "why is this claim flagged," "summarize the fraud flags on
CLM-2026-018833," or "what does clause 5.G1 mean" — over data the officer already
sees today on the Officer queue and Compliance pages. It's a UX layer, not a new
data-access path.

## 2. Scope: what it can and cannot query

**Confirmed with the user:** the chatbot may only query what's already shown on the
existing Officer and Compliance pages — findings, fraud flags, settlement/clauses,
claim status, and audit log entries. Nothing new.

Explicitly **out of scope** for this version:
- Raw medical text / diagnosis_text (invariant 4: only `medical_reviewer` reads
  `medical_records` — a chatbot with that access would need break-glass parity,
  audited reason-logging, and its own scope in `security-matrix.md`; bigger than a
  UI feature, deferred).
- Policy-term lookups beyond what's already surfaced in a settlement's clause
  citations (a small future extension, not v1).
- Any write/action capability (approve, reject, trigger payout). Read-only.

## 3. Why this scope keeps the existing invariants intact

Because the chatbot only reads from data the officer's existing pages already
display, it needs:
- **No new AGT scope.** It's not calling the data gateway directly — it reads from
  whatever the officer/compliance API endpoints already return to the browser.
- **No new agent identity.** It isn't one of the six ClaimGuard agents and doesn't
  request tool calls through the governance adapter.
- **No change to `security-matrix.md`.** The officer role's existing scopes already
  cover everything the bot would surface.

This keeps it a genuine UI/UX addition rather than a new governed component — the
same reasoning that made NeMo (ADR-013) an addition rather than a redesign: don't
widen what any role can see, just make what they can already see easier to query.

## 4. Architecture (proposed, not verified against current code)

- Lives in the Next.js console, likely as a panel on the Officer page (`frontend/app/
  (console)/officer/`) or a new `/officer/assistant` route.
- Calls the **existing** officer/compliance FastAPI endpoints for data — never the
  data gateway, never a new agent. The exact endpoints and response shapes were
  **not confirmed this session** — inventory them first (see §5).
- The chat itself needs an LLM call (a new, separate call — not one of the six
  ClaimGuard agents' contexts). Reuse the existing model-agnostic pattern
  (`MODEL_PROVIDER`/`MODEL_ID`, `agents/model_config.py`) rather than introducing a
  new provider, consistent with ADR-001's model-agnostic stance — unless there's a
  specific reason to do otherwise.
- Should be a plain request/response or streamed chat call, summarizing/answering
  over the data already fetched for the current officer session — not a new agent
  with its own tool-calling loop into governed systems.

## 5. Data sources to inventory before building (not done yet)

Before writing any code, confirm:
- The officer queue API: file path, route, and exact response shape (T3 claims,
  findings, fraud flags, clauses).
- The compliance API: audit log, denials, medical-data access report endpoints and
  shapes.
- Whether these are served by a dedicated `api/officer.py` / `api/compliance.py` (or
  similarly named) FastAPI router, and what auth/session check already guards them.
- What the frontend pages (`frontend/app/(console)/officer/`, `frontend/app/
  (console)/compliance/`) currently render, to confirm what's already considered
  "safe to show an officer" and shouldn't need re-litigating.

This wasn't done as part of this plan — the session was interrupted before the
research pass ran. Do this first when picking the plan back up.

## 6. Build steps (draft)

1. Inventory existing officer/compliance endpoints and page contents (§5).
2. Write a short ADR (`docs/adr/014-...`) recording the scope decision from §2–3 and
   the "no new governance" argument, same pattern as ADR-011/013.
3. Design the chat request/response contract: what context (claim id, current
   officer session) gets passed to the LLM call, and how the answer is grounded in
   the already-fetched data (avoid the model inventing figures — same anti-
   hallucination spirit as ADR-011's explanation guardrail, applied here too).
4. Build the backend endpoint that assembles context from the existing officer/
   compliance data and calls the LLM.
5. Build the frontend chat panel/page.
6. Add tests: the endpoint should never be reachable with claim data the officer's
   role wouldn't otherwise see (assert against `security-matrix.md`'s officer scope),
   and a hallucination check analogous to `validate_explanation` if the bot cites
   specific numbers.
7. Update `docs/architecture.md` and the console's `/architecture` page the same way
   ADR-013/NeMo was documented this session — don't let this become an undocumented
   feature.

## 7. Guardrails for the chatbot itself

Same philosophy as ADR-011/013 — the model is an untrusted generator, not an
authority:
- Ground every factual claim (a ₹ amount, a decision, a flag) in the data actually
  fetched for that claim; don't let the model answer from its own "knowledge" about
  insurance in general when a specific claim is being discussed.
- Fail closed on missing context: if the bot can't fetch the claim's data, say so —
  don't let the model guess.
- No write/action capability in v1 (§2) — this removes an entire class of risk
  (the bot can't approve, reject, or trigger a payout, so a bad answer costs at most
  officer confusion, not a governance bypass).

## 8. Open questions before starting (only the user can decide these)

- Which page does this live on: a panel on the existing Officer queue, or its own
  route?
- Model/provider for the chat call itself — same as the claim agents (Groq/Gemini),
  or something else?
- Should it be scoped per-claim (officer is already looking at one claim) or allow
  cross-claim questions ("show me all T3 claims with fraud flags this week")? The
  latter needs a list/aggregate endpoint, not just a single-claim one — bigger scope.
- Is this worth doing before or after the audit-chain re-verifier / guardrail-model
  swap (`meta/llama-guard-4-12b` benchmark) that were also proposed this session?

## 9. Effort estimate

Comparable in shape to the M8 console milestone in `docs/plan.md` (~1 day), but
smaller in scope since it reuses existing data endpoints rather than building new
pages from scratch — rough estimate **0.5–1 day**, assuming §5's inventory turns up
no surprises (e.g. the officer/compliance endpoints already return everything needed
without new backend work).
