"""The agent x scope matrix, TTLs, and trust thresholds from
docs/security-matrix.md, as data. This is the single place the token service
reads them from, so — per docs/engineering-guide.md ("Keep security-matrix.md as the
single source of truth for scopes. Code ... must be derived from it, never
the other way round.") — a change to the matrix means editing this file to
match, never the reverse.
"""

from __future__ import annotations

# security-matrix.md §2 (agent x collection matrix, minus the "-" cells) and
# §7 (tool allowlist) collapsed into: which scopes can each agent request.
# "-" cells and unlisted combinations are simply absent here -> denied.
AGENT_SCOPES: dict[str, set[str]] = {
    "supervisor": set(),  # coordinates only; holds findings, never raw data
    "intake": {"claim_documents:read", "claims:write", "medical_records:write"},
    "medical_reviewer": {"medical_records:read", "claims:read"},
    "coverage": {"policy_terms:read", "claims:read", "policyholders:read_limited"},
    "fraud": {"claims:read_pseudonymised", "hospitals:read"},
    "payout": {"bank_details:read", "payments:write"},
}

# security-matrix.md §4
SCOPE_TTL_SECONDS: dict[str, int] = {
    "medical_records:read": 120,
    "medical_records:write": 120,
    "bank_details:read": 60,
    "payments:write": 60,
}
DEFAULT_TTL_SECONDS = 300

# security-matrix.md §11.2 — minimum trust score (0-1000) required per scope.
SCOPE_TRUST_THRESHOLD: dict[str, int] = {
    "medical_records:read": 700,
    "medical_records:write": 700,
    "bank_details:read": 800,
    "payments:write": 800,
}
DEFAULT_TRUST_THRESHOLD = 400

# security-matrix.md §3 — field allowlists. Keyed by (scope, agent) where the
# allowlist differs by requester; otherwise keyed by scope alone.
FIELD_ALLOWLISTS: dict[str, list[str]] = {
    "policyholders:read_limited": ["plan", "sum_insured", "start_date", "member.age", "member.member_id"],
    "claims:read_pseudonymised": [
        "claim_pseudo_id", "person_pseudo_id", "hospital_id", "admission_date",
        "discharge_date", "claimed_amount", "doc_hashes", "status",
    ],
    "bank_details:read": ["account_number", "ifsc"],
}
# claims:read has a different allowlist per requesting agent (security-matrix.md §3).
CLAIMS_READ_ALLOWLIST_BY_AGENT: dict[str, list[str]] = {
    "medical_reviewer": ["claim_id", "admission_date", "discharge_date", "stated_illness"],
    "coverage": ["claim_id", "member_id", "dates", "claimed_amount", "line_items", "status", "assessment"],
    "payout": ["claim_id", "member_id", "dates", "claimed_amount", "line_items", "status", "assessment"],
}

# M5: write-side field allowlists for the three `*:write` scopes — which
# fields a token holding that scope is permitted to *set*, mirroring
# FIELD_ALLOWLISTS' read-side restriction but for the write path
# (data_gateway's POST /write). Anything not listed here is silently
# dropped from the write payload before it reaches the ORM, the same
# fail-closed-by-omission discipline as the read allowlists.
WRITE_FIELD_ALLOWLISTS: dict[str, list[str]] = {
    "claims:write": ["line_items", "claimed_amount", "status", "assessment"],
    "medical_records:write": ["diagnosis_text", "icd10", "history", "treatment"],
    "payments:write": ["amount", "account_ref", "agt_decision_id"],
}


def agent_allowed_scope(agent: str, scope: str) -> bool:
    """GOV-003: "Requested scope not in matrix for this agent" -> deny."""
    return scope in AGENT_SCOPES.get(agent, set())


def ttl_for_scope(scope: str) -> int:
    return SCOPE_TTL_SECONDS.get(scope, DEFAULT_TTL_SECONDS)


def trust_threshold_for_scope(scope: str) -> int:
    return SCOPE_TRUST_THRESHOLD.get(scope, DEFAULT_TRUST_THRESHOLD)


def field_allowlist_for(scope: str, agent: str | None = None) -> list[str] | None:
    """Returns the allowed fields for a scope, or None if the scope grants
    full-row access (i.e. no allowlist restriction — still row-bound by
    docs/security-matrix.md §1, just not field-filtered)."""
    if scope == "claims:read" and agent in CLAIMS_READ_ALLOWLIST_BY_AGENT:
        return CLAIMS_READ_ALLOWLIST_BY_AGENT[agent]
    return FIELD_ALLOWLISTS.get(scope)


def write_allowlist_for(scope: str) -> list[str] | None:
    """M5: fields a `*:write` scope may set. None means "this scope has no
    write allowlist" (not currently reachable for any *:write scope — every
    one of them is deliberately restricted; absence is a modelling error,
    not an intentional full-row-write grant)."""
    return WRITE_FIELD_ALLOWLISTS.get(scope)
