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
