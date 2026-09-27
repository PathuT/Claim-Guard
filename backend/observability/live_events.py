"""Live event stream for the Console's Story view (frontend/app/story).

A claim run is normally one blocking HTTP call: the browser sees nothing
until every agent, governance check, token issuance and gateway call has
already finished. This module lets a *live* run (api/agentos.py's
POST /claims/{id}/live) surface each of those backend operations to the
browser the moment it happens, without changing what any of them do.

Routing is by OpenTelemetry trace_id, not a thread-local/contextvar: the
live endpoint opens a root span, registers a queue for that span's
trace_id (`attach()`), and every `emit()` / finished span anywhere in the
same trace lands on that queue. Everything this project already does to
keep one claim in one trace (docs/plan.md M6 — the supervisor's
claim.flow span, governance/client.py's tool.call span) is exactly what
makes this routing work; no new plumbing is threaded through call sites.

Outside a live run there is no registered queue for the current trace, so
`emit()` and the span processor are both no-ops — the Harbor adapter, the
plain POST /claims endpoint and every test behave exactly as before.

Privacy (docs/CLAUDE.md invariant 9 applies here the same way it applies
to spans): every emitted string passes through observability/redaction's
account-number/name rules, and `LiveEventSpanProcessor` is registered
AFTER `RedactionSpanProcessor`, so the span attributes it reads have
already been redacted. Callers never pass raw medical text or tokens (only
a token's jti) to `emit()`.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, Span
from opentelemetry.sdk.trace.export import SpanProcessor

from . import terminal_log
from .redaction import MEDICAL_REDACTED, redact_value

_channels: dict[int, queue.Queue] = {}
# The workflow step currently running in each live trace (set by step(...,
# "active")). Every event is stamped with it, so the console can attribute
# LLM calls, tokens and governance decisions to the agent doing the work.
_current_step: dict[int, str] = {}
_lock = threading.Lock()

# Our own hand-rolled spans already get a richer, explicit emit() at the
# call site (governance decision with rule ids, token jti/ttl, ...) — the
# span processor only adds a compact "span exported" line for these.
_EXPLICIT_SPANS = {"governance.decision", "tool.call", "claim.flow", "claim.submit", "claim.live_run", "claim.live_attack"}


def attach(trace_id: int, channel: queue.Queue) -> None:
    with _lock:
        _channels[trace_id] = channel


def detach(trace_id: int) -> None:
    with _lock:
        _channels.pop(trace_id, None)
        _current_step.pop(trace_id, None)


def _current_trace_id() -> int | None:
    span_context = trace.get_current_span().get_span_context()
    return span_context.trace_id if span_context.is_valid else None


def _channel_for_current_trace() -> queue.Queue | None:
    trace_id = _current_trace_id()
    return None if trace_id is None else _channels.get(trace_id)


def _safe(text: str | None) -> str | None:
    if text is None:
        return None
    return str(redact_value("live_event", text))


def emit(
    layer: str,
    title: str,
    detail: str | None = None,
    *,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    """One human-readable line in the Story view's live backend log.

    `layer` is the architectural layer the operation belongs to (api,
    document, agent, llm, rules, governance, identity, token, gateway,
    database, audit, state, payment, trace) — the frontend maps each to
    the technology that implements it. `level` is one of info / success /
    warn / deny / error.
    """
    trace_id = _current_trace_id()
    safe_title, safe_detail = _safe(title), _safe(detail)
    terminal_log.event(layer, safe_title, safe_detail, level, trace_id)
    channel = None if trace_id is None else _channels.get(trace_id)
    if channel is None:
        return
    channel.put({
        "kind": "log",
        "ts": time.time(),
        "layer": layer,
        "title": safe_title,
        "detail": safe_detail,
        "level": level,
        "step": _current_step.get(trace_id),
        "data": data or {},
    })


def step(step_id: str, status: str, summary: str | None = None, data: dict[str, Any] | None = None) -> None:
    """Chapter progress for the Story view: `status` is active / done /
    skipped / blocked."""
    trace_id = _current_trace_id()
    terminal_log.step(step_id, status, _safe(summary), trace_id)
    channel = None if trace_id is None else _channels.get(trace_id)
    if channel is None:
        return
    if status == "active":
        _current_step[trace_id] = step_id
    channel.put({"kind": "step", "ts": time.time(), "step": step_id, "status": status, "summary": _safe(summary), "data": data or {}})


class LiveEventSpanProcessor(SpanProcessor):
    """Forwards finished spans that belong to a live run onto its queue.

    LLM spans (OpenInference's `openinference.span.kind == "LLM"`) become a
    rich line — model, latency, token counts — since that's the one kind of
    backend work with no explicit emit() of its own (Agno makes the call).
    Everything else becomes a compact "span exported to Phoenix" line so the
    trace itself is visibly being built as the story plays.
    """

    def on_start(self, span: Span, parent_context=None) -> None:
        return None

    def on_end(self, span: ReadableSpan) -> None:
        span_context = span.get_span_context()
        if span_context is None:
            return
        attributes = dict(span.attributes or {})
        kind = attributes.get("openinference.span.kind")
        duration_ms = ((span.end_time or 0) - (span.start_time or 0)) / 1_000_000

        if kind == "LLM":
            model = attributes.get("llm.model_name") or attributes.get("llm.provider") or "LLM"
            prompt_tokens = attributes.get("llm.token_count.prompt")
            completion_tokens = attributes.get("llm.token_count.completion")
            tokens = ""
            if prompt_tokens is not None or completion_tokens is not None:
                tokens = f" · {prompt_tokens or 0} prompt + {completion_tokens or 0} completion tokens"
            # Printed for every LLM call, live run or not (Harbor, POST /claims).
            terminal_log.event("llm", f"LLM call completed — {model}", f"{duration_ms:,.0f} ms{tokens}", "info", span_context.trace_id)

        channel = _channels.get(span_context.trace_id)
        if channel is None:
            return
        current_step = _current_step.get(span_context.trace_id)
        redacted_count = sum(1 for v in attributes.values() if v == MEDICAL_REDACTED)

        if kind == "LLM":
            channel.put({
                "kind": "log", "ts": time.time(), "layer": "llm", "step": current_step,
                "title": f"LLM call completed — {model}",
                "detail": f"{duration_ms:,.0f} ms{tokens}" + (f" · {redacted_count} medical attribute(s) redacted before export" if redacted_count else ""),
                "level": "info",
                "data": {"model": str(model), "duration_ms": round(duration_ms), "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
            })
            return

        if kind == "AGENT":
            channel.put({
                "kind": "log", "ts": time.time(), "layer": "agent", "step": current_step,
                "title": f"Agno agent run finished — {span.name}",
                "detail": f"{duration_ms:,.0f} ms" + (f" · input/output redacted in trace ({redacted_count} attribute(s))" if redacted_count else ""),
                "level": "info",
                "data": {"duration_ms": round(duration_ms)},
            })
            return

        if span.name in _EXPLICIT_SPANS or kind is not None:
            channel.put({
                "kind": "trace", "ts": time.time(), "layer": "trace", "step": current_step,
                "title": f"span exported → Phoenix: {span.name}",
                "detail": f"{duration_ms:,.1f} ms",
                "level": "info",
                "data": {"span": span.name, "duration_ms": round(duration_ms, 1)},
            })

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True
