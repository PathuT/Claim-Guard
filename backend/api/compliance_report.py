"""`make compliance-report` (docs/plan.md M9, docs/compliance-mapping.md §4):
"generates a Markdown/HTML report for Divya containing: test results for
every row above, Harbor scoreboard (outcome + governance pass rates),
medical-data access summary (by agent and by officer break-glass), denied
actions by rule ID, audit chain integrity check result."

Run: `uv run python -m api.compliance_report` (from backend/), or
`make compliance-report` from the repo root. Writes
`backend/compliance_report.md`.

Every section here is generated from something REAL and currently
checkable in this repo — actual pytest results, the real running
FlightRecorder's own audit log, the real installed
agent_control_plane.FlightRecorder.verify_integrity() hash-chain check, and
the latest real Harbor job result.json if one exists. Nothing here is a
static/aspirational table: docs/compliance-mapping.md's own "Evidence /
test" column names tests that were never actually written under those
exact names (test_token_row_binding, test_audit_chain_integrity, etc. do
not exist as literal pytest function names) — this report maps each
compliance row to the REAL test names that exercise it instead (grouped by
the GOV/PAY/STATE/DATA rule_id embedded in each real test's own name,
tests/test_security_*.py), and says plainly when a section (e.g. the Harbor
scoreboard, if no run has completed yet) has no real data to report rather
than inventing a number.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
HARBOR_JOBS_DIR = REPO_ROOT / "evals" / "harbor" / "jobs"
OUTPUT_PATH = BACKEND_DIR / "compliance_report.md"

# --- Compliance-mapping.md's rows, mapped to the REAL rule_id prefix each
# one's actual test coverage lives under (tests/test_security_*.py test
# names all embed their rule_id: test_security_gov001_..., _pay003_...,
# _state002_..., _data001_...) — not the aspirational test names
# compliance-mapping.md itself lists, which were never written under those
# names. `scenarios` are the real S0X Harbor task ids that also exercise
# this row, from docs/use-case.md §8.
COMPLIANCE_ROWS: list[dict] = [
    {"framework": "DPDP 2023", "principle": "Purpose limitation", "rule_prefixes": ["data001"], "scenarios": ["S07"]},
    {"framework": "DPDP 2023", "principle": "Data minimisation", "rule_prefixes": ["data001", "data002"], "scenarios": ["S04"]},
    {"framework": "DPDP 2023", "principle": "Accuracy", "rule_prefixes": ["pay001"], "scenarios": ["S05"]},
    {"framework": "DPDP 2023", "principle": "Storage limitation", "rule_prefixes": [], "scenarios": [], "note": "Token revocation on terminal state is covered by tests/test_security_token_service.py's revocation tests; no scheduled cleanup job for synthetic data exists yet (docs/compliance-mapping.md's own aspiration, not yet built)."},
    {"framework": "DPDP 2023", "principle": "Security safeguards", "rule_prefixes": ["gov001", "gov002"], "scenarios": ["S08"]},
    {"framework": "DPDP 2023", "principle": "Accountability", "rule_prefixes": [], "scenarios": [], "note": "Hash-chain integrity — see the Audit Chain Integrity section below, and rule_ids on every decision — see Denied Actions below."},
    {"framework": "DPDP 2023", "principle": "Notice & rights (access, correction)", "rule_prefixes": [], "scenarios": ["S09"], "note": "Policyholder console view + resubmission path (M8); no automated test, verified via the Console's live policyholder page."},
    {"framework": "DPDP 2023", "principle": "Breach readiness", "rule_prefixes": [], "scenarios": [], "note": "Medical-data access report — see the Medical-Data Access Summary section below."},
    {"framework": "IRDAI (paraphrased)", "principle": "Clear reasons for deductions/rejections", "rule_prefixes": ["state001"], "scenarios": ["S01", "S03"]},
    {"framework": "IRDAI (paraphrased)", "principle": "Human accountable for rejection", "rule_prefixes": ["state001"], "scenarios": ["S03"]},
    {"framework": "IRDAI (paraphrased)", "principle": "Timely settlement", "rule_prefixes": [], "scenarios": ["S01"], "note": "No SLA timer is implemented in the console yet (docs/compliance-mapping.md's own aspiration)."},
    {"framework": "IRDAI (paraphrased)", "principle": "Fair, consistent decisions", "rule_prefixes": ["pay001", "pay002", "pay006"], "scenarios": []},
    {"framework": "OWASP Agentic", "principle": "Goal hijack / prompt injection", "rule_prefixes": [], "scenarios": ["S06"]},
    {"framework": "OWASP Agentic", "principle": "Tool misuse", "rule_prefixes": ["gov001", "data002"], "scenarios": ["S06", "S07"]},
    {"framework": "OWASP Agentic", "principle": "Identity & privilege abuse", "rule_prefixes": [], "scenarios": ["S07", "S08"]},
    {"framework": "OWASP Agentic", "principle": "Insecure inter-agent communication", "rule_prefixes": [], "scenarios": [], "note": "Schema-validated agent outputs (agents/schemas.py) — no dedicated test file; enforced structurally by Agno's output_schema, not a governance rule."},
    {"framework": "OWASP Agentic", "principle": "Cascading failures", "rule_prefixes": ["gov002"], "scenarios": []},
    {"framework": "OWASP Agentic", "principle": "Human-agent trust exploitation", "rule_prefixes": [], "scenarios": [], "note": "Officer console shows evidence/clause refs, not just a recommendation (M8) — verified live, no automated test."},
    {"framework": "OWASP Agentic", "principle": "Rogue agent behaviour", "rule_prefixes": ["gov001"], "scenarios": ["S06"]},
]


def run_tests() -> dict:
    """Runs the real backend test suite with --junitxml (pytest's own
    built-in reporter — no extra dependency needed) and returns
    {rule_prefix: {"passed": n, "failed": n, "tests": [names]}} plus an
    "_uncategorized" bucket for tests whose name doesn't embed a rule_id
    (e.g. observability/redaction tests)."""
    with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
        junit_path = Path(f.name)
    try:
        subprocess.run(
            [sys.executable, "-m", "pytest", "--junitxml", str(junit_path), "-q"],
            cwd=BACKEND_DIR, capture_output=True, text=True, check=False,
        )
        tree = ET.parse(junit_path)
    finally:
        junit_path.unlink(missing_ok=True)

    by_rule: dict[str, dict] = defaultdict(lambda: {"passed": 0, "failed": 0, "tests": []})
    for testcase in tree.getroot().iter("testcase"):
        name = testcase.get("name", "")
        failed = testcase.find("failure") is not None or testcase.find("error") is not None
        rule_prefix = _extract_rule_prefix(name)
        bucket = by_rule[rule_prefix]
        bucket["tests"].append(name)
        bucket["failed" if failed else "passed"] += 1
    return dict(by_rule)


def _extract_rule_prefix(test_name: str) -> str:
    """test_security_gov001_tool_not_in_allowlist_denied -> "gov001".
    test_security_pay003_high_value... -> "pay003". Falls back to
    "_uncategorized" for tests that don't embed one (e.g.
    test_medical_free_text_fully_redacted)."""
    parts = test_name.removeprefix("test_security_").split("_")
    if parts and any(parts[0].startswith(p) for p in ("gov", "pay", "state", "data")):
        return parts[0]
    return "_uncategorized"


def get_audit_summary() -> dict:
    """Real, live data from the actual running FlightRecorder — see
    governance/flight_recorder.py. Returns statistics, denied-by-rule-id
    counts, the integrity check result, and the medical-data access
    summary (by agent + by officer break-glass — see
    api/officer.py's break_glass_discharge_summary endpoint, the only
    place claims_officer/break_glass_discharge_summary_access entries
    come from)."""
    from governance.flight_recorder import get_recorder

    recorder = get_recorder()
    stats = recorder.get_statistics()
    integrity = recorder.verify_integrity()

    blocked_entries = recorder.query_logs(policy_verdict="blocked", limit=1000)
    denied_by_rule: dict[str, int] = defaultdict(int)
    for entry in blocked_entries:
        reason = entry.get("violation_reason") or ""
        rule_id = reason.split(":")[0].strip() if ":" in reason else (reason or "UNKNOWN")
        denied_by_rule[rule_id] += 1

    medical_reviewer_entries = recorder.query_logs(agent_id="medical_reviewer", limit=1000)
    break_glass_entries = [
        e for e in recorder.query_logs(agent_id="claims_officer", limit=1000)
        if e.get("tool_name") == "break_glass_discharge_summary_access"
    ]

    return {
        "stats": stats,
        "integrity": integrity,
        "denied_by_rule": dict(denied_by_rule),
        "medical_reviewer_access_count": len(medical_reviewer_entries),
        "break_glass_accesses": [
            {"trace_id": e["trace_id"], "timestamp": e["timestamp"], "tool_args": e.get("tool_args")}
            for e in break_glass_entries
        ],
    }


def get_harbor_scoreboard() -> dict | None:
    """Reads the MOST RECENT evals/harbor/jobs/*/result.json, if any exist.
    Returns None (not a fabricated 0%) when no Harbor job has ever
    completed — as of M9's own writing, every job in evals/harbor/jobs/
    predates the backend.Dockerfile build-context fix (docs/adr/006) and
    errored before any trial ran, so this legitimately returns None on a
    fresh clone until a real `harbor run` succeeds at least once."""
    if not HARBOR_JOBS_DIR.exists():
        return None
    job_dirs = sorted((d for d in HARBOR_JOBS_DIR.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    for job_dir in job_dirs:
        result_path = job_dir / "result.json"
        if not result_path.exists():
            continue
        data = json.loads(result_path.read_text())
        stats = data.get("stats", {})
        evals = stats.get("evals", {})
        for eval_name, eval_stats in evals.items():
            if eval_stats.get("n_trials", 0) > 0:
                return {"job_dir": job_dir.name, "eval_name": eval_name, **eval_stats}
    return None  # every job present errored before any trial completed


def render_report(test_results: dict, audit: dict, harbor: dict | None) -> str:
    lines: list[str] = []
    lines.append("# ClaimGuard Compliance Report")
    lines.append("")
    lines.append("Generated by `make compliance-report` (docs/plan.md M9). This is a "
                  "**demonstration of compliance-by-design**, not legal advice or a "
                  "certified compliance claim — see docs/compliance-mapping.md.")
    lines.append("")

    lines.append("## 1. Compliance mapping — real test coverage")
    lines.append("")
    lines.append("| Framework | Principle | Rules covered | Real tests | Result |")
    lines.append("|---|---|---|---|---|")
    footnotes: list[str] = []
    for row in COMPLIANCE_ROWS:
        rule_ids = ", ".join(p.upper() for p in row["rule_prefixes"]) or "—"
        n_tests = 0
        n_failed = 0
        for prefix in row["rule_prefixes"]:
            bucket = test_results.get(prefix)
            if bucket:
                n_tests += len(bucket["tests"])
                n_failed += bucket["failed"]
        result = "—" if n_tests == 0 else ("✅ all pass" if n_failed == 0 else f"❌ {n_failed} failing")
        principle = row["principle"]
        if "note" in row:
            footnotes.append(f"[^{len(footnotes) + 1}]: {row['note']}")
            principle = f"{principle} [^{len(footnotes)}]"
        lines.append(f"| {row['framework']} | {principle} | {rule_ids} | {n_tests} | {result} |")
    lines.append("")
    lines.extend(footnotes)
    lines.append("")

    total_passed = sum(b["passed"] for b in test_results.values())
    total_failed = sum(b["failed"] for b in test_results.values())
    lines.append(f"**Full backend test suite: {total_passed} passed, {total_failed} failed "
                 f"({total_passed + total_failed} total, `uv run pytest` from backend/).**")
    lines.append("")

    lines.append("## 2. Harbor scoreboard")
    lines.append("")
    if harbor is None:
        lines.append("_No Harbor job with at least one completed trial exists yet in "
                      "`evals/harbor/jobs/`. Run `make eval` to produce one — this section "
                      "will report real outcome/governance pass rates once a job succeeds, "
                      "not a placeholder number._")
    else:
        metrics = harbor.get("metrics", [])
        n_trials = harbor.get("n_trials", 0)
        n_errors = harbor.get("n_errors", 0)
        outcome_pass = sum(1 for m in metrics if m.get("outcome") == 1.0)
        governance_pass = sum(1 for m in metrics if m.get("governance") == 1.0)
        lines.append(f"Job `{harbor['job_dir']}` ({harbor['eval_name']}): {n_trials} trials, {n_errors} errors.")
        lines.append("")
        lines.append(f"- Outcome pass rate: {outcome_pass}/{n_trials}")
        lines.append(f"- Governance pass rate: {governance_pass}/{n_trials}")
    lines.append("")

    lines.append("## 3. Medical-data access summary")
    lines.append("")
    lines.append(f"- `medical_reviewer` agent accesses (normal path): {audit['medical_reviewer_access_count']}")
    lines.append(f"- Officer break-glass accesses (audited exception path): {len(audit['break_glass_accesses'])}")
    if audit["break_glass_accesses"]:
        lines.append("")
        lines.append("| Trace ID | Timestamp | Officer | Reason |")
        lines.append("|---|---|---|---|")
        for access in audit["break_glass_accesses"]:
            args = access["tool_args"] or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            lines.append(f"| {access['trace_id']} | {access['timestamp']} | {args.get('officer_id', '?')} | {args.get('reason', '?')} |")
    lines.append("")

    lines.append("## 4. Denied actions by rule ID")
    lines.append("")
    if not audit["denied_by_rule"]:
        lines.append("No denials recorded in the current audit log.")
    else:
        lines.append("| Rule ID | Denials |")
        lines.append("|---|---|")
        for rule_id, count in sorted(audit["denied_by_rule"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {rule_id} | {count} |")
    lines.append("")

    lines.append("## 5. Audit chain integrity")
    lines.append("")
    integrity = audit["integrity"]
    if integrity["valid"]:
        lines.append(f"✅ **Valid.** {integrity.get('message', '')} ({integrity['total_entries']} entries checked, "
                      "via the real installed `agent_control_plane.FlightRecorder.verify_integrity()` — "
                      "hash-chain + content-hash checks, not reimplemented here.)")
    else:
        lines.append(f"❌ **TAMPERING DETECTED** at entry {integrity.get('first_tampered_id')}: {integrity.get('error')}")
    lines.append("")

    lines.append("## 6. Audit log statistics")
    lines.append("")
    stats = audit["stats"]
    lines.append(f"- Total actions logged: {stats['total_actions']}")
    lines.append(f"- By verdict: {stats['by_verdict']}")
    lines.append("- Top agents by action count:")
    for agent in stats["top_agents"]:
        lines.append(f"  - {agent['agent_id']}: {agent['count']}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    print("Running backend test suite...", file=sys.stderr)
    test_results = run_tests()
    print("Reading live audit log...", file=sys.stderr)
    audit = get_audit_summary()
    print("Checking for a Harbor scoreboard...", file=sys.stderr)
    harbor = get_harbor_scoreboard()

    report = render_report(test_results, audit, harbor)
    OUTPUT_PATH.write_text(report)
    print(f"Wrote {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
