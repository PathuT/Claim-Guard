# ADR-001: Agno as the agent framework

- **Status:** accepted

## Context
We need multi-agent orchestration (supervisor + specialists), typed outputs, tool hooks
to insert governance, and a runtime to serve agents over an API.

## Decision
Use **Agno**: teams for supervisor/specialist routing, Pydantic response models for
typed findings, tool hooks as the interception point for AGT, AgentOS as the runtime.

## Alternatives considered
- **LangGraph** — explicit graph control, but more boilerplate; our flow is simple routing.
- **CrewAI** — has native AGT integration, but the assignment specifies Agno.
- **Microsoft Agent Framework** — best-documented AGT pairing, but not the chosen stack.

## Consequences
- No native AGT integration for Agno: we build and own the adapter (ADR-002).
- Agno evolves quickly; pin the version and verify APIs against its docs.
