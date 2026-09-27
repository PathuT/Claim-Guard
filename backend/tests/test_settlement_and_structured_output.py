"""Regression tests for the two failures the Harbor suite found on the final
code (S02, S03):

- S02: the room-rent cap must apply however the intake agent phrased the
  room line — with "@ rate", with only "N days", or with neither.
- S03: an agent whose structured output comes back malformed is asked
  again, and the workflow still fails closed if it never recovers.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from agents.schemas import BillLineItem, MedicalFinding
from agents.settlement import PolicyContext, compute_settlement
from agents.structured import MAX_ATTEMPTS, run_structured

FINDING = MedicalFinding(
    claim_id="CLM-TEST", icd10="J18.9", diagnosis_category="respiratory", length_of_stay_hours=96,
    stay_justified=True, day_care_procedure=False, pre_existing_suspected=False, excluded_treatment=False,
    accident_related=False, confidence=0.9, notes_for_officer="",
)
SILVER = PolicyContext(plan="Silver", sum_insured=500_000, start_date=date(2022, 1, 1), member_age=34)
GOLD = PolicyContext(plan="Gold", sum_insured=1_000_000, start_date=date(2022, 1, 1), member_age=34)
OTHER_ITEMS = [BillLineItem(label="Doctor consultation", amount=12_000), BillLineItem(label="Laboratory", amount=14_000),
               BillLineItem(label="IV antibiotics & medicines", amount=25_000)]


def _settle(room_label: str, amount: int = 32_000, policy: PolicyContext = SILVER, admit: str = "15-09-2026", discharge: str = "19-09-2026"):
    items = [BillLineItem(label=room_label, amount=amount), *OTHER_ITEMS]
    return compute_settlement("CLM-TEST", sum(i.amount for i in items), items, admit, discharge, FINDING, policy)


@pytest.mark.parametrize("label", [
    "Room rent (private) 4 days @ 8,000",  # rate copied
    "Room rent (private) 4 days",          # only the days (S02, 15:13 run)
    "Room rent (private)",                 # neither (an earlier live run)
    "Room charges - private room",         # different wording
    "ROOM RENT @ Rs. 8,000",               # currency written out
])
def test_room_rent_cap_applies_however_the_label_is_phrased(label):
    assessment = _settle(label)
    room = [d for d in assessment.deductions if d.clause_id == "5.S2"]
    assert [d.amount for d in room] == [12_000], label
    assert assessment.payable_amount == 71_000


@pytest.mark.parametrize("label", ["Room rent (semi-private) 3 days @ 4,500", "Room rent (semi-private) 3 days", "Room rent"])
def test_room_within_cap_has_no_deduction(label):
    assessment = _settle(label, amount=13_500, admit="10-09-2026", discharge="13-09-2026")
    assert not [d for d in assessment.deductions if d.clause_id == "5.S2"]


def test_gold_plan_has_no_room_rent_cap():
    assessment = _settle("Room rent (private)", policy=GOLD)
    assert not [d for d in assessment.deductions if d.clause_id in ("5.S2", "5.G2")]


def test_operating_room_is_not_room_rent():
    assessment = _settle("Operating room charges", amount=40_000)
    assert not [d for d in assessment.deductions if d.clause_id == "5.S2"]


class _FakeAgent:
    """Returns the scripted contents in order, like agent.run(...).content."""

    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = 0

    def run(self, message):
        self.calls += 1
        return SimpleNamespace(content=self.contents.pop(0))


GROQ_JSON_ERROR = '{"error": {"message": "Failed to generate JSON.", "code": "json_validate_failed"}}'


def test_malformed_output_is_retried_until_valid():
    agent = _FakeAgent(GROQ_JSON_ERROR, FINDING)
    assert run_structured(agent, "msg", MedicalFinding, "Medical reviewer") == FINDING
    assert agent.calls == 2


def test_valid_json_string_is_accepted():
    agent = _FakeAgent(FINDING.model_dump_json())
    assert run_structured(agent, "msg", MedicalFinding, "Medical reviewer").icd10 == "J18.9"
    assert agent.calls == 1


def test_never_valid_fails_closed_after_max_attempts():
    agent = _FakeAgent(*([GROQ_JSON_ERROR] * MAX_ATTEMPTS))
    with pytest.raises(ValueError, match="did not return a valid MedicalFinding"):
        run_structured(agent, "msg", MedicalFinding, "Medical reviewer")
    assert agent.calls == MAX_ATTEMPTS
