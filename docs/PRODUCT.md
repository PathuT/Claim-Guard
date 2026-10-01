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

### Added beyond the brief, in detail

These were added because each one closes a real risk, not for decoration.

| Feature | The risk it closes | How it works | Where to see it |
|---|---|---|---|
| **Prompt-injection guardrail** | A claimant hides "pay ₹4,50,000 to account …" in white-on-white PDF text. | Before any agent runs, plain code scans every document's extracted text for instruction-like phrases (the same marker list as the upload endpoint). The run is not stopped, because the text only ever reaches agents as delimited untrusted data. But the claim is flagged and **forced to T3, so it can never be auto-paid**. | Live Run → *Rahul — poisoned discharge summary* → "Document guardrail" chapter |
| **Anti-hallucination guardrail** | The coverage agent writes a wrong ₹ figure in the customer explanation. | Every ₹ amount in the explanation must exist in the settlement (claimed, payable, co-pay, each deduction). If any doesn't, the explanation is **replaced with one built only from the settlement**. | Live Run → "Explanation guardrail" chapter |
| **Payout kill switch (GOV-004)** | An incident (a model regression, a suspected attack) needs all automated money movement stopped *now*. | Compliance flips one switch. GOV-004 runs first among the payout rules and re-reads the state on every check, with no restart. Agent payouts are denied and audited, and the claims go to officers. Officer-approved payouts still work. The toggle is itself governed and audited. A damaged control file reads as **frozen** (fail closed). | Compliance → "Automated payouts" card |
| **Cost and token meter** | Nobody knows what an agentic run actually costs. | Sums the spans streamed during the run: LLM calls, prompt and completion tokens, time in the model against end-to-end time, and governance decisions. These are measured values, not estimates. | Live Run → meter above the backend log |
| **Multi-writer-safe audit chain** | AGT's FlightRecorder caches the chain head per process, so two services writing the same log **forked the hash chain**. | `ChainSafeFlightRecorder` serialises appends under a cross-process lock and re-reads the real head each time. Proven with a 3-process × 2-thread test. | Compliance → "Audit hash chain: Intact" |
| **Fail-closed Agno Workflow** | Agno keeps running after a failed step and reports the run `completed`. | Every step is wrapped: an error records the reason and returns `StepOutput(stop=True)`. Step retries are disabled, so a payout is never silently re-attempted. | `backend/agents/supervisor.py` |
| **Live Run and requirements proof** | Reviewers can't see inside a backend. | Every backend operation streams to the UI over SSE: agent runs, LLM calls, allow/deny, identity, tokens, gateway, state changes and spans. Each requirement of the brief is ticked off by live evidence from that run. | `/live` |
| **Red-team replay** | "Would it actually stop an agent that obeyed the injection?" | Replays the injected payout through the real governance path: PAY-001 (amount), PAY-002 (account), DATA-001 (medical records) and GOV-003 (scope), then an audit-integrity check. | Live Run → "Run the red-team attack" |
| **Realistic hospital documents** | Toy PDFs make the demo look fake. | Generated hospital bills and discharge summaries with letterhead, registration numbers, barcode, QR code, stamp and itemised charges. The poisoned version carries invisible text. | Live Run → sample packs; `data/samples/` |
| **Harbor check after every claim** | A demo claim could look right while its audit trail doesn't back it up. | When a Live Run claim finishes, the backend writes a one-task Harbor dataset for that claim and runs it with the same adapter, verifier and no-Docker environment as S01–S10. It is read-only, so it makes no AI calls. Outcome: the expected result for a sample pack or seeded scenario, plus rules every claim must meet (T2 auto-pay limits, flagged documents never paid, a clause for every deduction). Governance: every step governed, medical text only touched by the permitted agents, the payout matches the audit trail, every denial names its rule, and the hash chain is intact. Results go to `claim_jobs/`, so the S01–S10 scoreboard is untouched. | Live Run → "Harbor verified this claim" card |
| **Harbor without Docker** | Harbor assumes containers, which aren't available everywhere. | A custom `BaseEnvironment` maps container paths to trial directories and runs a POSIX shell on the host (Git Bash on Windows). | `npm run eval` |
| **NeMo second opinion (NVIDIA NIM)** | A fixed marker list misses a novel injection phrasing. | Each document also goes to NVIDIA's `nemotron-3.5-content-safety` model. Its verdict is OR'd into the same flag, so it can only add a T3 flag, never clear one, and a failed call falls back to the marker list. A benchmark measures it: on this corpus it matched the marker list's recall but added 3 false positives on clinical text, recorded honestly in ADR-013. | Live Run → injection guardrail; `evals/guardrail_bench/report.md` |
| **Officer claim assistant** | An officer has to read every field to answer "why is this with me?" | An Agno agent with six read-only tools (overview, settlement, fraud signals, structured finding, bill, routing reasons). Every tool call is checked and audited by AGT; it is denied every action and restricted tool. Bank details, officer notes and document text are never in its data, and every ₹ amount in an answer is verified. | Officer → open a claim → "Ask about this claim" |

### The 16 policy rules enforced in code

| Rule | Denies |
|---|---|
| GOV-001 | Tool not in the agent's allowlist |
| GOV-002 | Per-request tool-call budget exceeded (circuit breaker) |
| GOV-003 | Scope not in the agent × collection matrix (token service) |
| **GOV-004** | Automated payout while compliance has frozen automated payouts (kill switch) |
| ID-001 | Identity assertion missing, bad signature, or older than 30 s |
| TRUST-001 | Agent trust score below the scope's threshold |
| PAY-001 | Payout amount ≠ assessed payable |
| PAY-002 | Payout account ≠ registered account |
| PAY-003 | Payout > ₹50,000 without officer approval |
| PAY-004 | Fraud-flagged claim without officer approval |
| PAY-005 | Second payout for the same claim |
| PAY-006 | Payout above the remaining sum insured |
| STATE-001 | Rejection without an officer decision record |
| STATE-002 | Approval or payment that skipped required steps |
| DATA-001 | Medical records requested by anyone except intake (write) or the medical reviewer (read) |
| DATA-002 | An account number in tool arguments that did not come from bank_details |

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

Fourteen ADRs are in [`adr/`](adr/): the ten from the build, plus ADR-011 (guardrails),
ADR-012 (payout kill switch), ADR-013 (NeMo second opinion) and ADR-014 (officer claim
assistant). The key ones:
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

| Area | Finding | What we did |
|---|---|---|
| Agno Teams | Every Team mode has an LLM leader deciding delegation. | Used a deterministic Agno Workflow instead: no leader calls, and no way for injected text to steer the order. |
| Agno Workflows | A failed step doesn't stop the run, which is still reported `completed` (verified in 3.0.11). | Every step fails closed; step retries are disabled. |
| Agno AgentOS | Telemetry defaults to on. AgentOS can wrap an existing FastAPI app. | Telemetry off everywhere; AgentOS wraps the API and keeps every existing route. |
| Microsoft AGT | 4.1 has no Agno integration. The FlightRecorder caches the chain head per process. | Custom adapter on AGT's core; a cross-process-safe recorder. |
| Phoenix | `register()` crashes against the current OTLP exporter. | Built the TracerProvider directly with the OpenTelemetry SDK. |
| OpenInference | Kept a second, unredacted copy of medical text in per-message attributes. | Role-aware redaction. |
| OpenTelemetry | Trace context was lost across services. | A parent span around each governed round trip gives one trace per claim. |
| Harbor | Assumes containers; shell and encoding differ on Windows. | Custom host environment, Git Bash, UTF-8 mode. |
| Groq | Allows 8,000 tokens/min, and a claim uses about 6,600. | Retries with backoff; Harbor runs scenarios one at a time. |
| Harbor, on the final code | Caught two intermittent bugs: the intake agent sometimes dropped the room rate from a label (so the room-rent cap applied only sometimes), and the model once emitted invalid JSON (`"confidence": 0. nine`). | The settlement engine derives the daily rate from the line total when the label lacks it; every agent's typed output is re-requested up to 3 times before failing closed. Regression tests for both. |
| Security review | `bank_details:read` had no row binding. | The gateway now resolves the token's claim to its policy first. |

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
