# ADR-009: Next.js console, no separate Node backend

- **Status:** accepted

## Context
The backend (agents, governance, gateway) is Python. We need a UI for three roles.

## Decision
**Next.js (TypeScript)** for the console, calling AgentOS APIs directly. No NestJS layer.

## Alternatives considered
- **NestJS BFF** — adds a second backend runtime and another trust boundary for no gain.
- **Streamlit** — fast, but weaker for role-based multi-page UX.

## Consequences
Fewer moving parts; auth/RBAC lives in the AgentOS API.
