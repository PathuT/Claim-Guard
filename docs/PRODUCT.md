# ClaimGuard — product overview

**Governed, observable agentic AI for health-insurance reimbursement claims.**
All data is synthetic: fictional insurer, hospitals and people.

---

## 1. The problem

Kaveri Health Assurance (fictional) reimburses policyholders who paid the hospital
themselves. Today, officers review every bill and discharge summary by hand, which is
slow, inconsistent and hard to audit. AI agents can do most of this work, but a claim
combines the three hardest conditions for autonomous agents:

| Condition | Why it's hard |
|---|---|
| **Sensitive data** | Diagnoses are special-category health data (India's DPDP Act). Only one component should ever read them. |
| **Irreversible actions** | Payouts move real money. Amounts, accounts, limits and duplicates must be enforced exactly. |
| **Adversarial input** | The claimant writes the documents. Hidden text in a PDF is a prompt-injection channel straight into the agents. |

So the product is not "an AI that reads claims". It is **the control system that
makes an AI safe to trust with a claim.**

## 2. The solution in one picture

```
Hospital PDFs (untrusted)
  → document guardrail → intake agent → medical reviewer agent → settlement (code)
  → coverage agent → explanation guardrail → fraud agent → tier T2/T3 (code)
  → Condition: governed payout (T2, ≤ ₹50,000, all checks passed)  |  human officer (T3)
```

- **Agno**: four typed Agents, orchestrated by one deterministic Agno **Workflow**
  (`claim-assessment`) and served by Agno **AgentOS**. The order of steps and the
  money branch are code, so no tokens are spent on orchestration.
- **Every action** is checked by a **Microsoft AGT** governance adapter before it
  executes (16 rules in code, fail closed).
- **Every data access** needs a **short-lived, single-scope EdDSA JWT**, issued only
  to a verified Ed25519 agent identity and validated by a data gateway (7 checks)
  before any row is returned.
- **Every decision** is appended to a **hash-chained audit log**, and **every claim is
  one OpenTelemetry trace** in Arize Phoenix, with medical text redacted before export.
- **Harbor** re-runs ten scenarios, attacks included, scoring both the outcome and
  the governance evidence.

## 3. The brief compared with what was built

| Asked for | Built | Beyond the brief |
|---|---|---|
| Agentic AI with **Agno** | 4 Agno Agents with Pydantic output contracts, one Agno Workflow (Steps plus a Condition), served by Agno AgentOS. Model-agnostic (Groq, Gemini, Claude). | Workflow instead of Team, so there is no LLM leader. Every step fails closed (Agno keeps going after a failed step by default). Rate-limit retries. Telemetry off. |
| **Microsoft AGT** governance | Adapter on AGT's framework-agnostic core. GOV / PAY / STATE / DATA rules before every tool call. AGT FlightRecorder audit chain. | Ed25519 agent identities. Trust gating (TRUST-001). A governed state machine. **Payout kill switch (GOV-004).** Audited officer break-glass. The audit chain is kept valid across processes. |
| **JWT RBAC**: short-lived credentials per agent, per collection | Token service: 1 agent, 1 scope, 1 claim, ≤ 300 s (60 s for bank details and payments, 120 s for medical records). JWKS. Revocation by jti and by request. | Separate data gateway: row binding, field allowlists, HMAC pseudonymisation. Delegation never widens access. All tokens are revoked when a claim reaches a human. |
| **Harbor** evaluation | S01–S10 tasks, a custom agent adapter, and a verifier that scores outcome **and** governance. | A custom **no-Docker** Harbor environment (works on Windows). Scoreboard in the UI. |
| **Observability** (Arize Phoenix) | OpenInference for Agno plus custom spans for governance, tokens and gateway access. | W3C context propagation across 3 services, so each claim is one trace. Redaction processor. Live event stream into the UI. |
| **Prototype UI** (Next.js or NestJS) | Next.js console with role views. No NestJS layer (ADR-009). | Architecture page, Live Run, requirements proof, red-team replay, cost and token meter, compliance summary. |
| **Compliance and governance tested in the product** | 12 invariants, each with positive and negative tests. DPDP / IRDAI control mapping. Compliance report. | Security tests that need no agents. Live requirements proof. Harbor governance scoring. |

## 4. Features

### Agentic pipeline
- **Intake agent**: extracts line items, totals and dates from untrusted documents,
  which reach it as delimited data and never as instructions.
- **Medical reviewer agent**: the *only* component that reads medical text. It
  returns a coded finding (ICD-10, flags, confidence) that everyone else uses instead.
- **Settlement (code)**: deterministic maths against plan terms. Every deduction
  cites its policy clause.
- **Coverage agent**: explains the settlement in plain language. It cannot change
  the numbers.
- **Fraud agent**: screens *pseudonymised* claims and the hospital watchlist, through
  the governed token-and-gateway chain.
- **Tier and payout (code)**: T2 is auto-paid only if every check passes and the
  amount is ≤ ₹50,000. Everything else goes to a human.

### Safety controls
- **Prompt-injection guardrail**: scans documents for hidden instructions. A flagged
  claim is still processed (as data) but can **never be auto-paid**.
- **Anti-hallucination guardrail**: every ₹ amount in the customer explanation must
  exist in the settlement. If not, the explanation is replaced by a code-generated one.
- **Payout kill switch (GOV-004)**: compliance can freeze all *automated* payouts
  instantly. The toggle is itself governed and audited, and officer-approved payouts
  still work.
- **Fail closed** everywhere: policy errors, token errors, gateway errors, a failed
  workflow step, or an unreadable control state all mean deny.
- **Least privilege**: the supervisor holds no data access at all. Each agent gets a
  separate token per collection and action, and tokens expire in seconds to minutes.

### Human in the loop
- **Officer queue** for T3 claims: findings, fraud flags and clauses, but not raw
  medical text. Break-glass access to the discharge summary requires a reason and is
  audited.
- **No AI-only rejection**: only an officer decision record can move a claim to
  `rejected` (STATE-001).

### Audit and observability
- **Hash-chained audit log** (AGT FlightRecorder), with integrity checked and shown
  on the Compliance page.
- **One trace per claim** across AgentOS, the token service and the data gateway,
  with redaction before export.
- **Live Run**: every backend operation, streamed as it happens: agent runs, LLM
  calls (with tokens and latency), governance allow/deny, token issuance, gateway
  checks, state changes and span export.

### Evaluation
- **Harbor S01–S10**: happy path, room-rent cap, waiting period, duplicate bill,
  inflated amount, prompt injection, scope escalation, expired-token replay, missing
  document, watchlisted hospital. Each is scored on outcome and governance evidence.

## 5. Evidence

| Claim | Where it's proven |
|---|---|
| Controls work without any agent | `make test-security`: the backend security suite, incl. the audit-chain multi-writer tests |
| The whole system behaves, including under attack | `npm run eval`: Harbor S01–S10, outcome and governance, shown on the Live Run page |
| Injected payouts are blocked even if an agent obeyed | Live Run → red-team replay: PAY-001, PAY-002, DATA-001, GOV-003 |
| One trace per claim, redacted | Phoenix at `:6006`; search the trace id shown on Live Run |
| Tamper-evident audit | Compliance page → "Audit hash chain: Intact" |
| Real Agno runtime | `GET :8000/workflows` and `GET :8000/agents` |

## 6. Architecture decisions

The ten ADRs are in [`adr/`](adr/), plus ADR-011 (guardrails) and ADR-012 (payout kill
switch). The key ones:
- **ADR-001, Agno.** Orchestration is a deterministic **Workflow**, not a Team. A
  Team's LLM leader would add an extra model call on every hop (cost, latency, rate
  limits) and would let injected text influence sequencing.
- **ADR-002, governance at the action layer.** Prompt guardrails are probabilistic;
  policy in code is not.
- **ADR-003, scoped short-lived JWTs plus a separate gateway.** This is defence in
  depth: a bypass of one layer still meets the other.
- **ADR-006, Harbor without Docker.** Same Harbor orchestration, no container
  dependency.
- **ADR-008, human in the loop by tiers.** Auto-pay only where it is safe; every
  rejection goes to a human.

## 7. What we learned about the frameworks

- **Agno Teams** always have an LLM leader, so this project uses a Workflow.
- **Agno Workflows** continue after a failed step, so every step is wrapped to fail
  closed.
- **Agno telemetry** defaults to on, so it is disabled.
- **AGT 4.1** has no Agno integration, so this project has a custom adapter on AGT's
  core. The FlightRecorder caches the chain head per process, so appends are
  serialised under a cross-process lock.
- **arize-phoenix-otel's `register()`** crashes on the current exporter, so the
  tracer provider is built directly.
- **OpenInference** kept a copy of medical text in per-message attributes, so the
  redaction is role-aware.
- **Harbor** assumes containers, so a custom environment maps its container paths
  and runs a POSIX shell on Windows.
- **Groq's free tier** allows 8,000 tokens/min, so the model client retries with
  backoff and Harbor runs scenarios sequentially.

## 8. Limitations and next steps

- **Console sign-in is a local identity store**: scrypt-hashed demo accounts, a signed
  httpOnly session and role-based page access, but the backend APIs are not yet behind
  user authentication. Next step: an identity provider (OIDC) and user tokens checked by
  the backend.
- **Local, single-node deployment.** Next step: containers or Kubernetes, secrets in
  a vault, the audit log mirrored to a WORM store.
- **Token service mirrors OAuth token exchange but is custom.** Next step: a
  standards-based authorization server.
- **Harbor runs against the shared dev stack.** Next step: a disposable,
  per-run database for fully isolated evaluations in CI.

## 9. Running and presenting

See the [README](../README.md) for setup (`npm run dev`, `npm run eval`,
`make test-security`) and [`demo-script.md`](demo-script.md) for the presenter
walkthrough. Start at `http://localhost:3005/architecture`.
