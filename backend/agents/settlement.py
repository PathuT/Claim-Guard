"""Deterministic settlement calculator — the actual arithmetic behind the
coverage agent's CoverageAssessment. Plain Python, not LLM reasoning:
docs/architecture.md §2 ("The LLM is an untrusted decision-maker.
Enforcement is deterministic code") applies to money as much as to policy
checks. The coverage Agno agent (coverage.py) wraps this; it does not
recompute the numbers itself.

Every deduction cites a `clause_id` from data/synthetic/generators/plan_terms.py
(the same clause IDs seeded into policy_terms), matching docs/use-case.md §7's
"₹1,200 deducted: non-payable items (clause 5.G1)" exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from .schemas import BillLineItem, CoverageAssessment, Deduction, MedicalFinding

NON_PAYABLE_KEYWORDS = ("toiletries", "registration fee", "attendant", "admin fee", "food for attendant")

ROOM_RENT_CAP = {"Silver": 5_000, "Gold": None}  # None = no cap (Gold, single private room)
CO_PAY_RATE = {"Silver": {"under_60": 0.0, "60_plus": 0.20}, "Gold": {"under_60": 0.0, "60_plus": 0.0}}
INITIAL_WAITING_DAYS = 30
SPECIFIC_ILLNESS_WAITING_YEARS = 2
PED_WAITING_YEARS = {"Silver": 3, "Gold": 2}
MIN_HOSPITALISATION_HOURS = 24

SPECIFIC_ILLNESS_KEYWORDS = ("cataract", "hernia", "knee replacement")


@dataclass
class PolicyContext:
    """Everything the calculator needs about the policy — assembled by the
    caller from trusted policyholder/policy_terms rows, never from agent
    arguments (same trusted-context discipline as governance/adapter.py)."""

    plan: str  # "Silver" | "Gold"
    sum_insured: int
    start_date: date
    member_age: int


def _parse_bill_date(s: str) -> date:
    """Bill dates from intake are in DD-MM-YYYY (matching the sample bills'
    own format, e.g. "10-09-2026") or ISO YYYY-MM-DD — try both.
    Naive (no timezone) is deliberate: these are calendar dates (admission/
    discharge days), not timestamps — there's no time-of-day or timezone
    concept anywhere in the claim data model."""
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()  # noqa: DTZ007 - calendar date only, see docstring
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: {s!r}")


ROOM_RENT_LABEL = re.compile(r"\broom\s*(rent|charges?|tariff)\b", re.IGNORECASE)
# Rooms that are not accommodation, so never subject to the room-rent cap.
NOT_ACCOMMODATION = re.compile(r"\b(operat\w*|theat\w*|procedure|recovery|labou?r|delivery|emergency|icu|iccu|nicu|treatment)\b", re.IGNORECASE)


def _room_rent_line_items(line_items: list[BillLineItem], stay_days: int) -> tuple[list[BillLineItem], int | None]:
    """Finds the room-rent line item(s) and the per-day rate, needed to
    compute the excess over the plan's cap. Returns (items, rate_or_None).

    The rate comes from the label's "@ ₹X" when the intake agent copied it,
    and otherwise from the line total divided by the days billed ("N days"
    in the label, else the stay length). Found by the Harbor suite (S02): the
    agent labelled the same ₹32,000 line "Room rent (private) 4 days @ 8,000",
    "Room rent (private) 4 days" and "Room rent (private)" on different runs,
    and only the first was capped. The money maths must not depend on how a
    model phrases a label."""
    room_items = [li for li in line_items if ROOM_RENT_LABEL.search(li.label) and not NOT_ACCOMMODATION.search(li.label)]
    per_day = None
    for li in room_items:
        rate = re.search(r"@\s*(?:₹|rs\.?|inr)?\s*([\d,]+)", li.label, re.IGNORECASE)
        if rate:
            per_day = int(rate.group(1).replace(",", ""))
            continue
        days = re.search(r"(\d+)\s*days?\b", li.label, re.IGNORECASE)
        billed_days = int(days.group(1)) if days else stay_days
        if billed_days > 0 and li.amount > 0:
            per_day = round(li.amount / billed_days)
    return room_items, per_day


def _stay_days(admission: date, discharge: date) -> int:
    return max((discharge - admission).days, 1)


def compute_settlement(
    claim_id: str,
    claimed_amount: int,
    line_items: list[BillLineItem],
    admission_date_str: str,
    discharge_date_str: str,
    finding: MedicalFinding,
    policy: PolicyContext,
) -> CoverageAssessment:
    deductions: list[Deduction] = []
    flags: list[str] = []

    admission = _parse_bill_date(admission_date_str)
    discharge = _parse_bill_date(discharge_date_str)

    # --- Non-payables (clause 5.G1, both plans) ---
    for li in line_items:
        label_lower = li.label.lower()
        if any(kw in label_lower for kw in NON_PAYABLE_KEYWORDS):
            deductions.append(Deduction(amount=li.amount, reason="Non-payable item", clause_id="5.G1"))

    # --- Room rent excess (Silver only; Gold has no cap) ---
    cap = ROOM_RENT_CAP.get(policy.plan)
    if cap is not None:
        stay_days = _stay_days(admission, discharge)
        _room_items, per_day_rate = _room_rent_line_items(line_items, stay_days)
        if per_day_rate is not None and per_day_rate > cap:
            excess_per_day = per_day_rate - cap
            excess_total = excess_per_day * stay_days
            clause_id = "5.S2" if policy.plan == "Silver" else "5.G2"
            deductions.append(Deduction(amount=excess_total, reason=f"Room rent excess (₹{per_day_rate}/day vs ₹{cap}/day cap)", clause_id=clause_id))

    # --- Exclusions (cosmetic surgery, non-accident dental) ---
    if finding.excluded_treatment:
        flags.append("excluded_treatment")

    # --- Waiting periods ---
    days_since_start = (admission - policy.start_date).days
    if days_since_start < INITIAL_WAITING_DAYS and not finding.accident_related:
        flags.append("initial_waiting_period_not_met")

    if finding.pre_existing_suspected:
        ped_years = PED_WAITING_YEARS.get(policy.plan, 3)
        years_since_start = days_since_start / 365.25
        if years_since_start < ped_years:
            flags.append("pre_existing_disease_waiting_period_not_met")

    # --- Minimum hospitalisation (unless day-care procedure) ---
    if not finding.day_care_procedure and finding.length_of_stay_hours < MIN_HOSPITALISATION_HOURS:
        flags.append("minimum_hospitalisation_not_met")

    # --- Co-pay ---
    co_pay_rate = CO_PAY_RATE.get(policy.plan, {"under_60": 0.0, "60_plus": 0.0})
    rate = co_pay_rate["60_plus"] if policy.member_age >= 60 else co_pay_rate["under_60"]
    amount_after_deductions = claimed_amount - sum(d.amount for d in deductions)
    co_pay_amount = round(amount_after_deductions * rate)

    payable_amount = amount_after_deductions - co_pay_amount

    if flags or finding.confidence < 0.7:
        recommended_decision = "pending_human"
    else:
        recommended_decision = "approve"

    return CoverageAssessment(
        claim_id=claim_id,
        claimed_amount=claimed_amount,
        deductions=deductions,
        co_pay_amount=co_pay_amount,
        payable_amount=payable_amount,
        recommended_decision=recommended_decision,
        flags=flags,
    )
