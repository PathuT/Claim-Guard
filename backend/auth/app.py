"""Token service HTTP API (docs/architecture.md §4: "FastAPI + PyJWT (EdDSA)").

Run: uv run uvicorn auth.app:app --port 8100 (see TOKEN_SERVICE_PORT in .env).

Endpoints:
    POST /tokens        — issue a token from a signed identity assertion
    GET  /.well-known/jwks.json — publish public keys for the gateway to verify against
    POST /revoke/jti     — revoke a single token
    POST /revoke/req_id  — revoke every token issued for a request

`token.issue` span (docs/architecture.md §11) is emitted around the issuance
call; failures still emit a span (with the denial as the span's status/attrs)
so a denied issuance is visible in Phoenix too, not just a silent 4xx.
"""

from __future__ import annotations

import base64

from fastapi import FastAPI, Header, HTTPException
from opentelemetry import trace
from pydantic import BaseModel

from observability.tracing import extract_context, setup_tracing

from . import token_service as ts
from .keys import jwks

# Registers the Phoenix-bound TracerProvider *before* get_tracer() below —
# without this, spans are created but never exported anywhere (a silent
# no-op), same gap the M0 hello_agent.py setup avoids for the agent side.
setup_tracing(service_name="claimguard-token-service")

app = FastAPI(title="ClaimGuard Token Service")
tracer = trace.get_tracer("claimguard.token_service")


class IssueRequest(BaseModel):
    agent_id: str
    req_id: str
    scope: str
    timestamp: float
    signature: str = ""  # base64-encoded Ed25519 signature (see governance.identity.sign_assertion)
    parent: str | None = None
    parent_scopes: list[str] | None = None
    claim_id: str | None = None


class IssueResponse(BaseModel):
    token: str
    jti: str
    exp: int
    kid: str


class RevokeJtiRequest(BaseModel):
    jti: str


class RevokeReqIdRequest(BaseModel):
    req_id: str


@app.post("/tokens", response_model=IssueResponse)
def issue(req: IssueRequest, traceparent: str | None = Header(default=None)) -> IssueResponse:
    try:
        signature_bytes = base64.b64decode(req.signature) if req.signature else b""
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail={"reason_code": "GATEWAY-MALFORMED", "message": "signature is not valid base64"}) from None

    assertion = ts.IdentityAssertion(
        agent_id=req.agent_id, req_id=req.req_id, scope=req.scope,
        timestamp=req.timestamp, signature=signature_bytes,
        parent=req.parent, claim_id=req.claim_id,
    )
    parent_scopes = set(req.parent_scopes) if req.parent_scopes is not None else None

    # M6: join the caller's trace (governance/client.py's own
    # governance.decision span) instead of starting a new root span here —
    # the manual receiving half of context propagation this module's own
    # docstring in observability/tracing.py describes.
    parent_context = extract_context({"traceparent": traceparent} if traceparent else None)
    with tracer.start_as_current_span("token.issue", context=parent_context) as span:
        span.set_attribute("agent_id", req.agent_id)
        span.set_attribute("scope", req.scope)
        span.set_attribute("req_id", req.req_id)
        try:
            issued = ts.issue_token(assertion, parent_scopes=parent_scopes)
        except ts.TokenServiceError as exc:
            span.set_attribute("decision", "deny")
            span.set_attribute("rule_id", exc.reason_code)
            raise HTTPException(status_code=403, detail={"reason_code": exc.reason_code, "message": exc.message}) from None
        span.set_attribute("decision", "allow")
        span.set_attribute("jti", issued.jti)
        span.set_attribute("ttl_seconds", issued.exp - int(req.timestamp))
        return IssueResponse(token=issued.jwt, jti=issued.jti, exp=issued.exp, kid=issued.kid)


@app.get("/.well-known/jwks.json")
def jwks_endpoint() -> dict:
    return jwks()


@app.post("/revoke/jti")
def revoke_jti(req: RevokeJtiRequest) -> dict:
    ts.revoke_jti(req.jti)
    return {"revoked": req.jti}


@app.post("/revoke/req_id")
def revoke_req_id(req: RevokeReqIdRequest) -> dict:
    ts.revoke_req_id(req.req_id)
    return {"revoked_req_id": req.req_id}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
