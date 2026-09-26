"""Security tests for the data gateway (docs/plan.md M2): the other half of
"Tests first: expired, wrong audience, wrong scope, wrong claim, revoked,
replay, allowlist leakage." Covers docs/security-matrix.md §6's 7-step
checklist plus row binding and field-allowlist filtering.
"""

from __future__ import annotations

import time

import jwt
import pytest

from auth import token_service as ts
from auth.keys import ACTIVE_KID, active_private_key
from data_gateway.gateway import (
    GatewayDenied,
    check_row_binding,
    filter_to_allowlist,
    validate_token,
)
from governance.identity import sign_assertion


def _assertion(agent_id="coverage", scope="policy_terms:read", req_id="req_gw_001", claim_id=None):
    """A real, correctly signed IdentityAssertion — M3 wired real Ed25519
    signature verification into the token service (see
    test_security_token_service.py's own _assertion() for the same note)."""
    ts_val = time.time()
    signed = sign_assertion(agent_id, req_id, scope, ts_val)
    return ts.IdentityAssertion(agent_id=agent_id, scope=scope, req_id=req_id, timestamp=ts_val, signature=signed.signature, claim_id=claim_id)


@pytest.fixture(autouse=True)
def _reset_state():
    ts._revoked_jti.clear()
    ts._revoked_req_id.clear()
    ts._trust_scores.clear()
    yield
    ts._revoked_jti.clear()
    ts._revoked_req_id.clear()
    ts._trust_scores.clear()


def _forge_token(claims: dict, key: bytes | None = None, kid: str = ACTIVE_KID) -> str:
    return jwt.encode(claims, key or active_private_key(), algorithm="EdDSA", headers={"kid": kid})


def _base_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": ts.ISSUER, "sub": "agent:coverage", "aud": ts.AUDIENCE,
        "scope": "policy_terms:read", "req_id": "req_gw_forge", "jti": "forge-jti-1",
        "iat": now, "exp": now + 300, "kid": ACTIVE_KID,
    }
    claims.update(overrides)
    return claims


# --- Happy path: a validly issued token passes all 5 decode-time checks ---

def test_security_valid_token_passes_gateway():
    token = ts.issue_token(_assertion())
    claims = validate_token(token.jwt, requested_scope="policy_terms:read")
    assert claims["scope"] == "policy_terms:read"


# --- Step 1/kid: unknown signing key ---

def test_security_unknown_kid_rejected():
    forged = _forge_token(_base_claims(), kid="some-unknown-kid")
    with pytest.raises(GatewayDenied) as exc:
        validate_token(forged, requested_scope="policy_terms:read")
    assert exc.value.reason_code == "GATEWAY-UNKNOWN-KID"


def test_security_bad_signature_rejected():
    """A token whose header claims our real kid, but was actually signed
    with a different private key — the classic forged-token attack."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    attacker_key = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    forged = _forge_token(_base_claims(), key=attacker_key, kid=ACTIVE_KID)
    with pytest.raises(GatewayDenied) as exc:
        validate_token(forged, requested_scope="policy_terms:read")
    assert exc.value.reason_code == "GATEWAY-BAD-SIGNATURE"


# --- Step 2: wrong audience / issuer ---

def test_security_wrong_audience_rejected_by_gateway():
    forged = _forge_token(_base_claims(aud="some-other-service"))
    with pytest.raises(GatewayDenied) as exc:
        validate_token(forged, requested_scope="policy_terms:read")
    assert exc.value.reason_code == "GATEWAY-BAD-AUDIENCE"


def test_security_wrong_issuer_rejected_by_gateway():
    forged = _forge_token(_base_claims(iss="not-the-real-token-service"))
    with pytest.raises(GatewayDenied) as exc:
        validate_token(forged, requested_scope="policy_terms:read")
    assert exc.value.reason_code == "GATEWAY-BAD-ISSUER"


# --- Step 3: expired ---

def test_security_expired_token_rejected_by_gateway():
    past = int(time.time()) - 3600
    forged = _forge_token(_base_claims(iat=past - 60, exp=past))
    with pytest.raises(GatewayDenied) as exc:
        validate_token(forged, requested_scope="policy_terms:read")
    assert exc.value.reason_code == "GATEWAY-EXPIRED"


def test_security_clock_skew_within_5s_tolerated():
    """security-matrix.md §6.3: max 5s clock skew allowed."""
    now = int(time.time())
    forged = _forge_token(_base_claims(iat=now - 302, exp=now - 2))  # expired 2s ago, within 5s skew
    claims = validate_token(forged, requested_scope="policy_terms:read")
    assert claims["jti"] == "forge-jti-1"


# --- Step 4: revoked (and replay, which is the same check reused) ---

def test_security_revoked_jti_rejected_by_gateway():
    token = ts.issue_token(_assertion(req_id="req_gw_002"))
    ts.revoke_jti(token.jti)
    with pytest.raises(GatewayDenied) as exc:
        validate_token(token.jwt, requested_scope="policy_terms:read")
    assert exc.value.reason_code == "GATEWAY-REVOKED"


def test_security_replay_after_req_id_revoked_rejected_by_gateway():
    """S08 in docs/use-case.md: "An agent replays an expired token" ->
    "Access denied; gateway rejects; jti logged, token never logged." Here:
    a still-cryptographically-valid, unexpired token is replayed after its
    req_id reached a terminal state — the gateway must still refuse it."""
    token = ts.issue_token(_assertion(req_id="req_gw_003"))
    assert validate_token(token.jwt, requested_scope="policy_terms:read")  # valid before revocation
    ts.revoke_req_id("req_gw_003")  # claim reaches a terminal state
    with pytest.raises(GatewayDenied) as exc:
        validate_token(token.jwt, requested_scope="policy_terms:read")  # replay attempt
    assert exc.value.reason_code == "GATEWAY-REVOKED"


# --- Step 5: wrong scope ---

def test_security_scope_mismatch_rejected():
    """A token minted for policy_terms:read must not authorize a
    claims:read request, even though both were issued to the same agent
    in the same request."""
    token = ts.issue_token(_assertion(scope="policy_terms:read"))
    with pytest.raises(GatewayDenied) as exc:
        validate_token(token.jwt, requested_scope="claims:read")
    assert exc.value.reason_code == "GATEWAY-SCOPE-MISMATCH"


# --- Step 6: row binding ("wrong claim") ---

def test_security_row_binding_wrong_claim_rejected():
    token = ts.issue_token(_assertion(scope="claims:read", claim_id="CLM-2026-000001"))
    claims = validate_token(token.jwt, requested_scope="claims:read")
    with pytest.raises(GatewayDenied) as exc:
        check_row_binding(claims, row_claim_id="CLM-2026-999999")  # a different claim
    assert exc.value.reason_code == "GATEWAY-ROW-BINDING"


def test_security_row_binding_matching_claim_allowed():
    token = ts.issue_token(_assertion(scope="claims:read", claim_id="CLM-2026-000001"))
    claims = validate_token(token.jwt, requested_scope="claims:read")
    check_row_binding(claims, row_claim_id="CLM-2026-000001")  # no raise


def test_security_row_binding_requires_claim_id_on_token():
    """A token with no claim_id claim (e.g. supervisor-level or a
    pseudonymised-scope token) must not be usable to bind to an arbitrary row."""
    token = ts.issue_token(_assertion(scope="claims:read"))  # no claim_id
    claims = validate_token(token.jwt, requested_scope="claims:read")
    with pytest.raises(GatewayDenied) as exc:
        check_row_binding(claims, row_claim_id="CLM-2026-000001")
    assert exc.value.reason_code == "GATEWAY-NO-CLAIM-BINDING"


# --- Step 7: allowlist leakage ---

def test_security_allowlist_strips_disallowed_fields():
    """coverage's policyholders:read_limited must never leak name/contact
    (security-matrix.md §3) even if the underlying row has them."""
    full_row = {
        "policy_number": "KHA-SIL-004512", "name": "Priya Raman",
        "contact": "priya.raman@example.com", "plan": "Silver",
        "sum_insured": 500_000, "start_date": "2025-08-01",
    }
    filtered = filter_to_allowlist(full_row, scope="policyholders:read_limited")
    assert "name" not in filtered
    assert "contact" not in filtered
    assert filtered == {"plan": "Silver", "sum_insured": 500_000, "start_date": "2025-08-01"}


def test_security_allowlist_nested_member_fields():
    row = {"member": {"member_id": "MEM-004512-01", "age": 34, "name": "Priya Raman"}}
    filtered = filter_to_allowlist(row, scope="policyholders:read_limited")
    assert filtered == {"member": {"member_id": "MEM-004512-01", "age": 34}}
    assert "name" not in filtered["member"]


def test_security_allowlist_per_agent_for_claims_read():
    """medical_reviewer's claims:read allowlist must never include claimed_amount
    or assessment (security-matrix.md §3: medical_reviewer only gets
    claim_id, admission_date, discharge_date, stated_illness)."""
    row = {
        "claim_id": "CLM-2026-018833", "admission_date": "2026-09-10",
        "discharge_date": "2026-09-13", "stated_illness": "Dengue fever",
        "claimed_amount": 38_500, "assessment": {"payable": 37_300},
    }
    filtered = filter_to_allowlist(row, scope="claims:read", agent="medical_reviewer")
    assert "claimed_amount" not in filtered
    assert "assessment" not in filtered
    assert filtered["stated_illness"] == "Dengue fever"


def test_security_pseudonymised_scope_strips_pii():
    """fraud's claims:read_pseudonymised must never see raw claim_id or PII
    fields like member names — only the pseudo ids and the allowlisted fields."""
    row = {
        "claim_id": "CLM-2026-018836", "claim_pseudo_id": "pseudo-abc123",
        "person_pseudo_id": "pseudo-def456", "policyholder_name": "Rahul Verma",
        "hospital_id": "HOSP-002", "admission_date": "2026-09-15",
        "discharge_date": "2026-09-17", "claimed_amount": 15_000,
        "doc_hashes": ["S04-duplicate-bill-hash"], "status": "submitted",
    }
    filtered = filter_to_allowlist(row, scope="claims:read_pseudonymised")
    assert "claim_id" not in filtered  # raw id must not leak
    assert "policyholder_name" not in filtered
    assert filtered["claim_pseudo_id"] == "pseudo-abc123"
