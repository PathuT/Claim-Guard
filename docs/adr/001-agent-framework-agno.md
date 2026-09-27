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

## Revision: orchestration with an Agno Workflow, served by Agno AgentOS

The original decision planned Agno *Teams* for supervisor routing. While building we
read `agno/team/mode.py`: every Team mode (coordinate, route, broadcast, tasks) has an
LLM leader that decides which member runs next. That doesn't fit a fixed, audited claim
flow, for three reasons:
- it adds an LLM call on every delegation, which costs money and latency and uses up
  the provider's token rate limit;
- the order of the steps (for example, "fraud screening always runs before payout")
  would be decided by a model that reads attacker-controlled documents;
- the order could not be reproduced exactly from run to run.

**Decision:** the pipeline is an `agno.workflow.Workflow`
(`agents/supervisor.py`, id `claim-assessment`). It has deterministic `Step`s (intake,
medical_review, settlement, coverage_explanation, fraud_screen, tier_decision) and a
`Condition` for the money branch: T2 goes to `governed_payout`, T3 goes to
`route_to_officer`. Each LLM step runs a real Agno Agent. Settlement, tiering and
payout are plain code. No tokens are spent on orchestration.

The API is served by Agno's `AgentOS`, wrapping the existing FastAPI app
(`base_app`, `on_route_conflict="preserve_base_app"`). Every existing route is kept,
and AgentOS adds `/config`, `/agents` and `/workflows`.

Findings from verifying this against agno 3.0.11, and what we did about each:
- **A failed step doesn't stop the run.** When a step raises, Agno logs a warning,
  runs the remaining steps and reports the run `completed`. So every step is wrapped
  to fail closed: the error is recorded and `StepOutput(stop=True)` halts the run.
  Step retries are disabled (`max_retries=0`), so a governed payout is never silently
  re-attempted. LLM rate limits are retried at the model layer instead
  (`agents/model_config.py`).
- **Telemetry is on by default.** Agents, Workflows and AgentOS all default to
  `telemetry=True`. It is set to `False` everywhere.
- **Workflow input is untrusted.** Trusted context (the policy, the registered
  account, the remaining sum insured) is passed in `additional_data`, assembled by the
  API from Postgres. A run started through AgentOS's own `/workflows/.../runs`
  endpoint has no trusted context, so it refuses at the first step.
