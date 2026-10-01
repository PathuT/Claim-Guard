"""Data gateway HTTP API (docs/architecture.md §4: "FastAPI + SQL").

Run: uv run uvicorn data_gateway.app:app --port 8200 (see DATA_GATEWAY_PORT in .env).

The only service that queries Postgres directly (docs/engineering-guide.md invariant 2).
Every request goes through the full checklist in gateway.py before touching
the DB: token validation -> row binding -> field-allowlist filtering.

One endpoint, `POST /query`, generic across collections rather than one route
per collection — the *scope* in the token (not the URL) determines what's
readable, so there's nothing collection-specific to route on beyond looking
up which table a scope maps to.

`POST /write` (M5) is the write-side equivalent for the three `*:write`
scopes (`claims:write`, `medical_records:write`, `payments:write`): same
token validation checklist (steps 1-5), then a field-allowlist on which
fields that scope may set (WRITE_ALLOWLIST) rather than the read side's
response-filtering allowlist, then row binding against `claim_id` — a
`claims:write`/`medical_records:write` token can only write the claim_id
baked into its own JWT, so a compromised or confused agent cannot write
into a different claim than the one it was scoped for.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from opentelemetry import trace
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from observability.tracing import extract_context, setup_tracing

from .db import get_session
from .gateway import (
    GatewayDenied,
    check_row_binding,
    filter_to_allowlist,
    filter_to_write_allowlist,
    validate_token,
)
from .models import (
    BankDetail,
    Claim,
    ClaimDocument,
    Hospital,
    MedicalRecord,
    Payment,
    Policyholder,
    PolicyTerm,
)
from .pseudonymise import pseudonymise_claim_row

setup_tracing(service_name="claimguard-data-gateway")

app = FastAPI(title="ClaimGuard Data Gateway")
tracer = trace.get_tracer("claimguard.data_gateway")

# scope -> (ORM model, row-bound-by-claim_id?). Pseudonymised scopes are not
# row-bound (security-matrix.md §1) and are handled separately below.
SCOPE_MODEL: dict[str, type] = {
    "claim_documents:read": ClaimDocument,
    "claims:read": Claim,
    "claims:read_pseudonymised": Claim,
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


class WriteRequest(BaseModel):
    scope: str
    claim_id: str  # every *:write scope is row-bound; there is no unbound write
    data: dict[str, Any]


# scope -> ORM model for the write path. Deliberately separate from
# SCOPE_MODEL even though claims:write/medical_records:write map to the same
# models as their read counterparts — keeping them apart means a future
# write-only or read-only scope doesn't have to fight the other side's
# assumptions (e.g. payments:write has no read counterpart at all).
SCOPE_WRITE_MODEL: dict[str, type] = {
    "claims:write": Claim,
    "medical_records:write": MedicalRecord,
    "payments:write": Payment,
}


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
    traceparent: str | None = Header(default=None),
    db: Session = Depends(_get_db),
) -> dict:
    token = authorization.removeprefix("Bearer ").strip()

    parent_context = extract_context({"traceparent": traceparent} if traceparent else None)
    with tracer.start_as_current_span("gateway.access", context=parent_context) as span:
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

        # bank_details has no claim_id column (it's keyed by policy_number),
        # so row binding for it goes through the token's claim -> its
        # policy_number, resolved once here rather than per-row. Any other
        # *:read scope's rows carry claim_id directly and skip this.
        token_policy_number: str | None = None
        if model is BankDetail:
            claim_row = db.get(Claim, claims.get("claim_id")) if claims.get("claim_id") else None
            if claim_row is None:
                span.set_attribute("decision", "deny")
                span.set_attribute("rule_id", "GATEWAY-NO-CLAIM-BINDING")
                raise HTTPException(status_code=403, detail={"reason_code": "GATEWAY-NO-CLAIM-BINDING", "message": f"token's claim_id {claims.get('claim_id')!r} does not exist"})
            token_policy_number = claim_row.policy_number

        results: list[dict] = []
        for row in rows:
            row_dict = {c.name: getattr(row, c.name) for c in row.__table__.columns}
            if is_pseudonymised:
                # docs/architecture.md §10: keyed-hash pseudonyms replace
                # claim_id/policy_number, and every other PII-adjacent field
                # not in the pseudonymised allowlist is dropped entirely —
                # done here, in pseudonymise_claim_row(), before the
                # allowlist filter even runs (filter_to_allowlist would only
                # drop columns, not swap claim_id for a hash).
                row_dict = pseudonymise_claim_row(row_dict)
            elif model is BankDetail:
                try:
                    check_row_binding(claims, row_claim_id=None, row_policy_number=row_dict.get("policy_number"), token_policy_number=token_policy_number)
                except GatewayDenied:
                    continue  # not this token's policy — silently excluded, same as the direct-binding case below
            else:
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


@app.post("/write")
def write(
    req: WriteRequest,
    authorization: str = Header(...),
    x_agent_id: str = Header(..., alias="X-Agent-Id"),
    traceparent: str | None = Header(default=None),
    db: Session = Depends(_get_db),
) -> dict:
    """Write-side equivalent of /query for the three `*:write` scopes.
    Same token checklist (steps 1-5 via validate_token), then row binding
    against the token's own claim_id (every *:write token is claim-bound —
    an intake token scoped to one claim cannot write another claim's row),
    then the write-side field allowlist strips anything not in
    WRITE_FIELD_ALLOWLISTS before it reaches the ORM.

    claims:write / medical_records:write are update-only: the claim row
    itself is created by claim submission (api/claims.py, not intake — the
    non-nullable fields Claim requires, like policy_number/hospital_id/
    admission_date, aren't in WRITE_FIELD_ALLOWLISTS for claims:write at
    all, so intake could never construct a valid new row even if it tried).
    medical_records:write *does* insert-if-absent since intake is the first
    and only writer of that row. payments:write is insert-only — a new
    payments row per payout, never an update to an existing one
    (docs/architecture.md §10: payments starts empty, one row per payout;
    PAY-005 in governance/rules.py is what actually prevents a second payout
    for the same claim, not this endpoint).
    """
    token = authorization.removeprefix("Bearer ").strip()

    parent_context = extract_context({"traceparent": traceparent} if traceparent else None)
    with tracer.start_as_current_span("gateway.access", context=parent_context) as span:
        span.set_attribute("scope", req.scope)
        span.set_attribute("agent_id", x_agent_id)
        span.set_attribute("claim_id", req.claim_id)
        span.set_attribute("write", True)

        try:
            claims = validate_token(token, requested_scope=req.scope, requested_claim_id=req.claim_id)
        except GatewayDenied as exc:
            span.set_attribute("decision", "deny")
            span.set_attribute("rule_id", exc.reason_code)
            raise HTTPException(status_code=403, detail={"reason_code": exc.reason_code, "message": exc.message}) from None

        model = SCOPE_WRITE_MODEL.get(req.scope)
        if model is None:
            span.set_attribute("decision", "deny")
            span.set_attribute("rule_id", "GATEWAY-UNKNOWN-SCOPE")
            raise HTTPException(status_code=403, detail={"reason_code": "GATEWAY-UNKNOWN-SCOPE", "message": f"no collection mapped for scope {req.scope!r}"})

        try:
            check_row_binding(claims, row_claim_id=req.claim_id)
        except GatewayDenied as exc:
            span.set_attribute("decision", "deny")
            span.set_attribute("rule_id", exc.reason_code)
            raise HTTPException(status_code=403, detail={"reason_code": exc.reason_code, "message": exc.message}) from None

        payload = filter_to_write_allowlist(req.data, scope=req.scope)

        if model is Payment:
            # Insert-only: a new payments row per payout.
            db.add(Payment(claim_id=req.claim_id, **payload))
        elif model is Claim:
            # Update-only: claims:write (intake) can only set fields already
            # in WRITE_FIELD_ALLOWLISTS["claims:write"], none of which are
            # enough to construct a valid new Claim row — the row must
            # already exist (created at claim submission).
            existing_claim = db.get(Claim, req.claim_id)
            if existing_claim is None:
                span.set_attribute("decision", "deny")
                span.set_attribute("rule_id", "GATEWAY-NO-SUCH-CLAIM")
                raise HTTPException(status_code=404, detail={"reason_code": "GATEWAY-NO-SUCH-CLAIM", "message": f"claim {req.claim_id!r} does not exist"})
            for field_name, value in payload.items():
                setattr(existing_claim, field_name, value)
        else:  # MedicalRecord: insert-if-absent, since intake is its sole writer
            existing_record = db.execute(select(MedicalRecord).where(MedicalRecord.claim_id == req.claim_id)).scalar_one_or_none()
            if existing_record is None:
                db.add(MedicalRecord(claim_id=req.claim_id, **payload))
            else:
                for field_name, value in payload.items():
                    setattr(existing_record, field_name, value)

        db.commit()

        span.set_attribute("decision", "allow")
        return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
