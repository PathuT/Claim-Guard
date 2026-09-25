# ClaimGuard — Build Plan

About **11 working days** with Claude Code. Each milestone ends in something demoable.
Work one milestone per session. Start each in plan mode with the prompt given.

If time is short, cut in this order: console polish (M8) → Harbor scenarios S09/S10 →
Phoenix dashboards. **Never cut** M2, M3, or S06/S07.

---

## M0 — Skeleton (0.5 day)

**Goal:** everything starts with one command and one traced agent call is visible.

- [ ] Repo layout per `CLAUDE.md`, `uv` project, Next.js app scaffold
- [ ] `docker-compose.yml` with all services from `architecture.md` §13 (stubs OK)
- [ ] Phoenix running; Agno instrumented; a hello agent produces a trace
- [ ] `Makefile` targets exist (`up`, `down`, `test`, `lint`)

**Done when:** `make up` works and a trace appears in Phoenix.

> Prompt: *"Read CLAUDE.md and docs/architecture.md. Plan M0 from docs/plan.md. Check the installed Agno and Phoenix instrumentation docs before writing code."*

## M1 — Synthetic data (1 day)

- [ ] Generators for all collections per `use-case.md` §4.2
- [ ] Priya and Rahul fixtures exactly as in the scenarios
- [ ] PDF generator for bills and discharge summaries; 5 poisoned PDFs with hidden text
- [ ] Plan terms loaded and embedded (pgvector)
- [ ] `make seed` is idempotent

**Done when:** seeded DB matches the spec; S01 and S06 documents render correctly.

## M2 — Token service + data gateway (1.5 days) — security core

- [ ] Token service: issue, JWKS, revoke by `jti` and by `req_id`
- [ ] Identity assertion check (stub signer now; real AGT identity wired in M3)
- [ ] Gateway: full validation checklist (`security-matrix.md` §6), field allowlists, row binding, pseudonymisation
- [ ] Spans `token.issue` and `gateway.access`
- [ ] Tests first: expired, wrong audience, wrong scope, wrong claim, revoked, replay, allowlist leakage

**Done when:** `make test-security` passes with no agents involved.

## M3 — AGT adapter + policies + audit (1.5 days) — governance core

- [ ] Read AGT docs for the pinned version; record integration approach in ADR-002
- [ ] Adapter hooking every Agno tool call; context fetched from trusted stores
- [ ] Rules GOV-001..003, PAY-001..006, STATE-001..002, DATA-001..002
- [ ] AGT agent identities registered; token service verifies real AGT signatures (ID-001)
- [ ] Trust-score gating per `security-matrix.md` §11 (TRUST-001) and ring mapping (RING-001)
- [ ] Hash-chained audit writer + integrity check
- [ ] Structured denials returned to agents; `governance.decision` spans
- [ ] Tests for every rule, allow and deny cases

**Done when:** every rule has a passing positive and negative test.

## M4 — Intake, medical reviewer, coverage (1.5 days)

- [ ] Agents with typed response models; supervisor team routing
- [ ] Documents passed as delimited untrusted data
- [ ] Medical finding and coverage assessment schemas enforced
- [ ] Settlement calculation per plan terms, every deduction with `clause_id`

**Done when:** S01 produces the correct ₹37,300 assessment (payout still stubbed).

## M5 — Fraud, payout, tiers, human-in-the-loop (1 day)

- [ ] Fraud agent on pseudonymised data + hospital watchlist
- [ ] Payout via payments mock through AGT
- [ ] Tier logic and claim state machine (`architecture.md` §8)
- [ ] Officer decision API; token revocation at terminal / `pending_human` states

**Done when:** S01 pays automatically; S02 and S03 stop at `pending_human`; S06 is never paid.

## M6 — Observability deepening (0.5 day)

- [ ] One trace per `req_id` across all services (context propagation)
- [ ] Redaction processor + test (no medical text or account numbers in spans)
- [ ] Phoenix views: denials by rule, tokens by agent, cost/latency per claim

**Done when:** S06's trace shows the injection attempt, the denial, and no sensitive data.

## M7 — Harbor evals (1.5 days)

- [ ] Decide environment isolation approach from Harbor docs; record in ADR-006
- [ ] Custom Harbor agent adapter calling AgentOS API (with scripted officer decisions)
- [ ] Tasks S01–S10, each verifying outcome **and** governance evidence
- [ ] Scoreboard output; `make eval`

**Done when:** `make eval` runs all 10 and reports both pass rates.

## M8 — Console (1 day)

- [ ] Policyholder: submit claim, view status + breakdown
- [ ] Officer: T3 queue with findings, flags, clauses, trace link; audited break-glass
- [ ] Compliance: audit log viewer, denials, medical-data access report

**Done when:** the full S01 and S02 journeys work from the browser.

## M9 — Compliance report, docs, demo (1 day)

- [ ] `make compliance-report` per `compliance-mapping.md` §4
- [ ] ADRs reviewed and complete
- [ ] README with architecture diagram, setup, demo script
- [ ] Demo script: S01 happy path → S06 injection blocked → S07 scope denial → S02 officer approval → compliance report

**Done when:** a fresh clone reaches a working demo with `make up && make seed && make eval`.
