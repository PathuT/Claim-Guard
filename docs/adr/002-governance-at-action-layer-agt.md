# ADR-002: Deterministic governance at the action layer with AGT

- **Status:** accepted

## Context
Prompt instructions ("never pay more than the assessed amount") can be overridden by
injected content. Claims documents are attacker-controlled input.

## Decision
Every tool call passes through an **AGT adapter** that evaluates policy in code before
execution, fails closed, returns structured denials, and writes a hash-chained audit entry.
Policy context (assessed payable, registered account, approval records) is fetched from
trusted stores, never taken from agent arguments.

## Alternatives considered
- **Prompt-level guardrails only** — probabilistic; cannot guarantee S06 is blocked.
- **Custom policy middleware** — possible, but reinvents policy language, audit, identity.
- **Output filtering (LLM judge)** — useful extra layer, still probabilistic.

## Consequences
- We write an Agno ↔ AGT adapter (integration approach recorded here once built).
- AGT is public preview: pin version; keep policies in files so they're portable.
- Enables the strongest demo: the model can be fooled and money still doesn't move.

## Integration approach (M3, recorded once built)

**Package:** `agent-governance-toolkit[full]` v4.1.0 on PyPI. No dedicated Agno
adapter exists (only LangChain, MCP, A2A, CrewAI, and similar are named
integrations) — we wired our own thin adapter against the framework-agnostic
core (`agent_control_plane`), exactly as this ADR anticipated. This is a
custom Agno ↔ AGT adapter, not a drop-in plugin.

**What we used, and why:**
- **`FlightRecorder`** (`agent_control_plane`) is the real audit trail —
  append-only, hash-chained (`previous_hash`/`entry_hash`), with
  `verify_integrity()` detecting post-hoc tampering. It already implements
  docs/CLAUDE.md invariant 10 correctly, so we did not reimplement
  hash-chaining ourselves; our custom `Audit` SQLAlchemy model from M1 is
  unused. FlightRecorder stores to its own local SQLite file, separate from
  the Supabase Postgres used for claims/policyholders/etc. — acceptable for
  now since nothing else needs to join audit rows with claim data yet; if
  M8's console needs that, a mirror/sync into Postgres is a follow-up, not a
  redesign.
- **`PolicyRule`/`PolicyEngine`** (`agent_control_plane`) has the right shape
  (`Callable[[ExecutionRequest], bool]` validators) but we implemented the
  GOV/PAY/STATE/DATA rules as plain Python predicates in `governance/rules.py`
  instead of registering them with `PolicyEngine` directly — the rules need
  richer denial reasons (a `rule_id` + human message) than a bare `bool`
  return, and our own `run_all_rules()` / `check_and_audit()` orchestration in
  `governance/adapter.py` gives us that without fighting the engine's return
  type. `ExecutionRequest`/`ActionType` weren't used for the same reason:
  `ActionType`'s fixed enum (`code_execution`, `file_read`, `api_call`, …) has
  no close match for "execute a payout" or "read medical records", so mapping
  onto it would have added indirection without adding safety.
- **`agentmesh.identity.SoftwareKeyStore`** provides real Ed25519
  `generate_keypair`/`sign`/`verify`, confirmed to be part of the current
  `agent-governance-toolkit-core` 4.1.0 distribution despite the `agentmesh`
  top-level import path itself being flagged deprecated (superseded by the
  consolidated package name, not by different code) — used for real AGT
  agent identities, replacing M2's shape-only stub. Each of the 6 agents gets
  a registered Ed25519 identity (`governance/identity.py`), and
  `auth/token_service.py`'s `verify_identity_assertion` now verifies a real
  signature (ID-001), not just checking shape/staleness.
- **Not used:** `agent_os` and `agentmesh` as top-level "batteries-included"
  runtimes are both explicitly deprecated in favor of the same
  `agent-governance-toolkit-core` package; we import specific working
  submodules from it (`agent_control_plane`, `agentmesh.identity`) rather
  than either deprecated top-level entry point.

**Bugs found and fixed while wiring this (both the same underlying class of
mistake — a fresh random key generated per process instead of a persisted
one):**
1. `TOKEN_SERVICE_PRIVATE_KEY` unset → token-service and gateway processes
   signed/verified with different random keys → every gateway call failed
   with `GATEWAY-BAD-SIGNATURE` even for a token that should have been valid.
2. Same issue one layer up: `governance/identity.py` generated a fresh random
   identity per agent per process → an agent process's signed assertion
   could never verify against the token service's own idea of that agent's
   public key. Fixed the same way: persisted seeds
   (`AGENT_IDENTITY_SEED_<AGENT>` in `.env`), loaded via
   `Ed25519PrivateKey.from_private_bytes()` and injected directly into
   `SoftwareKeyStore._keys` (its internal dict — the class has no public
   "import an existing key" method in v4.1.0; if a future version adds one,
   prefer it over reaching into the private attribute).

Both were caught only by testing the real cross-process HTTP flow end-to-end,
not by the in-process unit test suite (which runs everything in one process
and so never exercised the mismatch) — worth remembering for M4-M5 when the
six agents become real separate processes/services.
