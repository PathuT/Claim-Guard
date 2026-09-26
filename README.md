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

## Status: M0-M3 done ✅ (M4 next)

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

Everything past this point (the six ClaimGuard agents, console, evals) is
**not built yet** — see [`docs/plan.md`](docs/plan.md) M4 onward.

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

**No Docker.** Every service runs as a native local process (see
[`docs/adr/`](docs/adr/) for the reasoning if this changes). Postgres is hosted
(Supabase) rather than run locally.

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
```

### Run

```bash
make seed   # populates Supabase with synthetic data (idempotent, safe to re-run)
npm run dev # or `make up` — same thing
```

Starts Phoenix (`:6006`), the frontend (`:3005`), the token service (`:8100`), and
the data gateway (`:8200`) together in one terminal.

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
