"""OTel/Phoenix wiring shared by every ClaimGuard service.

Call `setup_tracing(service_name)` once, at process start, before any Agno
agent or FastAPI app is created. It points the OpenTelemetry SDK at the local
Phoenix collector and turns on OpenInference auto-instrumentation for Agno,
so every `agent.run(...)` call produces spans Phoenix can show as a trace.

M0 scope was the plumbing needed for "one traced agent call is visible in
Phoenix" (docs/plan.md M0). M6 adds real W3C trace-context propagation
(docs/plan.md M6: "One trace per req_id across all services (context
propagation)") — before this, every process started its own independent
trace with no shared trace_id, so "one trace per req_id" was only true of
the audit log (FlightRecorder's own trace_id), not of Phoenix.

docs/engineering-guide.md's own stack line is explicit: "OpenInference instrumentation
for Agno, plus custom OTel spans for governance, token, and gateway events"
— this project's spans are hand-rolled, not produced by generic
auto-instrumentation libraries wrapping httpx/FastAPI. Propagation here
follows the same discipline: plain `opentelemetry.propagate`
inject/extract calls (part of the SDK already installed, no new
dependency), used explicitly at the two places that need it —
governance/client.py injects a `traceparent` header before every httpx call
it makes; each FastAPI app's own request handler extracts it before
starting its own span as a child of that context — rather than an
instrumentation library doing this invisibly for every request/response.

Also registers `RedactionSpanProcessor` (docs/architecture.md §11) as the
FIRST span processor added to the tracer provider, before the exporting
processor — a `SynchronousMultiSpanProcessor` (OTel's internal fan-out) runs
its processors' `on_end()` in registration order, so redaction has to be
added before the exporter or it would run AFTER export, i.e. never actually
redact what Phoenix stores.

M6 also moves `setup_tracing()` off `phoenix.otel.register()`'s convenience
wrapper and onto the plain `opentelemetry-sdk` + `opentelemetry-exporter-
otlp-proto-http` classes directly. Found live while wiring redaction:
`register()` unconditionally calls an internal `_tracing_details()` that
reads `exporter._headers`, an attribute `opentelemetry-exporter-otlp-proto-
http`'s current release (1.45.0) no longer has — a real version-skew bug in
`arize-phoenix-otel==0.17.1` (the latest release on PyPI; there is no newer
fix to move to), reproduced with a bare `register()` call and no code from
this project involved. The plain-SDK construction below produces an
identical result — confirmed by checking Phoenix's own `/v1/projects` API,
which shows a manually-built provider's spans landing under the right
project name exactly like `register()`'s own output — while sidestepping
the broken method entirely.
"""

from __future__ import annotations

import os

from openinference.instrumentation.agno import AgnoInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from .live_events import LiveEventSpanProcessor
from .redaction import RedactionSpanProcessor

# The resource attribute key phoenix.otel.register() itself uses to bucket
# spans into a named Phoenix project — matched here so a manually-built
# provider's spans land in the same place register()'s would have.
_PHOENIX_PROJECT_RESOURCE_KEY = "openinference.project.name"


def setup_tracing(service_name: str):
    """Build a Phoenix-bound tracer provider, instrument Agno, and put the
    redaction processor first in the export pipeline.

    Reads PHOENIX_COLLECTOR_ENDPOINT from the environment (see .env.example).
    Safe to call once per process; call before constructing any Agent.
    """
    endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")

    resource = Resource.create({_PHOENIX_PROJECT_RESOURCE_KEY: service_name})
    tracer_provider = TracerProvider(resource=resource)

    # Order matters: redaction must run before the spans reach the
    # exporter, so it's added first — see module docstring.
    tracer_provider.add_span_processor(RedactionSpanProcessor())
    exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Console Story view: forwards finished spans of a live claim run to the
    # browser. Registered after redaction, so it only ever sees redacted
    # attributes; a no-op for any trace that isn't a live run.
    tracer_provider.add_span_processor(LiveEventSpanProcessor())

    trace.set_tracer_provider(tracer_provider)

    AgnoInstrumentor().instrument(tracer_provider=tracer_provider)

    return tracer_provider


def inject_traceparent(headers: dict[str, str]) -> dict[str, str]:
    """Called by governance/client.py right before every httpx call to the
    token service / data gateway. Adds a `traceparent` header (W3C Trace
    Context) carrying whatever span is currently active as the parent for
    whatever span the receiving service starts — the sending half of the
    manual propagation this module's docstring describes."""
    from opentelemetry.propagate import inject

    inject(headers)
    return headers


def extract_context(headers: dict[str, str] | None):
    """Called by each FastAPI handler that should join the caller's trace
    (auth/app.py's issue(), data_gateway/app.py's query()/write(),
    api/officer.py's decide()) instead of starting a new root span. Returns
    an OTel Context to pass as `context=` to `tracer.start_as_current_span()`;
    a request with no `traceparent` header (e.g. a direct curl/test call)
    gets back the current (empty) context, which simply starts a new root
    span — the same behaviour as before propagation existed, not an error."""
    from opentelemetry.propagate import extract

    return extract(headers or {})
