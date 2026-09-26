"""Security tests for the token service (docs/plan.md M2):
"Tests first: expired, wrong audience, wrong scope, wrong claim, revoked,
replay, allowlist leakage." `make test-security` runs this file (and its
gateway counterpart) with no agents involved.

Naming convention: every test starts with `test_security_` so
`pytest -k security` (the `make test-security` target) selects exactly these.
"""

from __future__ import annotations

import time

import jwt
import pytest

from auth import token_service as ts
from auth.keys import public_key_for
from governance.identity import sign_assertion


def _assertion(agent_id="intake", scope="claim_documents:read", req_id="req_test_001", timestamp=None, **kwargs):
    """Builds a *real*, correctly signed IdentityAssertion — M3 wired real
    Ed25519 signature verification into verify_identity_assertion, so an
    unsigned/wrong-signature assertion is refused the same way a stale one
    is (see ID-001 tests below, which deliberately sign correctly and only
    vary agent_id/scope/req_id, keeping the signature check itself isolated
    to its own tests)."""
    ts_val = timestamp if timestamp is not None else time.time()
    signed = sign_assertion(agent_id, req_id, scope, ts_val)
    return ts.IdentityAssertion(
        agent_id=agent_id, scope=scope, req_id=req_id, timestamp=ts_val,
        signature=signed.signature, **kwargs,
    )


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test gets a clean revocation/trust-score slate — these are
    module-level in-memory stores (see token_service.py's own comment on
    why), so tests must not leak state into each other."""
    ts._revoked_jti.clear()
    ts._revoked_req_id.clear()
    ts._trust_scores.clear()
    yield
    ts._revoked_jti.clear()
    ts._revoked_req_id.clear()
    ts._trust_scores.clear()


# --- GOV-003: wrong / out-of-matrix scope ---

def test_security_wrong_scope_denied():
    """coverage may request policy_terms:read, never medical_records:read
    (security-matrix.md §2 — that cell is "-")."""
    with pytest.raises(ts.ScopeDenied) as exc:
        ts.issue_token(_assertion(agent_id="coverage", scope="medical_records:read"))
    assert exc.value.reason_code == "GOV-003"


def test_security_agent_allowed_its_own_scope():
    token = ts.issue_token(_assertion(agent_id="coverage", scope="policy_terms:read"))
    assert token.jwt


# --- ID-001: identity assertion missing / stale ---

def test_security_stale_identity_assertion_refused():
    stale = ts.IdentityAssertion(
        agent_id="intake", scope="claim_documents:read", req_id="req_test_002",
        timestamp=time.time() - 60,  # > IDENTITY_ASSERTION_MAX_AGE_SECONDS (30s)
    )
    with pytest.raises(ts.IdentityRefused) as exc:
        ts.issue_token(stale)
    assert exc.value.reason_code == "ID-001"


def test_security_missing_fields_identity_assertion_refused():
    bad = ts.IdentityAssertion(agent_id="", scope="claim_documents:read", req_id="req_test_003", timestamp=time.time())
    with pytest.raises(ts.IdentityRefused):
        ts.issue_token(bad)


def test_security_unsigned_assertion_refused():
    """M3: a well-formed, fresh assertion with no real signature (or a wrong
    one) must still be refused — shape and staleness alone are not enough."""
    unsigned = ts.IdentityAssertion(agent_id="intake", scope="claim_documents:read", req_id="req_test_003b", timestamp=time.time())
    with pytest.raises(ts.IdentityRefused) as exc:
        ts.issue_token(unsigned)
    assert exc.value.reason_code == "ID-001"
    assert "signature" in exc.value.message.lower()


def test_security_wrong_agent_signature_refused():
    """A signature valid for one agent must not verify for a different
    agent_id in the assertion (prevents an agent from impersonating another)."""
    signed_by_intake = sign_assertion("intake", "req_test_003c", "claim_documents:read")
    impersonating = ts.IdentityAssertion(
        agent_id="coverage",  # claims to be coverage...
        scope="claim_documents:read", req_id="req_test_003c", timestamp=signed_by_intake.timestamp,
        signature=signed_by_intake.signature,  # ...but the signature is intake's
    )
    with pytest.raises(ts.IdentityRefused) as exc:
        ts.issue_token(impersonating)
    assert exc.value.reason_code == "ID-001"


def test_security_unknown_agent_refused():
    """An unregistered agent_id has no keypair to sign with at all (AGT's
    SoftwareKeyStore.sign raises KeyError for it) — so the only way it could
    reach the token service is by presenting someone else's signature bytes
    under a fake name. That must still fail verification (no public key is
    registered for 'not_a_registered_agent' to check it against)."""
    real = sign_assertion("intake", "req_test_003d", "claim_documents:read")
    bad = ts.IdentityAssertion(
        agent_id="not_a_registered_agent", scope="claim_documents:read",
        req_id="req_test_003d", timestamp=real.timestamp, signature=real.signature,
    )
    with pytest.raises(ts.IdentityRefused):
        ts.issue_token(bad)


# --- TRUST-001: below-threshold trust score ---

def test_security_low_trust_score_refused_for_sensitive_scope():
    ts.penalize_trust("medical_reviewer", "req_test_004", amount=1000)  # drop to 0
    with pytest.raises(ts.TrustRefused) as exc:
        ts.issue_token(_assertion(agent_id="medical_reviewer", scope="medical_records:read", req_id="req_test_004"))
    assert exc.value.reason_code == "TRUST-001"


def test_security_low_trust_score_still_ok_for_low_threshold_scope():
    """Default threshold is 400; dropping by 200 from 1000 leaves 800, which
    still clears the default-threshold scopes even though it would fail the
    800-threshold ones (bank_details:read, payments:write)."""
    ts.penalize_trust("intake", "req_test_005", amount=200)
    token = ts.issue_token(_assertion(agent_id="intake", scope="claim_documents:read", req_id="req_test_005"))
    assert token.jwt


# --- Delegation never widens access ---

def test_security_delegation_cannot_widen_scope():
    """coverage requests a scope it IS allowed by the matrix (policy_terms:read),
    but its alleged parent's own granted scopes don't include it — so this
    must fail as a delegation-widening attempt (GOV-003), not slip through
    just because the matrix alone would have allowed it for coverage."""
    with pytest.raises(ts.DelegationWidened):
        ts.issue_token(
            _assertion(agent_id="coverage", scope="policy_terms:read", parent="supervisor"),
            parent_scopes={"claims:read"},  # parent never had policy_terms:read
        )


def test_security_delegation_widening_blocked_even_for_agents_own_valid_scope():
    """Distinguishes GOV-003 (scope not in the agent's own matrix row) from
    the delegation check: coverage is normally allowed medical_records:read?
    No — it isn't, by the matrix itself. This test uses a scope coverage IS
    allowed (policy_terms:read) to isolate the delegation check specifically,
    since test_security_delegation_cannot_widen_scope above could otherwise
    be satisfied by either check firing."""
    with pytest.raises(ts.DelegationWidened):
        ts.issue_token(
            _assertion(agent_id="coverage", scope="policy_terms:read", parent="fraud"),
            parent_scopes=set(),  # fraud has no policy_terms:read to delegate
        )


def test_security_delegation_within_parent_scope_allowed():
    token = ts.issue_token(
        _assertion(agent_id="coverage", scope="policy_terms:read", parent="supervisor"),
        parent_scopes={"policy_terms:read"},
    )
    assert token.jwt


# --- JWT shape / expiry / audience (security-matrix.md §5-6) ---

def test_security_issued_token_has_expected_claims():
    token = ts.issue_token(_assertion())
    claims = jwt.decode(
        token.jwt, public_key_for(token.kid), algorithms=["EdDSA"],
        audience=ts.AUDIENCE, issuer=ts.ISSUER,
    )
    assert claims["sub"] == "agent:intake"
    assert claims["aud"] == ts.AUDIENCE
    assert claims["iss"] == ts.ISSUER
    assert claims["scope"] == "claim_documents:read"
    assert claims["jti"] == token.jti
    assert claims["exp"] - claims["iat"] == 300  # default TTL


def test_security_sensitive_scope_gets_shorter_ttl():
    token = ts.issue_token(_assertion(agent_id="payout", scope="bank_details:read"))
    claims = jwt.decode(token.jwt, public_key_for(token.kid), algorithms=["EdDSA"], audience=ts.AUDIENCE, issuer=ts.ISSUER)
    assert claims["exp"] - claims["iat"] == 60  # security-matrix.md §4


def test_security_expired_token_rejected_on_decode():
    """Forges a token identical to a real one except iat/exp are both in the
    past, then confirms jwt.decode refuses it. (A negative `leeway` does NOT
    simulate "now is later" in PyJWT — it makes `iat` look like it's in the
    future instead and raises ImmatureSignatureError, not ExpiredSignatureError;
    forging the timestamps directly is the correct way to test this.)"""
    from auth.keys import ACTIVE_KID, active_private_key

    past = int(time.time()) - 3600
    claims = {
        "iss": ts.ISSUER, "sub": "agent:payout", "aud": ts.AUDIENCE,
        "scope": "bank_details:read", "req_id": "req_test_expired",
        "jti": "expired-test-jti", "iat": past - 60, "exp": past, "kid": ACTIVE_KID,
    }
    expired_jwt = jwt.encode(claims, active_private_key(), algorithm="EdDSA", headers={"kid": ACTIVE_KID})
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(expired_jwt, public_key_for(ACTIVE_KID), algorithms=["EdDSA"], audience=ts.AUDIENCE, issuer=ts.ISSUER)


def test_security_wrong_audience_rejected():
    token = ts.issue_token(_assertion())
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(
            token.jwt, public_key_for(token.kid), algorithms=["EdDSA"],
            audience="some-other-service", issuer=ts.ISSUER,
        )


def test_security_wrong_signing_key_rejected():
    """A token signed by our key must not verify against a different key —
    proves the signature is actually checked, not just present."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    token = ts.issue_token(_assertion())
    other_pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token.jwt, other_pub, algorithms=["EdDSA"], audience=ts.AUDIENCE, issuer=ts.ISSUER)


# --- Revocation (by jti and by req_id) ---

def test_security_revoked_jti_is_flagged():
    token = ts.issue_token(_assertion(req_id="req_test_010"))
    assert not ts.is_revoked(token.jti, "req_test_010")
    ts.revoke_jti(token.jti)
    assert ts.is_revoked(token.jti, "req_test_010")


def test_security_revoke_by_req_id_flags_every_token_for_it():
    """security-matrix.md §4: revoking by req_id must cover every token
    issued for that request, not just the last one — simulates a claim
    reaching a terminal state mid-flight with multiple outstanding tokens."""
    t1 = ts.issue_token(_assertion(agent_id="intake", scope="claim_documents:read", req_id="req_test_011"))
    t2 = ts.issue_token(_assertion(agent_id="coverage", scope="policy_terms:read", req_id="req_test_011"))
    ts.revoke_req_id("req_test_011")
    assert ts.is_revoked(t1.jti, "req_test_011")
    assert ts.is_revoked(t2.jti, "req_test_011")


def test_security_revocation_is_per_req_id_not_global():
    ts.issue_token(_assertion(req_id="req_test_012"))
    ts.revoke_req_id("req_test_012")
    t2 = ts.issue_token(_assertion(req_id="req_test_013"))
    assert not ts.is_revoked(t2.jti, "req_test_013")


# --- Replay: a token cannot be reused after its req_id is revoked, even
# though the JWT itself is still cryptographically valid and unexpired.
# This is exactly the "gateway rejects; jti logged, token never logged"
# behaviour S08 in docs/use-case.md describes -- the *gateway's* job (M2's
# other half) is to check is_revoked() on every request, which
# test_security_data_gateway.py covers. Here we only prove the token
# service's revoke bookkeeping is correct, which that check depends on.
def test_security_replay_after_terminal_state_is_revoked():
    token = ts.issue_token(_assertion(req_id="req_test_014"))
    ts.revoke_req_id("req_test_014")  # claim reached a terminal state
    assert ts.is_revoked(token.jti, "req_test_014")
