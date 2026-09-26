"""Ed25519 signing key management for the token service.

docs/security-matrix.md §10: "Token service Ed25519 key pair; private key only
in token-service container; kid rotation supported (old key kept for
validation until its tokens expire)."

M2 scope: a single active key, generated at process start if TOKEN_SERVICE_PRIVATE_KEY
isn't set, or loaded from it. Multi-key rotation (keeping old keys around for
JWKS validation after a new one is promoted) is a real feature this module
supports via `KEYS` being a dict, but the *rotation trigger* (promoting a new
key, retiring an old one) isn't built until it's actually needed.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from dotenv import load_dotenv

# Load .env explicitly here rather than assuming some other already-imported
# module did it first. Relying on import order silently produced a real bug:
# TOKEN_SERVICE_PRIVATE_KEY read as unset (falling back to a fresh random
# key) whenever this module happened to load before whatever else called
# load_dotenv() — which broke cross-process signature verification between
# the token service and the gateway even with the env var correctly set.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

ACTIVE_KID = "ts-2026-09"


def _generate_key_pair() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


def _load_or_generate() -> tuple[bytes, bytes]:
    """Loads TOKEN_SERVICE_PRIVATE_KEY (PEM, base64-encoded, from .env) if
    set; otherwise generates an ephemeral key pair. An ephemeral key is fine
    for local dev (docs/CLAUDE.md: secrets from env vars) but means tokens
    don't survive a process restart with an unset key — expected for M2."""
    raw = os.environ.get("TOKEN_SERVICE_PRIVATE_KEY")
    if raw:
        priv_pem = base64.b64decode(raw)
        priv = serialization.load_pem_private_key(priv_pem, password=None)
        if not isinstance(priv, Ed25519PrivateKey):
            raise ValueError("TOKEN_SERVICE_PRIVATE_KEY is not an Ed25519 key")
        pub_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return priv_pem, pub_pem
    return _generate_key_pair()


_PRIVATE_PEM, _PUBLIC_PEM = _load_or_generate()

# kid -> public key PEM. Every issued token's `kid` header must be a key in
# here for the gateway to validate it (security-matrix.md §6.1).
KEYS: dict[str, bytes] = {ACTIVE_KID: _PUBLIC_PEM}


def active_private_key() -> bytes:
    return _PRIVATE_PEM


def public_key_for(kid: str) -> bytes | None:
    return KEYS.get(kid)


def _b64url_uint(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def jwks() -> dict:
    """JWKS document (RFC 7517) for OKP/Ed25519 keys, so the gateway (or any
    external verifier) can fetch public keys without a shared secret."""
    pub = serialization.load_pem_public_key(_PUBLIC_PEM)
    assert isinstance(pub, Ed25519PublicKey)
    return {
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "kid": ACTIVE_KID,
                "use": "sig",
                "alg": "EdDSA",
                "x": _b64url_uint(pub),
            }
        ]
    }
