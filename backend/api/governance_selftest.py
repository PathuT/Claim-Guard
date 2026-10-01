"""Governance self-test endpoints (docs/use-case.md §8: S07, S08 — attack
attempts against the governance layer itself, not a claim reaching a
particular final state).

These drive the REAL token-issuance and gateway-validation codepaths
(auth.token_service.issue_token, data_gateway's validate_token) directly,
the same functions M2/M3's own security tests
(tests/test_security_token_service.py, tests/test_security_gateway.py)
already exercise at the unit level — this module exists so Harbor's S07/S08
tasks (and any operator wanting to smoke-test a running deployment) can
verify the same invariants end-to-end, over real HTTP, against the actual
running token service and data gateway processes, not just in-process.

Both endpoints are read/probe-only: they attempt exactly the denied action
and report the verdict, never a bypass. A self-test that itself succeeded in
the attack would be the actual security bug — these exist to prove it can't.
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from governance.identity import sign_assertion

router = APIRouter(prefix="/_governance", tags=["governance-selftest"])

TOKEN_SERVICE_URL = "http://localhost:8100"
DATA_GATEWAY_URL = "http://localhost:8200"


class ScopeMatrixProbeResult(BaseModel):
    scenario: str
    attempted_agent_id: str
    attempted_scope: str
    denied: bool
    reason_code: str | None = None
    http_status: int | None = None
    detail: str


class TokenReplayProbeResult(BaseModel):
    scenario: str
    issued_jti: str
    ttl_seconds: int
    waited_seconds: float
    denied: bool
    reason_code: str | None = None
    http_status: int | None = None
    detail: str


@router.post("/probe/scope-matrix", response_model=ScopeMatrixProbeResult)
def probe_scope_matrix() -> ScopeMatrixProbeResult:
    """S07: the coverage agent attempts (e.g. via a prompt-injection
    instruction) to request medical_records:read directly — a scope
    docs/security-matrix.md §2 marks "-" for coverage. Signs a REAL identity
    assertion as `coverage` requesting that scope and submits it to the
    real, running token service's POST /tokens; the token service must
    refuse it with GOV-003 before any JWT is ever minted (docs/engineering-guide.md
    invariant: an out-of-matrix scope is refused at issuance, never merely
    filtered later)."""
    req_id = f"selftest-s07-{int(time.time() * 1000)}"
    assertion = sign_assertion(agent_id="coverage", req_id=req_id, scope="medical_records:read")

    with httpx.Client(timeout=10.0) as client:
        response = client.post(
            f"{TOKEN_SERVICE_URL}/tokens",
            json={
                "agent_id": "coverage",
                "req_id": req_id,
                "scope": "medical_records:read",
                "timestamp": assertion.timestamp,
                "signature": __import__("base64").b64encode(assertion.signature).decode(),
            },
        )

    if response.status_code == 200:
        # The attack succeeded — a real, usable token was minted. This is
        # the failure case S07 exists to catch, reported plainly rather
        # than raised, so the verifier can score it as a real failure
        # instead of the probe itself crashing.
        return ScopeMatrixProbeResult(
            scenario="S07", attempted_agent_id="coverage", attempted_scope="medical_records:read",
            denied=False, http_status=response.status_code,
            detail="token service issued a usable token for an out-of-matrix scope — GOV-003 did not fire",
        )

    detail_body = response.json().get("detail", {}) if response.headers.get("content-type", "").startswith("application/json") else {}
    reason_code = detail_body.get("reason_code") if isinstance(detail_body, dict) else None
    return ScopeMatrixProbeResult(
        scenario="S07", attempted_agent_id="coverage", attempted_scope="medical_records:read",
        denied=True, reason_code=reason_code, http_status=response.status_code,
        detail=detail_body.get("message", response.text) if isinstance(detail_body, dict) else response.text,
    )


@router.post("/probe/token-replay", response_model=TokenReplayProbeResult)
def probe_token_replay() -> TokenReplayProbeResult:
    """S08: an agent replays an expired token against the data gateway.
    Issues a REAL, validly-signed, validly-scoped token for `payout`
    requesting `bank_details:read` (60s TTL — the shortest configured scope,
    security-matrix.md §4, chosen so this probe doesn't need to sleep
    minutes), waits past its expiry, then submits it to the real, running
    data gateway's POST /query. The gateway must refuse with
    GATEWAY-EXPIRED; the jti is logged by the gateway's own tracing, the
    token's raw bytes never are (docs/architecture.md's own "token never
    logged" invariant — this probe doesn't log the token either, only its
    jti, matching that discipline)."""
    req_id = f"selftest-s08-{int(time.time() * 1000)}"
    scope = "bank_details:read"
    # A real, already-seeded claim_id (S01's) so the gateway's claim ->
    # policy_number binding for bank_details:read resolves cleanly — this
    # probe is isolating the EXPIRY check alone, not also exercising
    # GATEWAY-NO-CLAIM-BINDING, which is a different rule with its own
    # coverage elsewhere (tests/test_security_gateway.py).
    probe_claim_id = "CLM-2026-018833"
    assertion = sign_assertion(agent_id="payout", req_id=req_id, scope=scope)

    with httpx.Client(timeout=10.0) as client:
        issue_response = client.post(
            f"{TOKEN_SERVICE_URL}/tokens",
            json={
                "agent_id": "payout",
                "req_id": req_id,
                "scope": scope,
                "timestamp": assertion.timestamp,
                "signature": __import__("base64").b64encode(assertion.signature).decode(),
                "claim_id": probe_claim_id,
            },
        )
        issue_response.raise_for_status()
        issued = issue_response.json()
        jti = issued["jti"]
        exp = issued["exp"]

        wait_seconds = max(0.0, exp - time.time()) + 7.0  # past exp AND clear of the gateway's own 5s clock-skew leeway (CLOCK_SKEW_SECONDS in data_gateway/gateway.py) — waiting only past exp itself isn't enough, since PyJWT's leeway= means the token still validates for up to 5s after exp
        time.sleep(wait_seconds)

        replay_response = client.post(
            f"{DATA_GATEWAY_URL}/query",
            headers={"Authorization": f"Bearer {issued['token']}", "X-Agent-Id": "payout"},
            json={"scope": scope, "claim_id": probe_claim_id},
        )

    if replay_response.status_code == 200:
        return TokenReplayProbeResult(
            scenario="S08", issued_jti=jti, ttl_seconds=exp - int(assertion.timestamp),
            waited_seconds=wait_seconds, denied=False, http_status=replay_response.status_code,
            detail="gateway accepted an expired token — GATEWAY-EXPIRED did not fire",
        )

    detail_body = replay_response.json().get("detail", {}) if replay_response.headers.get("content-type", "").startswith("application/json") else {}
    reason_code = detail_body.get("reason_code") if isinstance(detail_body, dict) else None
    return TokenReplayProbeResult(
        scenario="S08", issued_jti=jti, ttl_seconds=exp - int(assertion.timestamp),
        waited_seconds=wait_seconds, denied=True, reason_code=reason_code, http_status=replay_response.status_code,
        detail=detail_body.get("message", replay_response.text) if isinstance(detail_body, dict) else replay_response.text,
    )
