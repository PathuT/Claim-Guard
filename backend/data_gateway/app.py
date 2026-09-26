"""Data gateway HTTP API (docs/architecture.md §4: "FastAPI + SQL").

Run: uv run uvicorn data_gateway.app:app --port 8200 (see DATA_GATEWAY_PORT in .env).

The only service that queries Postgres directly (docs/CLAUDE.md invariant 2).
Every request goes through the full checklist in gateway.py before touching
the DB: token validation -> row binding -> field-allowlist filtering.

One endpoint, `POST /query`, generic across collections rather than one route
per collection — the *scope* in the token (not the URL) determines what's
readable, so there's nothing collection-specific to route on beyond looking
up which table a scope maps to.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from opentelemetry import trace
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from observability.tracing import setup_tracing

from .db import get_session
from .gateway import (
    GatewayDenied,
    check_row_binding,
    filter_to_allowlist,
    validate_token,
)
from .models import (
    BankDetail,
    Claim,
    ClaimDocument,
    Hospital,
    MedicalRecord,
    Policyholder,
    PolicyTerm,
)

setup_tracing(service_name="claimguard-data-gateway")

app = FastAPI(title="ClaimGuard Data Gateway")
tracer = trace.get_tracer("claimguard.data_gateway")

# scope -> (ORM model, row-bound-by-claim_id?). Pseudonymised scopes are not
# row-bound (security-matrix.md §1) and are handled separately below.
SCOPE_MODEL: dict[str, type] = {
    "claim_documents:read": ClaimDocument,
    "claims:read": Claim,
    "claims:write": Claim,
    "medical_records:read": MedicalRecord,
    "medical_records:write": MedicalRecord,
    "policy_terms:read": PolicyTerm,
    "policyholders:read_limited": Policyholder,
    "bank_details:read": BankDetail,
    "hospitals:read": Hospital,
}


class QueryRequest(BaseModel):
    scope: str
    claim_id: str | None = None  # required for row-bound scopes; omitted for pseudonymised/reference-data reads


def _get_db() -> Session:
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def _row_claim_id(model: type, instance: Any) -> str | None:
    """claim_documents/claims/medical_records rows carry claim_id directly.
    Reference-data models (policy_terms, hospitals) aren't claim-bound at
    all — they're looked up by their own key, not a claim_id."""
    return getattr(instance, "claim_id", None)


@app.post("/query")
def query(
    req: QueryRequest,
    authorization: str = Header(...),
    x_agent_id: str = Header(..., alias="X-Agent-Id"),
    db: Session = Depends(_get_db),
) -> dict:
    token = authorization.removeprefix("Bearer ").strip()

    with tracer.start_as_current_span("gateway.access") as span:
        span.set_attribute("scope", req.scope)
        span.set_attribute("agent_id", x_agent_id)
        if req.claim_id:
            span.set_attribute("claim_id", req.claim_id)

        try:
            claims = validate_token(token, requested_scope=req.scope, requested_claim_id=req.claim_id)
        except GatewayDenied as exc:
            span.set_attribute("decision", "deny")
            span.set_attribute("rule_id", exc.reason_code)
            raise HTTPException(status_code=403, detail={"reason_code": exc.reason_code, "message": exc.message}) from None

        model = SCOPE_MODEL.get(req.scope)
        if model is None:
            span.set_attribute("decision", "deny")
            span.set_attribute("rule_id", "GATEWAY-UNKNOWN-SCOPE")
            raise HTTPException(status_code=403, detail={"reason_code": "GATEWAY-UNKNOWN-SCOPE", "message": f"no collection mapped for scope {req.scope!r}"})

        is_pseudonymised = req.scope.endswith(":read_pseudonymised")
        rows = db.execute(select(model)).scalars().all()

        results: list[dict] = []
        for row in rows:
            row_dict = {c.name: getattr(row, c.name) for c in row.__table__.columns}
            if not is_pseudonymised:
                row_claim_id = _row_claim_id(model, row)
                if row_claim_id is not None:
                    try:
                        check_row_binding(claims, row_claim_id=row_claim_id)
                    except GatewayDenied:
                        continue  # not this token's row — silently excluded, not a 403 for the whole query
            results.append(filter_to_allowlist(row_dict, scope=req.scope, agent=x_agent_id))

        span.set_attribute("decision", "allow")
        span.set_attribute("rows_returned", len(results))
        return {"rows": results}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
