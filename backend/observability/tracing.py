"""OTel/Phoenix wiring shared by every ClaimGuard service.

Call `setup_tracing(service_name)` once, at process start, before any Agno
agent or FastAPI app is created. It points the OpenTelemetry SDK at the local
Phoenix collector and turns on OpenInference auto-instrumentation for Agno,
so every `agent.run(...)` call produces spans Phoenix can show as a trace.

M0 scope: this is the plumbing needed for "one traced agent call is visible
in Phoenix" (docs/plan.md M0). Redaction (docs/architecture.md §11) and the
custom `governance.decision` / `token.issue` / `gateway.access` spans are
added in later milestones (M3, M6) — not here.
"""

from __future__ import annotations

import os

from openinference.instrumentation.agno import AgnoInstrumentor
from phoenix.otel import register


def setup_tracing(service_name: str):
    """Register a Phoenix-bound tracer provider and instrument Agno.

    Reads PHOENIX_COLLECTOR_ENDPOINT from the environment (see .env.example).
    Safe to call once per process; call before constructing any Agent.
    """
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")

    tracer_provider = register(
        endpoint=f"{endpoint}/v1/traces",
        project_name=service_name,
        auto_instrument=False,
    )

    AgnoInstrumentor().instrument(tracer_provider=tracer_provider)

    return tracer_provider
