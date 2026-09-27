"""GET /system/facts — every figure the console states about the system,
computed from the running system instead of typed into the UI.

- agents and workflow: the objects registered in Agno AgentOS (model id included);
- policy rules: governance/rules.py's ALL_RULES registry plus the checks the
  adapter and token service enforce themselves;
- scopes, token lifetimes and trust thresholds: auth/matrix.py;
- data: row counts in Postgres, and documents the injection scan flags;
- tests: the last pytest run's JUnit report (backend/.reports/pytest.xml);
- Harbor: the S01-S10 scoreboard and the per-claim checks;
- outcomes: measured over the assessed claims and the audit log.

Nothing here is an estimate; a figure that can't be computed is null.
"""

from __future__ import annotations

import json
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import func, select

from api.claim_intake import scan_injection_markers
from auth.matrix import AGENT_SCOPES, DEFAULT_TTL_SECONDS, trust_threshold_for_scope, ttl_for_scope
from data_gateway.db import get_session
from data_gateway.models import Claim, ClaimDocument, Hospital, Policyholder, PolicyTerm
from governance.rules import ALL_RULES
from governance.tool_allowlist import TOOL_CALL_BUDGET_PER_REQUEST

router = APIRouter()

TEST_REPORT = Path(__file__).resolve().parents[1] / ".reports" / "pytest.xml"
DECIDED = {"paid", "auto_approved", "pending_human", "approved", "approved_partial", "rejected", "needs_resubmission"}


def _rules() -> list[dict]:
    """ALL_RULES function names carry the rule id and what must hold
    (pay_001_amount_matches_assessment -> PAY-001). The other five are
    enforced before those rules run, by the adapter and the token service."""
    rules = [
        {"id": "GOV-001", "must_hold": "Tool is in the agent's allowlist", "enforced_by": "governance adapter"},
        {"id": "GOV-002", "must_hold": f"At most {TOOL_CALL_BUDGET_PER_REQUEST} tool calls per request", "enforced_by": "governance adapter"},
        {"id": "GOV-003", "must_hold": "Scope is in the agent × collection matrix", "enforced_by": "token service"},
        {"id": "ID-001", "must_hold": "Signed Ed25519 identity assertion, at most 30 s old", "enforced_by": "token service"},
        {"id": "TRUST-001", "must_hold": "Agent trust score meets the scope's threshold", "enforced_by": "token service"},
    ]
    for rule in ALL_RULES:
        prefix, number, *words = rule.__name__.split("_")
        rules.append({
            "id": f"{prefix.upper()}-{number}",
            "must_hold": " ".join(words).capitalize(),
            "enforced_by": "governance/rules.py",
        })
    return sorted(rules, key=lambda r: (r["id"].split("-")[0], r["id"]))


def _agents() -> tuple[list[dict], dict | None]:
    from api import agentos  # the running app's registered AgentOS objects

    os_ = agentos.agent_os
    agents = []
    for agent in os_.agents or []:
        model = getattr(agent, "model", None)
        name = agent.name or ""
        agents.append({
            "name": name,
            "model": getattr(model, "id", None),
            "provider": getattr(model, "provider", None) or (type(model).__name__ if model else None),
            "scopes": [
                {"scope": s, "ttl_s": ttl_for_scope(s), "min_trust": trust_threshold_for_scope(s)}
                for s in sorted(AGENT_SCOPES.get(name, set()))
            ],
        })
    workflow = None
    if os_.workflows:
        wf = os_.workflows[0]
        steps = []
        for step in wf.steps or []:
            steps.append(step.name)
            for inner in getattr(step, "steps", None) or []:
                steps.append(f"{step.name} → {inner.name}")
            for inner in getattr(step, "else_steps", None) or []:
                steps.append(f"{step.name} else → {inner.name}")
        workflow = {"id": wf.id, "name": wf.name, "steps": steps}
    return agents, workflow


def _tests() -> dict | None:
    if not TEST_REPORT.exists():
        return None
    root = ET.parse(TEST_REPORT).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return None
    total = int(suite.get("tests", 0))
    failed = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    return {
        "total": total, "passed": total - failed - skipped, "failed": failed, "skipped": skipped,
        "ran_at": suite.get("timestamp") or datetime.fromtimestamp(TEST_REPORT.stat().st_mtime, tz=timezone.utc).isoformat(),
    }


def _audit() -> dict:
    from governance.flight_recorder import get_recorder

    recorder = get_recorder()
    logs = recorder.query_logs(limit=100_000)
    integrity = recorder.verify_integrity()
    rejections_allowed = rejections_refused = 0
    for entry in logs:
        if entry.get("tool_name") != "set_claim_state":
            continue
        args = entry.get("tool_args")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict) or args.get("new_state") != "rejected":
            continue
        if entry.get("policy_verdict") == "allowed":
            rejections_allowed += 1
        else:
            rejections_refused += 1
    return {
        "entries": len(logs), "intact": bool(integrity.get("valid")),
        "allowed": sum(1 for e in logs if e.get("policy_verdict") == "allowed"),
        "refused": sum(1 for e in logs if e.get("policy_verdict") != "allowed"),
        # STATE-001: a rejection is allowed only with an officer decision record.
        "rejections_with_officer_decision": rejections_allowed,
        "ai_rejections_refused": rejections_refused,
    }


@router.get("/system/facts")
def system_facts() -> dict:
    db = get_session()
    try:
        data = {
            "policyholders": db.scalar(select(func.count()).select_from(Policyholder)),
            "claims": db.scalar(select(func.count()).select_from(Claim)),
            "hospitals": db.scalar(select(func.count()).select_from(Hospital)),
            "watchlisted_hospitals": db.scalar(select(func.count()).select_from(Hospital).where(Hospital.watchlist.is_(True))),
            "policy_clauses": db.scalar(select(func.count()).select_from(PolicyTerm)),
            "documents": db.scalar(select(func.count()).select_from(ClaimDocument)),
        }
        data["documents_with_hidden_instructions"] = sum(
            1 for text in db.scalars(select(ClaimDocument.extracted_text)) if scan_injection_markers(text or "")
        )
        claims = db.execute(select(Claim.status, Claim.assessment).where(Claim.assessment.is_not(None))).all()
    finally:
        db.close()

    # Only claims the agent workflow actually ran (it stores the intake
    # agent's output); the seeded history is not the agents' track record.
    ran = [(status, a) for status, a in claims if isinstance(a, dict) and "intake_summary" in a]
    processing = [a["processing_ms"] / 1000 for _, a in ran if isinstance(a.get("processing_ms"), (int, float))]
    deductions = [d for _, a in ran for d in (a.get("deductions") or [])]
    decided = [status for status, _ in ran if status in DECIDED]
    auto = sum(1 for s in decided if s in {"paid", "auto_approved"})

    from api.harbor_suite import get_suite, list_claim_checks

    suite = get_suite()
    checks = list_claim_checks(limit=1000)
    agents, workflow = _agents()
    ttls = [ttl_for_scope(s) for scopes in AGENT_SCOPES.values() for s in scopes] or [DEFAULT_TTL_SECONDS]

    return {
        "agents": agents,
        "workflow": workflow,
        "rules": _rules(),
        "token_ttl_s": {"max": max(ttls), "min": min(ttls)},
        # Every identity in the token service's matrix, including the payout
        # agent (governed code, not an LLM) and the supervisor (no data access).
        "scope_matrix": {
            agent: [{"scope": sc, "ttl_s": ttl_for_scope(sc), "min_trust": trust_threshold_for_scope(sc)} for sc in sorted(scopes)]
            for agent, scopes in AGENT_SCOPES.items()
        },
        "data": data,
        "tests": _tests(),
        "harbor": {
            "scenarios": len(suite.rows), "scored": suite.scored,
            "outcome_pass_rate": suite.outcome_pass_rate, "governance_pass_rate": suite.governance_pass_rate,
            "claim_checks": len(checks),
            "claim_checks_passed": sum(1 for c in checks if c.outcome == 1 and c.governance == 1),
        },
        "outcomes": {
            "claims_run_by_agents": len(ran),
            "seeded_history_claims": len(claims) - len(ran),
            "decided_claims": len(decided),
            "auto_decided": auto,
            "to_officer": sum(1 for s in decided if s == "pending_human"),
            "median_processing_s": round(statistics.median(processing), 1) if processing else None,
            "processing_samples": len(processing),
            "deductions": len(deductions),
            "deductions_with_clause": sum(1 for d in deductions if d.get("clause_id")),
        },
        "audit": _audit(),
    }
