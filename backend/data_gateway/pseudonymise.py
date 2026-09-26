"""Pseudonymisation for `claims:read_pseudonymised` (fraud agent only).

docs/architecture.md §10: "Pseudonymisation uses a keyed hash (HMAC with a
secret the fraud agent never has), so the same person maps to the same
pseudonym across claims without being reversible." docs/security-matrix.md
§10: "Pseudonymisation HMAC key only in the data gateway" — this module is
the only place PSEUDONYMISATION_HMAC_KEY is read; fraud never sees it,
directly or via any tool result (a hash it can't invert or key-guess is
exactly as good as never having the key for fraud's purposes).

Deterministic (same input -> same pseudonym) so the fraud agent can still
notice "this claim_id and that claim_id map to the same person_pseudo_id"
across two separate claims (S04's duplicate-claim scenario needs this), but
not deterministic across a *different* key (no other service could recompute
the same pseudonym without this key, even knowing the algorithm).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_HMAC_KEY_ENV = "PSEUDONYMISATION_HMAC_KEY"


def _hmac_key() -> bytes:
    raw = os.environ.get(_HMAC_KEY_ENV)
    if not raw:
        # Fail closed rather than falling back to a hardcoded key: a missing
        # key here would otherwise silently produce a *reversible* "pseudonym"
        # if some future default were guessable, defeating the whole point.
        raise RuntimeError(f"{_HMAC_KEY_ENV} is not set — pseudonymisation cannot run without it")
    return bytes.fromhex(raw)


def pseudonymise(value: str, *, salt: str) -> str:
    """`salt` namespaces the hash so claim_id and policy_number pseudonyms
    (different identifier spaces) never collide even for coincidentally
    equal underlying strings."""
    digest = hmac.new(_hmac_key(), f"{salt}:{value}".encode(), hashlib.sha256).hexdigest()
    return digest[:24]  # short pseudonym is enough; full 64 hex chars is unwieldy for no benefit


def pseudonymise_claim_row(row: dict) -> dict:
    """Replaces claim_id/policy_number with keyed-hash pseudonyms and drops
    every field not in the claims:read_pseudonymised allowlist (member_id,
    stated_illness, and any other PII-adjacent field is dropped entirely,
    not just claim_id/policy_number — docs/architecture.md §10: "drops PII
    fields entirely", not just the two identifiers named in the field list).
    """
    return {
        "claim_pseudo_id": pseudonymise(row["claim_id"], salt="claim_id"),
        "person_pseudo_id": pseudonymise(row["policy_number"], salt="policy_number"),
        "hospital_id": row.get("hospital_id"),
        "admission_date": row.get("admission_date"),
        "discharge_date": row.get("discharge_date"),
        "claimed_amount": row.get("claimed_amount"),
        "doc_hashes": row.get("doc_hashes"),
        "status": row.get("status"),
    }
