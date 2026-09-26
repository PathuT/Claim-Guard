"""Real AGT agent identity: registration, signing, and verification.

Replaces the M2 stub (auth/token_service.py's verify_identity_assertion,
which only checked shape/staleness) with real Ed25519 identity assertions,
per docs/security-matrix.md §11.1: "Every agent is registered with an AGT
identity (Ed25519 key pair) at startup... the AGT adapter sends the token
service a signed identity assertion... signed with the agent's AGT key. The
token service verifies the signature against the registered public key."

Uses agentmesh.identity.SoftwareKeyStore (confirmed real Ed25519
sign/verify/generate_keypair, part of the current agent-governance-toolkit-core
4.1.0 distribution — the `agentmesh` top-level import path is deprecated in
favor of the consolidated package name, but the code itself is current and
shipped; see M3 notes on this). SoftwareKeyStore keeps keys in memory only,
which matches this module's scope: real per-agent identities and signatures,
generated at process start, for a single local-dev process — a production
deployment would swap in one of AGT's other KeyStore backends (PKCS11,
TEEKeyStore) without changing this module's public interface.
"""

from __future__ import annotations

import base64
import json
import os
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import load_dotenv

with warnings.catch_warnings():
    # The `agentmesh` import path is deprecated in favor of importing from
    # agent_governance_toolkit_core directly, but no non-deprecated alias
    # exists yet for this specific module in v4.1.0 — silencing here only,
    # not globally, so a real deprecation elsewhere in this codebase would
    # still surface.
    warnings.simplefilter("ignore", DeprecationWarning)
    from agentmesh.identity import SoftwareKeyStore

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# The six ClaimGuard agents (docs/security-matrix.md §2), each gets its own
# registered identity at process start.
AGENT_IDS = ["supervisor", "intake", "medical_reviewer", "coverage", "fraud", "payout"]

_store = SoftwareKeyStore()
_public_keys: dict[str, bytes] = {}


def _seed_env_var(agent_id: str) -> str:
    return f"AGENT_IDENTITY_SEED_{agent_id.upper()}"


def _load_or_generate_private_key(agent_id: str) -> Ed25519PrivateKey:
    """Loads a persisted private key seed from .env if set, else generates a
    fresh one. Mirrors auth/keys.py's TOKEN_SERVICE_PRIVATE_KEY pattern —
    without persistence, each process that imports this module generates
    its own random identity per agent, so a signature made by one process
    (e.g. an agent process) can never verify in another (e.g. the token
    service process). Confirmed as a real bug in M3 the same way the M2
    signing-key mismatch was: found by testing the actual cross-process
    HTTP flow, not just in-process unit tests."""
    raw = os.environ.get(_seed_env_var(agent_id))
    if raw:
        seed = base64.b64decode(raw)
        return Ed25519PrivateKey.from_private_bytes(seed)
    return Ed25519PrivateKey.generate()


def _register_all() -> None:
    for agent_id in AGENT_IDS:
        if agent_id in _public_keys:
            continue
        private_key = _load_or_generate_private_key(agent_id)
        # SoftwareKeyStore has no "import an existing key" method (only
        # generate_keypair(), which is random-only) — writing directly into
        # its internal _keys dict is the only way to inject a persisted key.
        # This reaches past the public API deliberately, not accidentally;
        # if a future AGT version adds an import_keypair()-style method,
        # switch to it instead of this.
        _store._keys[agent_id] = private_key
        _public_keys[agent_id] = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )


_register_all()


@dataclass
class SignedAssertion:
    agent_id: str
    req_id: str
    scope: str
    timestamp: float
    signature: bytes


def _assertion_payload(agent_id: str, req_id: str, scope: str, timestamp: float) -> bytes:
    """Canonical byte representation signed and verified — sort_keys makes
    this deterministic regardless of construction order."""
    return json.dumps(
        {"agent_id": agent_id, "req_id": req_id, "scope": scope, "timestamp": timestamp},
        sort_keys=True,
    ).encode()


def sign_assertion(agent_id: str, req_id: str, scope: str, timestamp: float | None = None) -> SignedAssertion:
    """Called by the AGT adapter (on an agent's behalf) to produce the
    signed identity assertion sent to the token service."""
    ts = timestamp if timestamp is not None else time.time()
    payload = _assertion_payload(agent_id, req_id, scope, ts)
    signature = _store.sign(agent_id, payload)
    return SignedAssertion(agent_id=agent_id, req_id=req_id, scope=scope, timestamp=ts, signature=signature)


def verify_assertion(assertion: SignedAssertion) -> bool:
    """Called by the token service. Returns False for an unknown agent_id
    or a signature that doesn't match — never raises, so callers can turn
    both into the same ID-001 refusal, per security-matrix.md §11.1:
    "Unknown agent, bad signature, or stale timestamp (> 30 s) -> refuse."
    (Staleness is still auth/token_service.py's job, not this module's.)
    """
    public_key = _public_keys.get(assertion.agent_id)
    if public_key is None:
        return False
    payload = _assertion_payload(assertion.agent_id, assertion.req_id, assertion.scope, assertion.timestamp)
    return _store.verify(public_key, payload, assertion.signature)


def public_key_for_agent(agent_id: str) -> bytes | None:
    return _public_keys.get(agent_id)
