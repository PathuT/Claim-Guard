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

## Status: M0 — Skeleton ✅

The scaffolding milestone is complete and verified:

- Repo layout in place (`backend/`, `frontend/`, `evals/`, `data/`, `docs/`)
- Backend: Python 3.12 project managed with `uv`, Agno 3.0 installed
- Frontend: Next.js (App Router, TypeScript, Tailwind)
- Observability: Arize Phoenix wired via OpenInference; a smoke-test agent
  (`backend/agents/hello_agent.py`) has produced a real trace, confirmed via
  Phoenix's own API
- `npm run dev` starts Phoenix + frontend together from one command

Everything past this point (synthetic data, token service, data gateway, AGT
governance adapter, the six ClaimGuard agents, console, evals) is **not built yet** —
see [`docs/plan.md`](docs/plan.md) M1 onward.

---

## Stack

| Layer | Choice |
|---|---|
| Backend language | Python 3.12, managed with `uv` |
| Agent framework | [Agno](https://github.com/agno-agi/agno) (AgentOS runtime) |
| Governance | [Microsoft Agent Governance Toolkit](https://github.com/microsoft/agent-governance-toolkit) (public preview) — added in M3 |
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
npm run dev
```

Starts Phoenix (`http://localhost:6006`) and the frontend (`http://localhost:3005`)
together in one terminal.

To fire the smoke-test agent and confirm a trace appears in Phoenix, in a second
terminal (with `npm run dev` still running):

```bash
npm run dev:hello-agent
```

Then open `http://localhost:6006` and look for the `claimguard-hello-agent` project.

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
