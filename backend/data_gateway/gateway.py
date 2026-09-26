"""Data gateway request validation: docs/security-matrix.md §6, the 7-step
checklist, checked in order, fail-closed (docs/CLAUDE.md invariant 7 — "Any
error in policy evaluation, token validation, or the gateway = deny").

This module validates and authorizes a request; it does not itself run SQL.
Row binding (step 6) and field filtering (step 7) are expressed here as pure
functions over already-fetched rows, so they're unit-testable without a live
DB — the FastAPI app (M2, `api.py`) wires this to real queries.
"""

from __future__ import annotations

import jwt

from auth.keys import public_key_for
from auth.matrix import field_allowlist_for
from auth.token_service import AUDIENCE, ISSUER, is_revoked


class GatewayDenied(Exception):
    """Raised for any of the 7 checklist failures. `reason_code` matches
    docs/security-matrix.md's rule ids (or a checklist step name where no
    rule id exists yet, e.g. "GATEWAY-EXPIRED")."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        self.message = message
        super().__init__(f"{reason_code}: {message}")


CLOCK_SKEW_SECONDS = 5  # security-matrix.md §6.3


def validate_token(token: str, requested_scope: str, requested_claim_id: str | None = None) -> dict:
    """Steps 1-5 of the checklist. Returns the verified claims dict on
    success; raises GatewayDenied (fail closed) on any failure.

    Step ordering matters for defense-in-depth (cheapest/most-fundamental
    checks first) but every step is independently enforced regardless of
    order — this isn't a shortcut-evaluation optimization, it's a literal
    unrolling of the checklist.
    """
    # Step 0 (prerequisite to step 1): find which key this token claims to be
    # signed with, without trusting anything else in it yet.
    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError as exc:
        raise GatewayDenied("GATEWAY-MALFORMED", f"could not parse token header: {exc}") from None

    kid = unverified_header.get("kid")
    public_key = public_key_for(kid) if kid else None
    if public_key is None:
        raise GatewayDenied("GATEWAY-UNKNOWN-KID", f"no known signing key for kid={kid!r}")

    # Step 1: signature valid for that known kid.
    # Step 2: aud/iss correct.
    # Step 3: exp in the future (PyJWT enforces this during decode; we pass
    # our own CLOCK_SKEW_SECONDS as leeway so it's the exact 5s the spec asks for).
    try:
        claims = jwt.decode(
            token, public_key, algorithms=["EdDSA"],
            audience=AUDIENCE, issuer=ISSUER, leeway=CLOCK_SKEW_SECONDS,
        )
    except jwt.ExpiredSignatureError:
        raise GatewayDenied("GATEWAY-EXPIRED", "token exp has passed") from None
    except jwt.InvalidAudienceError:
        raise GatewayDenied("GATEWAY-BAD-AUDIENCE", "aud does not match data-gateway") from None
    except jwt.InvalidIssuerError:
        raise GatewayDenied("GATEWAY-BAD-ISSUER", "iss does not match token service") from None
    except jwt.InvalidSignatureError:
        raise GatewayDenied("GATEWAY-BAD-SIGNATURE", "signature verification failed") from None
    except jwt.InvalidTokenError as exc:
        raise GatewayDenied("GATEWAY-INVALID", f"token rejected: {exc}") from None

    # Step 4: jti not revoked (also covers the req_id-level revocation from
    # security-matrix.md §4 — "revoked when the request reaches a terminal
    # or pending_human state").
    if is_revoked(claims["jti"], claims["req_id"]):
        raise GatewayDenied("GATEWAY-REVOKED", f"jti={claims['jti']} or its req_id has been revoked")

    # Step 5: scope matches the requested collection and operation.
    if claims["scope"] != requested_scope:
        raise GatewayDenied(
            "GATEWAY-SCOPE-MISMATCH",
            f"token scope {claims['scope']!r} does not match requested {requested_scope!r}",
        )

    return claims


def check_row_binding(claims: dict, row_claim_id: str, row_policy_number: str | None = None) -> None:
    """Step 6: requested rows belong to the token's claim_id.

    security-matrix.md §1: "unless the scope is read_pseudonymised, the
    gateway only returns rows where claim_id (or the claim's policy_number)
    equals the token's claim_id claim." Pseudonymised scopes intentionally
    skip row binding (they read across claims by design) — callers must not
    call this for those scopes.
    """
    token_claim_id = claims.get("claim_id")
    if token_claim_id is None:
        raise GatewayDenied("GATEWAY-NO-CLAIM-BINDING", "token has no claim_id to bind rows to")
    if row_claim_id != token_claim_id:
        raise GatewayDenied(
            "GATEWAY-ROW-BINDING",
            f"requested row's claim_id {row_claim_id!r} does not match token's claim_id {token_claim_id!r}",
        )


def filter_to_allowlist(row: dict, scope: str, agent: str | None = None) -> dict:
    """Step 7: response filtered to the field allowlist. A scope with no
    allowlist entry (e.g. a plain `claims:read` from an agent not in
    CLAIMS_READ_ALLOWLIST_BY_AGENT) returns the row unfiltered — full-row
    access within that scope's row binding, per security-matrix.md §3's
    "Allowed fields" column only listing restricted scopes explicitly."""
    allowlist = field_allowlist_for(scope, agent)
    if allowlist is None:
        return dict(row)
    # Dotted paths (e.g. "member.age") address a nested dict field; anything
    # else is a top-level key. Unknown/absent keys are silently dropped
    # rather than raising, since callers may pass a superset row shape.
    filtered: dict = {}
    for path in allowlist:
        if "." in path:
            top, sub = path.split(".", 1)
            if top in row and isinstance(row[top], dict) and sub in row[top]:
                filtered.setdefault(top, {})[sub] = row[top][sub]
        elif path in row:
            filtered[path] = row[path]
    return filtered
