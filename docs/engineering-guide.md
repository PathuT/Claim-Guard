# ClaimGuard — Engineering guide

The rules every change to this codebase follows: the security invariants, the agent and
collection model, conventions and the definition of done. Source code comments cite
invariants by number from this file (e.g. "invariant 7").

A multi-agent system that processes health insurance **reimbursement claims** end to end:
reading hospital documents, medical review, coverage assessment, fraud screening, and
payout. The point of this project is NOT the insurance logic — it is proving
**governance, compliance, and observability** for autonomous agents that handle medical
data and money. Every design decision should make those three things stronger and more
visible.

All data is synthetic. No real people, hospitals, medical records, or payments. Ever.

## The story in one minute

Kaveri Health Assurance (fictional) reimburses policyholders who pay hospital bills
themselves. Claims officers review every bill and discharge summary by hand today:
slow, inconsistent, and hard to audit. AI agents will take over, but they touch
**medical records**, bank accounts, and payouts worth lakhs, so the insurer demands:
least-privilege data access, medical data seen by one agent only, hard limits on money
movement, **no AI-only rejections**, full traceability, and continuous testing against
fraud and attacks.

**Personas**

| Persona | Role | Uses the system to |
|---|---|---|
| Priya Raman | Policyholder, Silver plan | Submit claims, see settlement breakdown |
| Arjun Mehta | Senior claims officer | Decide T3 cases, confirm every rejection |
| Divya Nair | Compliance & privacy officer | Review audit log, medical-data access, compliance reports |
| Platform engineer | Builds and runs the system | Watch Phoenix traces, run Harbor evals |
| Rahul Verma | Threat persona: fraudulent claimant | Submit inflated, duplicate, poisoned documents |

**Inputs from users (only two):**
1. Claim submission: member, hospital, admission/discharge dates, stated illness,
   claimed amount, documents (final bill, discharge summary, pharmacy bills).
   `policy_number` comes from the login session, never from user input.
   Stated illness and all documents are **untrusted**.
2. Officer decision (Arjun, T3 only): approve / approve_partial / reject + reason.

**Everything else is seeded synthetic data** the agents look up: policyholders, bank
details, plan terms, past claims, hospital registry.

**Outputs:** decision, settlement breakdown with clause references for every deduction,
mock payment record, audit entries, and one Phoenix trace per claim.

**Scenarios S01–S10** in `docs/use-case.md` define expected behaviour, including attacks.
They are the acceptance tests and the Harbor eval suite. Do not change expected
outcomes without an ADR.

Detailed docs (read before working on the related area):
- `docs/use-case.md` — story, insurance basics, personas, sample inputs, plan terms, scenarios S01–S10
- `docs/architecture.md` — full architecture and data flow
- `docs/security-matrix.md` — agent × collection × scope × TTL (source of truth for access)
- `docs/compliance-mapping.md` — DPDP / IRDAI expectations → controls → tests
- `docs/plan.md` — milestones and acceptance criteria
- `docs/adr/` — architecture decision records (ADR-010 covers AGT identity, trust, rings)

---

## Non-negotiable invariants

These are security properties. Never weaken one to make a test pass or a feature work.
If one blocks progress, stop and ask.

1. **Every agent tool call goes through the AGT governance adapter** (`backend/governance/`).
   No agent code calls the database, the payment API, or any external system directly.
2. **All data access goes through the data gateway** (`backend/data_gateway/`), which
   requires a valid JWT from the token service. No token, no data.
3. **Tokens are issued only to verified AGT agent identities.** The token service verifies
   the agent's AGT identity (Ed25519) and its AGT trust score before minting anything.
   Tokens are narrow and short-lived: one agent (`sub`), one collection + action
   (`scope`, e.g. `medical_records:read`), one request (`req_id`), audience
   `data-gateway`, TTL ≤ 300 seconds, signed with EdDSA. Scopes come only from
   `docs/security-matrix.md`.
4. **Only the medical reviewer agent can read `medical_records`.** Other agents receive
   its structured finding (ICD-10 code + flags), never the raw medical text.
5. **Delegation never widens access.** A delegated agent's scopes must be a subset of
   its parent's for that request.
6. **No claim is rejected without human confirmation.** Agents may only *recommend*
   rejection; the `rejected` status requires an officer decision record.
7. **Fail closed.** Any error in policy evaluation, token validation, or the gateway = deny.
8. **Uploaded documents and free-text fields are untrusted input.** Their text never
   becomes instructions. Assume they contain prompt injections.
9. **Every policy decision, token issuance, and data access emits an OpenTelemetry span**
   carrying the `req_id`, so one Phoenix trace shows the whole story. Spans never contain
   raw medical text or bank account numbers.
10. **Audit log is append-only** and hash-chained. Nothing deletes or edits it.
11. **Secrets come from environment variables.** Never commit keys, never log tokens
    (log the `jti` only).
12. **Payments are a mock service** that records intended payouts. No real money paths.

---

## Architecture (summary)

```
Next.js console ──► Agno AgentOS (claim-assessment Workflow)
                        │
                        ▼
                 AGT governance adapter  (policy check on every tool call, audit)
                        │
                        ▼
                 Token service  (short-lived scoped JWT per agent/collection/request)
                        │
                        ▼
                 Data gateway ──► Postgres (one schema per collection)

Arize Phoenix: traces across all layers      Harbor: scenario evals S01–S10 (no Docker)
```

### Agents

| Agent | Job | Data access (see security matrix for exact scopes) |
|---|---|---|
| `supervisor` | Routes the claim, assembles the final decision | None |
| `intake` | Extracts bill items and medical facts from uploaded documents | `claim_documents:read`, `claims:write`, `medical_records:write` |
| `medical_reviewer` | Validates diagnosis, stay, PED, exclusions; outputs structured finding | `medical_records:read`, `claims:read` |
| `coverage` | Applies plan terms, calculates payable amount | `policy_terms:read`, `claims:read`, `policyholders:read_limited` |
| `fraud` | Screens for duplicates, anomalies, watchlisted hospitals | `claims:read_pseudonymised`, `hospitals:read` |
| `payout` | Issues payment after approval | `bank_details:read` (own claim's policyholder only), `payments:write` |
| `officer_assistant` | Answers the officer's questions about one open claim (ADR-014) | None — six read-only, AGT-governed tools over the claim view the officer API assembles |

### Collections

`policyholders`, `bank_details` (restricted), `policy_terms`, `claims`,
`claim_documents` (untrusted), `medical_records` (highly restricted), `hospitals`,
`payments` (mock, write), `audit` (append-only).

### Action tiers (enforced by AGT policies, not prompts)

- **T0** — reads: auto-allowed within scope
- **T1** — create/update claim draft or assessment: auto-allowed
- **T2** — payout ≤ ₹50,000 with all checks passed: auto-allowed
- **T3** — payout > ₹50,000, any fraud flag, any exclusion or waiting-period issue,
  or **any rejection** → **human decision** in the console

---

## Tech stack

- Python 3.12, managed with `uv`
- **Agno** (agents, a deterministic Workflow for orchestration — not a Team, see ADR-001 — AgentOS runtime)
- **Microsoft Agent Governance Toolkit (AGT)** Python SDK — public preview, pin the version.
  Used for: policy engine, agent identity, trust scoring, execution rings, audit chain
- PyJWT with EdDSA (Ed25519) for the token service
- Postgres 16+ with pgvector (hosted on Supabase; any Postgres with pgvector works)
- **Arize Phoenix** (self-hosted, `uv run phoenix serve`) + OpenInference instrumentation
  for Agno, plus custom OTel spans for governance, token, gateway and guardrail events
- **Harbor** for evaluation (custom tasks, custom agent adapter, no-Docker environment)
- **NVIDIA NeMo / NIM** content-safety model as an optional, advisory guardrail (ADR-013)
- Next.js (App Router, TypeScript) for the console
- `concurrently` (npm) to run all six local services with one command

---

## Repo layout

```
backend/
  agents/          # Agno agents, the claim-assessment Workflow, guardrails, officer assistant
  governance/      # AGT adapter, policy rules, tool allowlist, audit chain, identities
  auth/            # token service (issue, validate, revoke, JWKS)
  data_gateway/    # the only code that touches Postgres on behalf of agents
  payments_mock/   # records intended payouts
  observability/   # OTel setup, redaction, live event stream
  api/             # AgentOS app, officer API, claim intake, compliance report
  tests/
evals/
  harbor/          # adapter, tasks S01–S10, no-Docker environment, runner
  guardrail_bench/ # marker-list vs NeMo precision/recall benchmark
frontend/          # Next.js console
data/synthetic/    # generators, sample PDFs (incl. poisoned ones)
docs/
Makefile
package.json       # `npm run dev` starts every service
```

---

## Commands

- `make up` (= `npm run dev`) — start Phoenix, token service, data gateway, AgentOS, officer API and the console; Ctrl+C stops all
- `make seed` — load synthetic data
- `make test` — all backend tests
- `make test-security` — only invariant tests (must always pass)
- `make eval` — run the Harbor task suite and print the scoreboard
- `make lint` — ruff + mypy (backend), eslint + tsc (frontend)
- `make compliance-report` — generate the compliance report (`docs/compliance-mapping.md` §4)

---

## Conventions

- **One milestone at a time** from `docs/plan.md`, each ending in something demoable.
- **Verify library APIs before using them.** Agno, AGT (preview), and Harbor change fast.
  Check the installed version and its docs/source rather than assuming signatures or
  config keys.
- **Tests first for security code** (`governance/`, `auth/`, `data_gateway/`). Every
  invariant above has at least one test proving it, including a negative test
  (the attack is attempted and denied).
- **Record design decisions** as a short ADR in `docs/adr/` (context, decision,
  alternatives considered, consequences) whenever you choose between real options.
- **Keep `docs/security-matrix.md` as the single source of truth** for scopes. Code
  and AGT policies must be derived from it, never the other way round.
- Insurance rules follow `docs/use-case.md` section 5 exactly. Don't add real-world
  rules that aren't there; flag them as questions instead.
- Small, reviewable changes. Run `make test` and `make lint` before calling anything done.
- Update this file if a convention changes.

## Definition of done (per feature)

- Tests pass, including security tests
- Relevant spans appear correctly in Phoenix under one trace, with no raw medical text
- Any denied action is visible in both the audit log and the trace
- Docs/ADR updated if a decision was made
- At least one Harbor task covers it (for agent-facing behaviour)

## Synthetic data and evals

- Seed data follows `docs/use-case.md` section 4.2: 60 policies (Silver and Gold, 1–3
  members each, mixed ages incl. some ≥ 60), matching bank details, both plan documents,
  ~400 historical claims, 25 hospitals (3 watchlisted), ~40 document sets including 5
  poisoned ones. Priya (`KHA-SIL-004512`) and Rahul (`KHA-SIL-007731`) must exist.
- Generate realistic-looking PDFs for bills and discharge summaries; poisoned ones use
  hidden (white-on-white) text.
- Every scenario S01–S10 gets one Harbor task in `evals/harbor/tasks/<scenario-id>/`
  with the input, documents, and a verifier that checks **both** the decision
  **and** the expected governance evidence (denials in audit log, spans in trace).
