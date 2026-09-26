"""Per-agent tool allowlist from docs/security-matrix.md §7. GOV-001: "Tool
not in agent's allowlist" -> deny, even if the tool exists at all.

Kept as data, mirroring auth/matrix.py's AGENT_SCOPES — same
single-source-of-truth discipline docs/CLAUDE.md asks for with the security
matrix.
"""

from __future__ import annotations

AGENT_TOOLS: dict[str, set[str]] = {
    "supervisor": {"delegate", "set_claim_state", "request_human_review"},
    "intake": {"read_claim_documents", "write_claim_items", "write_medical_facts"},
    "medical_reviewer": {"read_medical_record", "read_claim_basic", "submit_medical_finding"},
    "coverage": {"search_policy_terms", "read_policy_limited", "read_claim", "submit_assessment"},
    "fraud": {"search_claims_pseudonymised", "read_hospital", "submit_fraud_screen"},
    "payout": {"read_bank_details", "execute_payout"},
    # Not an autonomous agent — the human console role itself
    # (security-matrix.md §9: "claims_officer ... open full discharge
    # summary via audited break-glass (reason required)"). Reusing
    # check_and_audit()/GOV-001 for this one human action means a
    # break-glass access shows up in the exact same audit log a denied
    # agent tool call would (docs/plan.md M8's "audited break-glass"),
    # rather than needing a second, parallel logging path.
    "claims_officer": {"break_glass_discharge_summary_access"},
}

# GOV-002: per-request tool-call budget, "e.g. 40 calls" (security-matrix.md §8).
TOOL_CALL_BUDGET_PER_REQUEST = 40


def tool_allowed(agent: str, tool_name: str) -> bool:
    return tool_name in AGENT_TOOLS.get(agent, set())
