"""Deterministic guardrails around the claim-assessment workflow (ADR-011).

Two checks, both plain Python (docs/architecture.md §2: "The LLM is an
untrusted decision-maker. Enforcement is deterministic code"):

1. Injection guardrail (`scan_documents`), which runs before intake. It scans the
   untrusted bill and discharge-summary text for instruction-like phrases,
   using the same marker list as the upload endpoint
   (api.claim_intake.scan_injection_markers). Detection does not stop the
   run. The documents are still read, as delimited untrusted data
   (invariant 8), exactly as before. A flagged claim can never be
   auto-paid, though: the supervisor adds INJECTION_FLAG to the assessment
   and forces tier T3, so a human officer sees the claim together with the flag.

2. Anti-hallucination guardrail (`validate_explanation`), which runs after the
   coverage agent writes its plain-language explanation. Every money
   amount in that text must be one the settlement contains. If any is not,
   the text is replaced with `build_fallback_explanation`, a template built
   only from the assessment, so an invented figure never reaches the
   policyholder or the officer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .schemas import CoverageAssessment

INJECTION_FLAG = "prompt_injection_suspected"
INJECTION_TIER_REASON = "hidden instruction-like text found in the documents"


# --- 1. Injection guardrail ----------------------------------------------------


@dataclass(frozen=True)
class DocumentScan:
    flagged: bool
    markers: list[str] = field(default_factory=list)  # distinct markers, first-seen order
    doc_types: list[str] = field(default_factory=list)  # doc types a marker was found in
    by_doc_type: dict[str, list[str]] = field(default_factory=dict)


def scan_documents(documents: Mapping[str, str | None]) -> DocumentScan:
    """`documents` maps doc_type -> extracted text. Observational only: the
    caller decides what a flag means (here, "never auto-pay")."""
    # The one marker list lives with the upload endpoint. It is imported
    # here rather than at module level because api.claim_intake loads
    # data_gateway.db (which needs DATABASE_URL at import time), and
    # `import agents.supervisor` shouldn't need that. If the import fails,
    # the step fails and _fail_closed stops the run.
    from api.claim_intake import scan_injection_markers

    by_doc_type: dict[str, list[str]] = {}
    for doc_type, text in documents.items():
        found = scan_injection_markers(text or "")
        if found:
            by_doc_type[doc_type] = found
    markers = list(dict.fromkeys(m for found in by_doc_type.values() for m in found))
    return DocumentScan(flagged=bool(markers), markers=markers, doc_types=list(by_doc_type), by_doc_type=by_doc_type)


# --- 2. Anti-hallucination guardrail --------------------------------------------

# A number is either comma-grouped (Western 37,300 or Indian 4,50,000) or
# plain (37300), with optional decimals (.00).
_NUMBER = r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_MULTIPLIER = r"lakhs?|lacs?|crores?|cr|k"
_MULTIPLIERS = {"lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
                "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000, "k": 1_000}

# Only a number with a currency marker counts as money: before it (₹, Rs,
# Rs., INR, rupees) or after it (rupees, INR, /-). That is why percentages
# (20%), dates (10-09-2026), day counts (3 days), hours and clause ids
# (5.G1) are never read as amounts.
_MONEY_RE = re.compile(
    rf"""
    (?:
        (?:₹|\bRs\.?|\bINR|\brupees?)\s*
        (?P<num1>{_NUMBER})
        (?:\s*(?P<mult1>{_MULTIPLIER})(?![A-Za-z]))?
    |
        (?<![\d,.])(?P<num2>{_NUMBER})
        (?:\s*(?P<mult2>{_MULTIPLIER})(?![A-Za-z]))?
        \s*(?:rupees?\b|INR\b|/-)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def extract_money_amounts(text: str) -> list[Decimal]:
    """Every money amount in `text`, in order of appearance. Lakh, crore and
    k are expanded, so "₹4.5 lakh" reads as 450000."""
    amounts: list[Decimal] = []
    for match in _MONEY_RE.finditer(text or ""):
        number = match.group("num1") or match.group("num2")
        multiplier = (match.group("mult1") or match.group("mult2") or "").lower()
        value = Decimal(number.replace(",", ""))
        if multiplier:
            value *= _MULTIPLIERS[multiplier]
        amounts.append(value)
    return amounts


def allowed_amounts(assessment: CoverageAssessment) -> set[int]:
    """The amounts the settlement actually contains. These are claimed,
    payable, co-pay, each deduction and the sum of deductions, plus the two
    figures that follow from them exactly: the co-pay base (claimed minus
    deductions) and the total reduction (claimed minus payable). The
    per-day rates quoted in a deduction's own reason are also allowed,
    e.g. "Room rent excess (₹6500/day vs ₹5000/day cap)"."""
    deductions_total = sum(d.amount for d in assessment.deductions)
    allowed = {
        assessment.claimed_amount,
        assessment.payable_amount,
        assessment.co_pay_amount,
        deductions_total,
        assessment.claimed_amount - deductions_total,
        assessment.claimed_amount - assessment.payable_amount,
    }
    for deduction in assessment.deductions:
        allowed.add(deduction.amount)
        allowed.update(int(v) for v in extract_money_amounts(deduction.reason) if v == v.to_integral_value())
    return allowed


def validate_explanation(explanation: str, assessment: CoverageAssessment) -> tuple[bool, list[int]]:
    """Returns (ok, unexpected_amounts). An amount is unexpected when it is
    not in `allowed_amounts`, or when it has non-zero paise, because
    settlement amounts are whole rupees. unexpected_amounts is de-duplicated
    and kept in the order the amounts appear in the text."""
    allowed = allowed_amounts(assessment)
    unexpected: list[int] = []
    for value in extract_money_amounts(explanation):
        whole = value == value.to_integral_value()
        as_int = int(value.to_integral_value(rounding=ROUND_HALF_UP))
        if (not whole or as_int not in allowed) and as_int not in unexpected:
            unexpected.append(as_int)
    return (not unexpected, unexpected)


def format_inr(amount: int) -> str:
    """₹ with Indian digit grouping: 450000 -> "₹4,50,000"."""
    sign = "-" if amount < 0 else ""
    digits = str(abs(amount))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        digits = ",".join([*groups, tail])
    return f"{sign}₹{digits}"


_DECISION_TEXT = {
    "approve": "recommended for approval",
    "approve_partial": "recommended for partial approval",
    "pending_human": "referred to a claims officer, who will make the decision",
    "reject_recommended": "rejection recommended; only a claims officer can reject a claim",
}


def build_fallback_explanation(assessment: CoverageAssessment) -> str:
    """Plain-language settlement summary built only from the assessment.
    It contains the payable amount and every deduction with its clause id,
    so it always passes validate_explanation."""
    parts = [f"Settlement summary for claim {assessment.claim_id}: {format_inr(assessment.claimed_amount)} claimed."]
    if assessment.deductions:
        for deduction in assessment.deductions:
            parts.append(f"{format_inr(deduction.amount)} deducted: {deduction.reason} (clause {deduction.clause_id}).")
    else:
        parts.append("No deductions were applied.")
    if assessment.co_pay_amount:
        parts.append(f"Co-pay under the plan: {format_inr(assessment.co_pay_amount)}.")
    parts.append(f"Payable amount: {format_inr(assessment.payable_amount)}.")
    decision = _DECISION_TEXT.get(assessment.recommended_decision, assessment.recommended_decision)
    parts.append(f"Decision: {decision}.")
    if assessment.flags:
        parts.append("Points for the claims officer: " + ", ".join(f.replace("_", " ") for f in assessment.flags) + ".")
    return " ".join(parts)


__all__ = [
    "INJECTION_FLAG",
    "INJECTION_TIER_REASON",
    "DocumentScan",
    "allowed_amounts",
    "build_fallback_explanation",
    "extract_money_amounts",
    "format_inr",
    "scan_documents",
    "validate_explanation",
]
