# ClaimGuard

A multi-agent system that processes health insurance **reimbursement claims** end to
end — reading hospital documents, medical review, coverage assessment, fraud
screening, and payout. The insurance logic is intentionally simple; the real subject
of this project is **governance, compliance, and observability for autonomous agents**
that handle medical data and money.

All data is synthetic. No real people, hospitals, medical records, or payments. Ever.

See [`docs/CLAUDE.md`](docs/CLAUDE.md) for the full project brief, invariants, and
architecture, and [`docs/plan.md`](docs/plan.md) for the milestone plan this repo is
built against.

---

## Status: M0-M8 done ✅ (M9 next)

**M0 — Skeleton:** repo layout, `uv` backend (Agno 3.0), Next.js frontend, Phoenix +
OpenInference wired and verified with a real traced agent call.

**M1 — Synthetic data:** all 9 collections seeded to Supabase Postgres (60
policyholders incl. Priya/Rahul's exact fixtures, 409 claims, 25 hospitals w/
3 watchlisted, 28 policy-term clauses embedded via Gemini into pgvector). 13
generated PDF documents, **5 confirmed poisoned** with extractable-but-invisible
(white-on-white) prompt-injection text for the S06 scenario. `make seed` is
idempotent (verified with repeated runs).

**M2 — Token service + data gateway (security core):** both running as real
FastAPI services.
- Token service (`backend/auth/`): issues short-lived, single-scope, EdDSA
  (Ed25519)-signed JWTs per `docs/security-matrix.md` §5; enforces the agent×scope
  matrix (GOV-003), trust-score gating (TRUST-001), and delegation-never-widens;
  revokes by `jti` and by `req_id`; publishes JWKS.
- Data gateway (`backend/data_gateway/`): the only code that queries Postgres;
  runs the full 7-step validation checklist from §6 (signature, audience/issuer,
  expiry with 5s clock skew, revocation, scope match, row binding, field-allowlist
  filtering) before returning any row.
- Verified end-to-end over real HTTP against live Supabase data, not just unit tests.

**M3 — AGT adapter + policies + audit (governance core):** built on the real
`agent-governance-toolkit` SDK (v4.1.0) — no Agno-specific integration exists
in the SDK, so `backend/governance/` is a custom adapter against its
framework-agnostic core, per ADR-002.
- `governance/adapter.py`: every agent tool call goes through
  `check_and_audit()` — GOV-001 (tool allowlist), GOV-002 (40-call circuit
  breaker), then all PAY-001..006 / STATE-001..002 / DATA-001..002 rules
  (`governance/rules.py`) — before an audit entry is written and the call is
  allowed or denied.
- Audit trail is AGT's own `FlightRecorder`: append-only, hash-chained,
  `verify_integrity()` detects tampering — used as-is rather than
  reimplemented.
- Real per-agent Ed25519 identities (`governance/identity.py`, via
  `agentmesh.identity.SoftwareKeyStore`) replace M2's shape-only ID-001 stub;
  `auth/token_service.py` now verifies a real signature, not just staleness.
- `make test-security` passes **70/70** tests with no agents involved — the
  M2 *and* M3 "done when" conditions — covering every rule's allow and deny
  case, plus the full token/gateway checklist from M2.

**M4 — Intake, medical reviewer, coverage:** the first 3 real ClaimGuard
agents, built with Agno (`backend/agents/`).
- `intake.py` / `medical_reviewer.py`: typed Agno agents (`output_schema`)
  matching the MedicalFinding contract in `docs/architecture.md` §9 exactly.
  Document text is delimited and labelled untrusted, passed in the user
  message only — never merged into the system prompt (invariant 8); verified
  resistant to S06's actual injection payload across repeated live runs.
- `settlement.py`: the payable-amount arithmetic is deterministic Python, not
  LLM reasoning (docs/architecture.md §2), so every deduction's `clause_id`
  and amount is guaranteed correct, not just plausible.
- `supervisor.py`: a plain Python orchestrator, not an Agno `Team` — every
  real `TeamMode` (coordinate/route/broadcast/tasks, confirmed by reading
  Agno's own source) has an LLM leader deciding delegation, which is the
  wrong fit for the fixed intake→medical_reviewer→coverage sequence
  `docs/architecture.md` §7 specifies.
- **Verified against real S01 documents end-to-end through the actual
  supervisor: produces exactly ₹37,300 payable**, matching M4's "done when"
  condition precisely, not approximately.

**M5 — Fraud, payout, tiers, human-in-the-loop:** the two remaining agents
(`fraud`, `payout`) join the supervisor, and this is where the security core
(M2/M3) gets exercised by real agents for the first time — not just unit
tests. New: `governance/client.py` (the real chain: `check_and_audit()` →
signed identity assertion → token service HTTP → data gateway HTTP), a
`POST /write` gateway endpoint for the three `*:write` scopes, real HMAC
pseudonymisation (`data_gateway/pseudonymise.py`) for `claims:read_pseudonymised`,
a claim state machine (`api/state_machine.py`) matching
`docs/architecture.md` §8 exactly, and an officer decision API (`api/officer.py`).
- `fraud.py`: screens pseudonymised claims + the hospital watchlist through
  the real gateway. Pre-filters the 409-row claim set down to evidence rows
  in plain Python before it ever reaches the LLM (raw-dumping all rows hit
  Groq's per-request token limit, and would have violated data-minimisation
  regardless) — verified live: S01 comes back clean, S04's duplicate-bill
  and S10's watchlisted-hospital flags both fire with correct evidence_refs.
- `payout.py`: plain Python, not an Agno agent (same "enforcement is
  deterministic code" reasoning as `settlement.py`) — `execute_payout` goes
  through PAY-001..006 with `trusted` values pulled from Postgres, never
  from the call's own args. **S06 verified live end-to-end, three ways**:
  wrong amount, wrong account, and both — all three denied by name
  (PAY-001/PAY-002), and the full supervisor run (real LLM reading the
  actual poisoned PDF) never even attempted the injected ₹4,50,000 in the
  first place.
- Found and fixed a real gap while wiring payout: `bank_details:read` had no
  row binding at all (it has no `claim_id` column, so the gateway's binding
  check silently skipped it) — any claim-scoped token could read every
  policyholder's bank details. Fixed in `data_gateway/gateway.py`/`app.py`
  by resolving the token's claim to its policy_number before comparing.
- Found and fixed a real M1 seed-data bug while testing S03: its claim was
  attached to Priya's 14-month-old policy instead of Rahul's 20-day-old one
  (the policy the "20 days ago" scenario narrative actually describes), so
  it paid automatically instead of stopping at `pending_human`. Corrected
  in `data/synthetic/generators/claims.py` and `docs/use-case.md`.
- **All three of M5's "done when" conditions verified live, end to end,
  through the real supervisor**: S01 pays automatically (₹37,300, T2); S02
  (₹71,000 room-rent-excess case) and S03 (waiting-period case) both stop
  at `pending_human`; S06 is never paid, in any variation tried.
- Officer decision API (`api/officer.py`): `pending_human → approved/
  approved_partial/rejected`, itself a real governed `set_claim_state` call
  so STATE-001 applies identically — a rejection with no officer decision
  record is denied the same way whether it comes from the API or a direct
  call. An approval supplies PAY-003/004's officer_approval_id and then
  calls payout for real. Tested live: an approved S02 pays through the
  officer path; a rejected S03 records the decision with no payout attempt.
- Token revocation wired into the state machine itself: entering `paid`,
  `rejected`, or `pending_human` revokes every token issued for that
  `req_id` (security-matrix.md §4), not left as an unused function.
- `make test-security` still passes **70/70** (unaffected by M5); the real
  audit trail (`FlightRecorder`) was inspected directly and its hash chain
  verified intact across every allow/deny decision made while testing M5.

**M6 — Observability deepening:** one real trace per claim across every
service, redaction that actually runs before export (not just span-side
attribute hygiene), and documented Phoenix views.
- **Context propagation** (`observability/tracing.py`, `governance/
  client.py`): manual W3C `traceparent` inject/extract via plain
  `opentelemetry.propagate` — no auto-instrumentation libraries, matching
  docs/CLAUDE.md's own stack line ("custom OTel spans," not
  auto-instrumented httpx/FastAPI). `governance/client.py`'s `call_tool()`
  now wraps its whole HTTP round-trip (governance check + token issuance +
  gateway call) in one `tool.call` span so it stays open long enough to
  actually be the parent of the calls it makes — found live that the
  original `governance.decision` span alone had already closed by the time
  the HTTP calls ran, so propagation code that was itself correct still
  produced disconnected traces.
- **Verified live, not asserted**: a full S01 claim flow produces **one
  shared `trace_id`** across the supervisor process, the token service, and
  the data gateway — 23 spans (Agno agent runs, `governance.decision`,
  `token.issue`, `gateway.access`, `tool.call`) all under one trace, checked
  directly against Phoenix's own stored spans, not just logged and assumed.
- **Redaction processor** (`observability/redaction.py`), registered first
  in the export pipeline (before spans ever reach Phoenix's exporter):
  medical free text → `[REDACTED:medical]`, account numbers → last 4
  digits, the two fixed persona names → stable pseudonyms. Found and fixed
  a real leak while verifying live: OpenInference's per-message LLM
  attributes (`llm.input_messages.<N>.message.content`) carried a second,
  unredacted copy of the same raw diagnosis/discharge text that
  `input.value`/`output.value` were already correctly redacting — fixed
  with a role-aware rule (system prompts stay readable; user/assistant
  content is redacted) rather than blanket-hiding every LLM message.
- **M6's own "done when" verified live in one real trace**: S06 run through
  the actual supervisor (real LLM reading the real poisoned PDF) plus the
  adversarial ₹4,50,000/unregistered-account payout attempt in the same
  trace — the PAY-001 denial is visible, and a direct search of every
  span's attributes in that trace turns up zero instances of the raw
  injected payload text, the unregistered account number, or the real name.
- Also found and fixed, incidentally: a genuine version-skew bug in
  `arize-phoenix-otel` (latest release, 0.17.1) against the current
  `arize-phoenix` — its `register()` convenience function unconditionally
  crashes on a renamed internal attribute. Worked around by building the
  `TracerProvider`/exporter directly from `opentelemetry-sdk` instead of
  through the broken wrapper — confirmed byte-for-byte equivalent Phoenix
  project placement via its own `/v1/projects` API.
- Phoenix views documented with real, tested filter expressions (not
  guessed syntax) in
  [`docs/observability-dashboards.md`](docs/observability-dashboards.md):
  denials by rule, token issuance by agent, latency per agent, cost per
  claim.

**M7 — Harbor evals:** 10 scenario tasks (S01-S10, `evals/harbor/tasks/`), each with
its own `instruction.md`/`task.toml`, a custom `BaseAgent` adapter that calls the real
AgentOS API, and a custom `BaseVerifier` that checks the real claim outcome/audit
trail against the scenario's expectations.
- **No Docker.** Harbor's own environment abstraction defaults to spinning up a
  container per task, but this project runs every task straight on the host instead,
  via a from-scratch `BaseEnvironment` subclass
  (`evals/harbor/environment_backend/local_host.py`) that maps Harbor's hardcoded
  container-path conventions (`/logs/agent`, `/logs/verifier`, ...) onto the real local
  per-trial directories Harbor itself already creates. Selected with
  `--env environment_backend.local_host:LocalHostEnvironment`.
- Verified live: `harbor run` against the real dev stack (`npm run dev` already
  running), zero Docker daemon involved, real outcome/governance scores.

**M8 — Console (Next.js frontend):** four real pages — Policyholder, Officer,
Compliance, and an Agent Pipeline view — plus a full design-system pass (OKLCH
tokens, light/dark mode) matching a specified reference look exactly.
- **Real document upload is the actual entrypoint**, not a pre-seeded `claim_id`
  replay: `POST /claims/new` (`backend/api/claim_intake.py`) takes two real PDF
  files from the browser, extracts their text with real `pypdf` (the same
  extraction the seed generator itself uses, applied to genuinely unseen files),
  hashes them, and creates a real `Claim` row — then the Console automatically
  submits that claim for assessment through the unchanged 5-agent pipeline.
  Verified end-to-end with freshly generated, non-seed PDFs.
- The demo-scenario buttons on the Policyholder page and the quick-load chips on
  the Pipeline page both replay real, already-seeded S01-S10 claims for anyone who
  wants to see a specific agent/governance behaviour without uploading their own
  documents.
- Pipeline page shows all 5 agents' real stored outputs for one claim side by side
  (intake summary, medical finding, coverage deductions, fraud flags, payout
  state), with an `AuditBadge` that's honest about which agents make governed,
  audited tool calls (supervisor, payout) versus which do real work that isn't
  itself gateway-audited (intake, medical reviewer, coverage, fraud).
- Officer page includes the audited break-glass discharge-summary flow
  (security-matrix.md §9) as a distinct, separately-logged path from the normal
  medical_reviewer-only restriction.

Everything past this point (tiers/scoping polish, remaining M9 work) is
**not built yet** — see [`docs/plan.md`](docs/plan.md) M9 onward.

---

## Stack

| Layer | Choice |
|---|---|
| Backend language | Python 3.12, managed with `uv` |
| Agent framework | [Agno](https://github.com/agno-agi/agno) (AgentOS runtime) |
| Governance | [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit) v4.1.0 (public preview) |
| Auth | PyJWT, EdDSA (Ed25519) — added in M2 |
| Database | Postgres 16 + pgvector, hosted on Supabase |
| Observability | Arize Phoenix (local) + OpenInference instrumentation |
| Evals | [Harbor](https://github.com/laude-institute/harbor) — added in M7 |
| Frontend | Next.js (App Router, TypeScript) |
| LLM provider | Model-agnostic via Agno; this repo defaults to Groq (`MODEL_PROVIDER=groq`), Gemini and Anthropic also supported |

**No Docker — including for evals.** Every service runs as a native local process,
and Harbor's own eval runs do too, via a custom `BaseEnvironment` that runs directly
on the host instead of in a container (see [`docs/adr/006-evaluation-harbor.md`](docs/adr/006-evaluation-harbor.md)
for the full history — Docker was tried first and deliberately dropped). Postgres is
hosted (Supabase) rather than run locally.

---

## Running it locally

### Prerequisites

- Python 3.12+ and [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+
- A Supabase (or any Postgres 16 + pgvector) database — needed from M1 onward, not for M0
- An API key for at least one LLM provider (Groq, Gemini, or Anthropic)

### Setup

```bash
cp .env.example .env        # then fill in your DATABASE_URL and an LLM API key
npm install                 # root: installs `concurrently` for dev orchestration
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..
cd evals/harbor && uv sync && cd ../..   # only needed for `make eval` — separate uv project, M7
```

### Run

```bash
make seed   # populates Supabase with synthetic data (idempotent, safe to re-run)
npm run dev # or `make up` — same thing
```

Starts Phoenix (`:6006`), the frontend/Console (`:3005`), the token service
(`:8100`), the data gateway (`:8200`), AgentOS (`:8000`), and the officer decision
API (`:8400`) together in one terminal.

Open `http://localhost:3005` for the Console — start at `/policyholder` to submit
a real claim (upload your own PDFs, or use one of the demo-scenario buttons to
replay a seeded S01-S10 case), then follow it through `/pipeline`, `/officer`
(for claims that stop at human review), and `/compliance`.

### Presenting it

- `http://localhost:3005/architecture`: the brief compared with what was built,
  system and request-flow diagrams, the security model, design decisions, what was
  learned about each framework, and a demo tour.
- `http://localhost:3005/live`: a live, narrated claim run. Upload real PDFs (or a
  sample pack) and watch every backend operation stream in: agent runs, LLM calls,
  governance allow/deny, token issuance, gateway checks, state changes and spans. It
  also has a requirements-proof panel, a red-team replay of the S06 injection, and the
  Harbor scoreboard.
- `npm run eval`: runs the Harbor suite (S01–S10) without Docker, from any shell.
- [`docs/demo-script.md`](docs/demo-script.md): the presenter walkthrough.

To fire the smoke-test agent and confirm a trace appears in Phoenix, in a second
terminal (with `npm run dev` still running):

```bash
npm run dev:hello-agent
```

Then open `http://localhost:6006` and look for the `claimguard-hello-agent` project.

Run the security test suite (no live services needed):

```bash
make test-security
```

Run the Harbor eval suite (needs `npm run dev`'s stack already running — no Docker):

```bash
npm run eval                                          # all 10 scenarios
cd evals/harbor && uv run python run_evals.py S01 S06 # just these
```

Scenarios run one at a time: they all drive the same local stack and the same
rate-limited LLM key. `run_evals.py` works from bash, cmd and PowerShell.

---

## Repo layout

```
backend/
  agents/          # Agno agent + team definitions, prompts
  governance/       # AGT adapter, policies/ (YAML/Rego), audit chain
  auth/            # token service (issue, validate, revoke)
  data_gateway/    # the only code that touches Postgres
  payments_mock/   # records intended payouts
  observability/   # OTel setup, custom span helpers, redaction
  api/             # AgentOS app, officer decision endpoints for the console
  tests/
evals/harbor/
  adapter/         # Harbor agent adapter that calls our AgentOS API
  tasks/           # one folder per scenario S01-S10
frontend/          # Next.js console
data/synthetic/    # generators, seed data, sample PDFs (incl. poisoned ones)
docs/              # project brief, architecture, security matrix, ADRs, plan
```

## Docs

- [`docs/use-case.md`](docs/use-case.md) — story, personas, plan terms, scenarios S01-S10
- [`docs/architecture.md`](docs/architecture.md) — full architecture and data flow
- [`docs/security-matrix.md`](docs/security-matrix.md) — agent × collection × scope × TTL (source of truth for access)
- [`docs/compliance-mapping.md`](docs/compliance-mapping.md) — DPDP / IRDAI expectations → controls → tests
- [`docs/plan.md`](docs/plan.md) — milestones and acceptance criteria
- [`docs/adr/`](docs/adr/) — architecture decision records
