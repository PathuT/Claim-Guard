"""The real tool-call path (docs/architecture.md §6), wired end to end for
the first time in M5: governance check -> signed identity assertion ->
token service (real HTTP) -> data gateway (real HTTP) -> result.

M4's agents (intake, medical_reviewer, coverage) took claim/policy/finding
data as plain function arguments — acceptable for that milestone
(docs/plan.md M4 scope note) but not for fraud/payout, which is exactly
where the security story needs to be real: fraud reads pseudonymised claims
and the hospital watchlist over the actual data gateway, and payout's
execute_payout call is what PAY-001..006 exist to police. `call_tool()`
below is the one function fraud.py/payout.py (and anything built after them)
uses to do that; nothing here reaches Postgres directly (docs/engineering-guide.md
invariant 2).

Sequence per call, matching docs/architecture.md §6 exactly:
  1. check_and_audit(ctx) — GOV-001/002, PAY/STATE/DATA rules, audit + span.
     Raises GovernanceDenied on any failure; the caller gets a structured
     denial, never an exception it has to interpret (docs/architecture.md
     §6: "A denied agent receives a clear structured denial... so it can
     continue safely").
  2. Sign an identity assertion (governance.identity.sign_assertion) and
     POST it to the token service's /tokens endpoint.
  3. POST the actual query/write to the data gateway with that token.

Scope-to-endpoint routing: read scopes go to POST /query, write scopes
(anything ending `:write`) go to POST /write — mirroring data_gateway/app.py's
own SCOPE_MODEL / SCOPE_WRITE_MODEL split.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
from opentelemetry import trace

from observability.live_events import emit
from observability.tracing import inject_traceparent

from .adapter import ToolCallContext, check_and_audit
from .identity import sign_assertion

TOKEN_SERVICE_URL = os.environ.get("TOKEN_SERVICE_URL", f"http://localhost:{os.environ.get('TOKEN_SERVICE_PORT', '8100')}")
DATA_GATEWAY_URL = os.environ.get("DATA_GATEWAY_URL", f"http://localhost:{os.environ.get('DATA_GATEWAY_PORT', '8200')}")

HTTP_TIMEOUT_SECONDS = 10.0

tracer = trace.get_tracer("claimguard.governance.client")


class ToolCallDenied(Exception):
    """Raised for any failure in the chain — governance denial, token
    refusal, or gateway denial — all collapsed into one exception type with
    a `reason_code` so a caller can branch on it (e.g. route to
    pending_human) without needing to know which layer said no."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        self.message = message
        super().__init__(f"{reason_code}: {message}")


@dataclass
class ToolCallRequest:
    req_id: str
    agent_id: str
    tool_name: str
    scope: str
    args: dict[str, Any]
    claim_id: str | None = None
    trusted: dict[str, Any] | None = None


def _get_token(agent_id: str, req_id: str, scope: str, claim_id: str | None) -> str:
    ts = time.time()
    signed = sign_assertion(agent_id=agent_id, req_id=req_id, scope=scope, timestamp=ts)
    body = {
        "agent_id": agent_id,
        "req_id": req_id,
        "scope": scope,
        "timestamp": ts,
        "signature": _b64(signed.signature),
        "claim_id": claim_id,
    }
    # M6: inject a `traceparent` header carrying the currently active span
    # (check_and_audit's governance.decision span, below) as this request's
    # parent, so the token service's token.issue span joins the same trace
    # instead of starting its own.
    emit("identity", f"{agent_id} signed an Ed25519 identity assertion", f"AGT agent identity · req_id={req_id} · requested scope {scope}",
         data={"agent_id": agent_id, "scope": scope})
    headers = inject_traceparent({})
    resp = httpx.post(f"{TOKEN_SERVICE_URL}/tokens", json=body, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
    if resp.status_code != 200:
        detail = resp.json().get("detail", {})
        emit("token", f"Token service REFUSED — {detail.get('reason_code', 'TOKEN-DENIED')}", detail.get("message", resp.text), level="deny",
             data={"agent_id": agent_id, "scope": scope, "rule_id": detail.get("reason_code", "TOKEN-DENIED")})
        raise ToolCallDenied(detail.get("reason_code", "TOKEN-DENIED"), detail.get("message", resp.text))
    issued = resp.json()
    # jti only — the token itself is never logged (docs/engineering-guide.md invariant 11).
    emit(
        "token",
        f"Token service minted a scoped JWT for {agent_id}",
        f"EdDSA-signed · scope={scope} · aud=data-gateway · ttl={max(0, int(issued['exp'] - ts))}s · jti={issued['jti']}",
        level="success",
        data={"jti": issued["jti"], "scope": scope, "agent_id": agent_id, "ttl_s": max(0, int(issued["exp"] - ts))},
    )
    return issued["token"]


def _b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode()


def call_tool(request: ToolCallRequest) -> dict:
    """The one entrypoint fraud/payout tool implementations call. Returns
    the gateway's JSON response (`{"rows": [...]}` for a read, `{"status":
    "ok"}` for a write) on success; raises ToolCallDenied on any failure at
    any layer.

    execute_payout specifically: the governance trace_id (the audit
    decision's own id) is injected into the write payload as
    `agt_decision_id` before it reaches the gateway — Payment.agt_decision_id
    (docs/architecture.md §10) records *which governance decision* allowed
    this payout, so it's the trace_id from check_and_audit(), not a second,
    unrelated id invented here.

    Wrapped in its own `tool.call` span so check_and_audit()'s own
    governance.decision span (a child of it) and the token/gateway HTTP
    calls that follow both nest under one still-open parent — found live
    while verifying M6's propagation that check_and_audit()'s `with
    tracer.start_as_current_span(...)` block had already exited by the time
    _get_token() ran, so there was no active span left for
    inject_traceparent() to actually propagate; every span kept starting
    its own independent trace despite the propagation code itself being
    correct. This tool.call span is what stays open for the whole call.
    """
    with tracer.start_as_current_span("tool.call") as call_span:
        call_span.set_attribute("agent_id", request.agent_id)
        call_span.set_attribute("tool_name", request.tool_name)
        call_span.set_attribute("req_id", request.req_id)

        ctx = ToolCallContext(
            req_id=request.req_id,
            agent_id=request.agent_id,
            tool_name=request.tool_name,
            args=request.args,
            claim_id=request.claim_id,
            trusted=request.trusted or {},
        )
        try:
            trace_id = check_and_audit(ctx)
        except Exception as exc:  # GovernanceDenied — imported lazily to avoid a cycle
            from .adapter import GovernanceDenied

            if isinstance(exc, GovernanceDenied):
                raise ToolCallDenied(exc.rule_id, exc.message) from None
            raise

        token = _get_token(request.agent_id, request.req_id, request.scope, request.claim_id)

        # tool.call (this span) is still the active span here, so the
        # gateway's gateway.access span joins the same trace as
        # governance.decision and token.issue both did above — a single
        # trace_id covering governance -> token issuance -> gateway access,
        # the "one trace per req_id" M6 asks for.
        headers = inject_traceparent({"Authorization": f"Bearer {token}", "X-Agent-Id": request.agent_id})
        if request.scope.endswith(":write"):
            data = dict(request.args)
            if request.tool_name == "execute_payout":
                data["agt_decision_id"] = trace_id
            body = {"scope": request.scope, "claim_id": request.claim_id, "data": data}
            resp = httpx.post(f"{DATA_GATEWAY_URL}/write", json=body, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
        else:
            body = {"scope": request.scope, "claim_id": request.claim_id}
            resp = httpx.post(f"{DATA_GATEWAY_URL}/query", json=body, headers=headers, timeout=HTTP_TIMEOUT_SECONDS)

        endpoint = "/write" if request.scope.endswith(":write") else "/query"
        if resp.status_code != 200:
            detail = resp.json().get("detail", {})
            emit("gateway", f"Data gateway DENIED POST {endpoint} — {detail.get('reason_code', 'GATEWAY-DENIED')}", detail.get("message", resp.text), level="deny",
                 data={"agent_id": request.agent_id, "scope": request.scope, "rule_id": detail.get("reason_code", "GATEWAY-DENIED")})
            raise ToolCallDenied(detail.get("reason_code", "GATEWAY-DENIED"), detail.get("message", resp.text))
        payload = resp.json()
        rows = payload.get("rows")
        emit(
            "gateway",
            f"Data gateway POST {endpoint} — {request.scope}",
            "JWT verified (signature, audience, expiry, revocation, scope, row binding) · "
            + (f"{len(rows)} row(s) returned, field-allowlisted" if rows is not None else "write committed to Postgres"),
            level="success",
            data={"agent_id": request.agent_id, "scope": request.scope, "rows": len(rows) if rows is not None else None},
        )
        emit("database", f"Postgres {'INSERT' if endpoint == '/write' else 'SELECT'} on {request.scope.split(':')[0]}", "Supabase Postgres 16 · reached only through the data gateway")
        return payload


def new_req_id() -> str:
    return f"req-{uuid.uuid4()}"
