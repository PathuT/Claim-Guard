# ADR-005: Arize Phoenix for observability

- **Status:** accepted

## Context
We need one trace that explains an entire claim: LLM calls, governance decisions, token
issuance, and data access, while never exposing medical text.

## Decision
Self-hosted **Arize Phoenix** with OpenTelemetry. OpenInference instrumentation for
Agno; custom spans for governance, tokens, gateway, payouts, human decisions. A redaction
processor runs before export.

## Alternatives considered
- **Langfuse** — strong option, similar capability; Phoenix chosen for OTel-native design and self-hosting simplicity.
- **LangSmith** — tight LangChain coupling, hosted by default.
- **Plain OTel + Jaeger** — no LLM-aware views or evals.

## Consequences
OTel standard means spans are portable to other backends. Redaction must be tested.
