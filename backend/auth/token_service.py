"""Token service core: issue, verify, revoke.

Implements docs/architecture.md §6 (tool-call enforcement path) steps
"G->T: signed AGT identity assertion" through "T-->G: JWT", and
docs/security-matrix.md §5 (JWT claims), §6 (gateway validation checklist —
the issuing side of it), and §11 (identity, trust gating).

M3: `verify_identity_assertion` now verifies a real Ed25519 signature via
governance.identity (agentmesh.identity.SoftwareKeyStore under the hood),
replacing M2's shape-and-staleness-only stub. `signature` on IdentityAssertion
is now real signature bytes, produced by governance.identity.sign_assertion —
see that module's docstring for why the AGT identity system is wired this way.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import jwt

from governance.identity import SignedAssertion, verify_assertion

from .keys import ACTIVE_KID, active_private_key
from .matrix import agent_allowed_scope, trust_threshold_for_scope, ttl_for_scope

ISSUER = "claimguard-token-service"
AUDIENCE = "data-gateway"
IDENTITY_ASSERTION_MAX_AGE_SECONDS = 30  # security-matrix.md §11.1


class TokenServiceError(Exception):
    """Base for all refusals. `reason_code` matches a rule id from
    docs/security-matrix.md so callers/tests/audit can key off it."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        self.message = message
        super().__init__(f"{reason_code}: {message}")


class IdentityRefused(TokenServiceError):
    """ID-001: identity assertion missing, invalid, or stale."""


class ScopeDenied(TokenServiceError):
    """GOV-003: requested scope not in matrix for this agent."""


class TrustRefused(TokenServiceError):
    """TRUST-001: agent trust score below scope threshold."""


class DelegationWidened(TokenServiceError):
    """A delegated request asked for a scope its parent doesn't itself hold —
    "delegation never widens access" (docs/CLAUDE.md invariant 5)."""


# --- In-memory revocation + trust state (M2 scope) ---
# A real deployment would back this with Postgres/Redis so it survives a
# restart and is shared across replicas; for M2 (single process, local dev)
# an in-memory set is enough to prove the revoke-by-jti/req_id behaviour the
# tests check. Swapping the store is an implementation detail behind the
# functions below, not a change to their interface.
_revoked_jti: set[str] = set()
_revoked_req_id: set[str] = set()
_trust_scores: dict[str, int] = {}  # keyed "agent:req_id", per security-matrix.md §11.2
DEFAULT_TRUST_SCORE = 1000


@dataclass
class IdentityAssertion:
    """What the AGT adapter sends the token service to request a token.
    Field names match docs/security-matrix.md §11.1: "agent id, req_id,
    requested scope, timestamp, signed with the agent's AGT key".

    `signature`: real Ed25519 signature bytes over (agent_id, req_id, scope,
    timestamp), produced by governance.identity.sign_assertion. Empty bytes
    (the default) will always fail verify_identity_assertion's signature
    check below — callers must sign for real, there is no unsigned path.
    """

    agent_id: str
    req_id: str
    scope: str
    timestamp: float
    signature: bytes = b""
    parent: str | None = None
    claim_id: str | None = None


@dataclass
class IssuedToken:
    jwt: str
    jti: str
    exp: int
    kid: str


def verify_identity_assertion(assertion: IdentityAssertion) -> None:
    """ID-001: "Unknown agent, bad signature, or stale timestamp (> 30s) ->
    refuse" (security-matrix.md §11.1). Shape/staleness checks first (cheap,
    no crypto needed), then the real Ed25519 signature via governance.identity —
    an agent whose signature doesn't verify is refused exactly like one with
    a missing/stale assertion, since both mean "we can't trust this identity"."""
    if not assertion.agent_id or not assertion.req_id or not assertion.scope:
        raise IdentityRefused("ID-001", "identity assertion missing required fields")
    age = time.time() - assertion.timestamp
    if age > IDENTITY_ASSERTION_MAX_AGE_SECONDS:
        raise IdentityRefused("ID-001", f"identity assertion stale ({age:.1f}s > {IDENTITY_ASSERTION_MAX_AGE_SECONDS}s)")
    if age < -5:  # small clock-skew allowance for a timestamp claiming to be in the future
        raise IdentityRefused("ID-001", "identity assertion timestamp is in the future")

    signed = SignedAssertion(
        agent_id=assertion.agent_id, req_id=assertion.req_id,
        scope=assertion.scope, timestamp=assertion.timestamp, signature=assertion.signature,
    )
    if not verify_assertion(signed):
        raise IdentityRefused("ID-001", f"signature verification failed for agent {assertion.agent_id!r}")


def get_trust_score(agent_id: str, req_id: str) -> int:
    """Trust is scoped per agent per request (security-matrix.md §11.2:
    "so one bad claim doesn't lock an agent out of every other claim")."""
    return _trust_scores.get(f"{agent_id}:{req_id}", DEFAULT_TRUST_SCORE)


def penalize_trust(agent_id: str, req_id: str, amount: int = 200) -> int:
    """Called by the AGT adapter (M3) when a denial is reported against this
    agent/request. Exposed here now so M3 has a stable function to call."""
    key = f"{agent_id}:{req_id}"
    new_score = max(0, get_trust_score(agent_id, req_id) - amount)
    _trust_scores[key] = new_score
    return new_score


def issue_token(assertion: IdentityAssertion, parent_scopes: set[str] | None = None) -> IssuedToken:
    """The full chain from docs/architecture.md §6: verify identity -> check
    matrix (GOV-003) -> check trust (TRUST-001) -> check delegation ceiling ->
    mint a scoped, short-lived JWT.

    `parent_scopes`: if this assertion has a `parent`, the parent's own
    granted scopes for this req_id — used to enforce "delegation never
    widens access" (docs/CLAUDE.md invariant 5). None means this is a
    top-level request (e.g. supervisor), not a delegated one.
    """
    verify_identity_assertion(assertion)

    if not agent_allowed_scope(assertion.agent_id, assertion.scope):
        raise ScopeDenied("GOV-003", f"{assertion.agent_id!r} is not permitted scope {assertion.scope!r}")

    if assertion.parent is not None:  # noqa: SIM102 - kept nested: "is this delegated" and
        if parent_scopes is None or assertion.scope not in parent_scopes:  # "is the delegation valid" read as two separate questions, not one
            raise DelegationWidened(
                "GOV-003",
                f"delegated scope {assertion.scope!r} exceeds parent {assertion.parent!r}'s granted scopes",
            )

    threshold = trust_threshold_for_scope(assertion.scope)
    score = get_trust_score(assertion.agent_id, assertion.req_id)
    if score < threshold:
        raise TrustRefused(
            "TRUST-001",
            f"{assertion.agent_id!r} trust score {score} below threshold {threshold} for scope {assertion.scope!r}",
        )

    ttl = ttl_for_scope(assertion.scope)
    now = int(time.time())
    jti = str(uuid.uuid4())

    claims: dict = {
        "iss": ISSUER,
        "sub": f"agent:{assertion.agent_id}",
        "aud": AUDIENCE,
        "scope": assertion.scope,
        "req_id": assertion.req_id,
        "jti": jti,
        "iat": now,
        "exp": now + ttl,
        "kid": ACTIVE_KID,
    }
    if assertion.claim_id is not None:
        claims["claim_id"] = assertion.claim_id
    if assertion.parent is not None:
        claims["parent"] = f"agent:{assertion.parent}"

    token = jwt.encode(claims, active_private_key(), algorithm="EdDSA", headers={"kid": ACTIVE_KID})
    return IssuedToken(jwt=token, jti=jti, exp=claims["exp"], kid=ACTIVE_KID)


def revoke_jti(jti: str) -> None:
    _revoked_jti.add(jti)


def revoke_req_id(req_id: str) -> None:
    """security-matrix.md §4: "Tokens for a req_id are revoked when the
    request reaches a terminal or pending_human state, even if not yet
    expired." One req_id may have issued many tokens across many agents;
    this revokes all of them at once without tracking each jti individually."""
    _revoked_req_id.add(req_id)


def is_revoked(jti: str, req_id: str) -> bool:
    return jti in _revoked_jti or req_id in _revoked_req_id


def decode_unverified(token: str) -> dict:
    """Reads claims without verifying signature/expiry — used by the gateway
    only to look up which `kid`'s public key to verify with. Never trust the
    output of this for an access decision."""
    return jwt.decode(token, options={"verify_signature": False})
