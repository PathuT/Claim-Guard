"""GET /system/facts derives the console's figures from the running code.
These cover the parts that need no database or AgentOS: the rule registry
and the test-report reader."""

from __future__ import annotations

from api import system_facts
from governance.rules import ALL_RULES


def test_rule_registry_is_read_from_code():
    rules = system_facts._rules()
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)) == len(ALL_RULES) + 5
    assert {"GOV-001", "GOV-002", "GOV-003", "GOV-004", "ID-001", "TRUST-001", "PAY-001", "STATE-001", "DATA-001"} <= set(ids)
    pay_001 = next(r for r in rules if r["id"] == "PAY-001")
    assert pay_001["must_hold"] == "Amount matches assessment"
    assert pay_001["enforced_by"] == "governance/rules.py"


def test_test_report_is_read_from_junit_xml(tmp_path, monkeypatch):
    report = tmp_path / "pytest.xml"
    report.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="12" failures="1" errors="1" skipped="2" '
        'timestamp="2026-09-27T21:00:00"></testsuite></testsuites>',
        encoding="utf-8",
    )
    monkeypatch.setattr(system_facts, "TEST_REPORT", report)
    assert system_facts._tests() == {"total": 12, "passed": 8, "failed": 2, "skipped": 2, "ran_at": "2026-09-27T21:00:00"}


def test_missing_test_report_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(system_facts, "TEST_REPORT", tmp_path / "absent.xml")
    assert system_facts._tests() is None
