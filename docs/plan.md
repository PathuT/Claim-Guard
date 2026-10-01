# ClaimGuard — Build Plan

Milestones M0–M9 delivered the brief; M10 lists the additions made afterwards. Each
milestone ended in something demoable. Where the build differed from the original plan,
the item says so.

If time is short, cut in this order: console polish (M8) → Harbor scenarios S09/S10 →
Phoenix dashboards. **Never cut** M2, M3, or S06/S07.

---

## M0 — Skeleton (0.5 day)

**Goal:** everything starts with one command and one traced agent call is visible.

- [x] Repo layout per `engineering-guide.md`, `uv` project, Next.js app scaffold
- [x] One command starts every service — built as `npm run dev` (`concurrently`) instead
  of Docker Compose; Postgres is hosted (Supabase)
- [x] Phoenix running; Agno instrumented; a hello agent produces a trace
- [x] `Makefile` targets exist (`up`, `down`, `test`, `lint`)

**Done when:** `make up` works and a trace appears in Phoenix.


## M1 — Synthetic data (1 day)

- [x] Generators for all collections per `use-case.md` §4.2
- [x] Priya and Rahul fixtures exactly as in the scenarios
- [x] PDF generator for bills and discharge summaries; 5 poisoned PDFs with hidden text
- [x] Plan terms loaded and embedded (pgvector)
- [x] `make seed` is idempotent

**Done when:** seeded DB matches the spec; S01 and S06 documents render correctly.

## M2 — Token service + data gateway (1.5 days) — security core

- [x] Token service: issue, JWKS, revoke by `jti` and by `req_id`
- [x] Identity assertion check (stub signer now; real AGT identity wired in M3)
- [x] Gateway: full validation checklist (`security-matrix.md` §6), field allowlists, row binding, pseudonymisation
- [x] Spans `token.issue` and `gateway.access`
- [x] Tests first: expired, wrong audience, wrong scope, wrong claim, revoked, replay, allowlist leakage

**Done when:** `make test-security` passes with no agents involved.

## M3 — AGT adapter + policies + audit (1.5 days) — governance core

- [x] Read AGT docs for the pinned version; record integration approach in ADR-002
- [x] Adapter hooking every Agno tool call; context fetched from trusted stores
- [x] Rules GOV-001..003, PAY-001..006, STATE-001..002, DATA-001..002
- [x] AGT agent identities registered; token service verifies real AGT signatures (ID-001)
- [x] Trust-score gating per `security-matrix.md` §11 (TRUST-001)
- [ ] Ring mapping (RING-001) — documented in ADR-010 but not enforced in code; GOV-001
  (tool allowlist) and GOV-002 (call budget) cover the same ground today
- [x] Hash-chained audit writer + integrity check
- [x] Structured denials returned to agents; `governance.decision` spans
- [x] Tests for every rule, allow and deny cases

**Done when:** every rule has a passing positive and negative test.

## M4 — Intake, medical reviewer, coverage (1.5 days)

- [x] Agents with typed response models; routing by a deterministic Agno Workflow
  rather than a Team (ADR-001)
- [x] Documents passed as delimited untrusted data
- [x] Medical finding and coverage assessment schemas enforced
- [x] Settlement calculation per plan terms, every deduction with `clause_id`

**Done when:** S01 produces the correct ₹37,300 assessment (payout still stubbed).

## M5 — Fraud, payout, tiers, human-in-the-loop (1 day)

- [x] Fraud agent on pseudonymised data + hospital watchlist
- [x] Payout via payments mock through AGT
- [x] Tier logic and claim state machine (`architecture.md` §8)
- [x] Officer decision API; token revocation at terminal / `pending_human` states

**Done when:** S01 pays automatically; S02 and S03 stop at `pending_human`; S06 is never paid.

## M6 — Observability deepening (0.5 day)

- [x] One trace per `req_id` across all services (context propagation)
- [x] Redaction processor + test (no medical text or account numbers in spans)
- [x] Phoenix views: denials by rule, tokens by agent, cost/latency per claim

**Done when:** S06's trace shows the injection attempt, the denial, and no sensitive data.

## M7 — Harbor evals (1.5 days)

- [x] Decide environment isolation approach from Harbor docs; record in ADR-006
- [x] Custom Harbor agent adapter calling AgentOS API (with scripted officer decisions)
- [x] Tasks S01–S10, each verifying outcome **and** governance evidence
- [x] Scoreboard output; `make eval`

**Done when:** `make eval` runs all 10 and reports both pass rates.

## M8 — Console (1 day)

- [x] Policyholder: submit claim, view status + breakdown
- [x] Officer: T3 queue with findings, flags, clauses; audited break-glass (shows its
  audit trace id)
- [x] Compliance: audit log viewer, denials, medical-data access report

**Done when:** the full S01 and S02 journeys work from the browser.

## M9 — Compliance report, docs, demo (1 day)

- [x] `make compliance-report` per `compliance-mapping.md` §4
- [x] ADRs reviewed and complete
- [x] README with architecture diagram, setup, demo script
- [x] Demo script: S01 happy path → S06 injection blocked → S07 scope denial → S02 officer approval → compliance report

**Done when:** a fresh clone reaches a working demo with `make up && make seed && make eval`.

## M10 — Additions after the brief

- [x] NeMo / NVIDIA NIM content-safety model as an advisory second opinion on the
  injection guardrail, OR-only, fails open, off by default (ADR-013)
- [x] Guardrail benchmark: marker list vs NeMo vs combined, precision/recall/F1
  (`evals/guardrail_bench/`)
- [x] Officer claim assistant: an Agno agent with six read-only, AGT-governed tools,
  scoped to one claim, every ₹ amount checked (ADR-014)
