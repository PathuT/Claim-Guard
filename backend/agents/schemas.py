"""Typed data contracts agents exchange, per docs/architecture.md §9:
"Agents exchange schema-validated JSON, not free text. Validation failure =
the finding is discarded and the claim goes to pending_human."

These are Agno `output_schema` models (Pydantic) — an agent constructed with
`output_schema=MedicalFinding` returns a validated instance or raises, giving
us the "validation failure -> discard" behaviour for free rather than having
to hand-parse a model's JSON text ourselves.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MedicalFinding(BaseModel):
    """medical_reviewer -> coverage, fraud, supervisor. Exact field set from
    docs/architecture.md §9 — do not add fields; coverage/fraud must only
    ever see this structured finding, never the raw discharge summary
    (docs/CLAUDE.md invariant 4)."""

    claim_id: str
    icd10: str
    diagnosis_category: str
    length_of_stay_hours: int
    stay_justified: bool
    day_care_procedure: bool
    pre_existing_suspected: bool
    excluded_treatment: bool
    accident_related: bool
    confidence: float = Field(ge=0.0, le=1.0)
    notes_for_officer: str  # shown only to officers, never passed to other agents (§9)


class Deduction(BaseModel):
    amount: int
    reason: str
    clause_id: str


class CoverageAssessment(BaseModel):
    """coverage -> supervisor. docs/architecture.md §9: "claimed amount, list
    of deductions ({amount, reason, clause_id}), co-pay, payable amount,
    recommended decision, flags."""

    claim_id: str
    claimed_amount: int
    deductions: list[Deduction]
    co_pay_amount: int
    payable_amount: int
    recommended_decision: str  # "approve" | "approve_partial" | "pending_human" | "reject_recommended"
    flags: list[str] = Field(default_factory=list)


class FraudFlag(BaseModel):
    type: str
    severity: str
    evidence_ref: str


class FraudScreen(BaseModel):
    """fraud -> supervisor. docs/architecture.md §9: "list of flags
    ({type, severity, evidence_ref}), using pseudonymised references only."""

    claim_id: str
    flags: list[FraudFlag] = Field(default_factory=list)


class BillLineItem(BaseModel):
    label: str
    amount: int


class IntakeResult(BaseModel):
    """intake -> claims:write + medical_records:write. Not one of the three
    contracts named in §9 (those are the *outputs* of medical_reviewer/
    coverage/fraud) — this is intake's own output schema, extracting what
    the discharge summary and bill actually said, split into what's claims
    data vs. medical data before either ever reaches another agent."""

    claim_id: str
    line_items: list[BillLineItem]
    bill_total: int
    diagnosis_text: str
    admission_date: str
    discharge_date: str
    length_of_stay_hours: int
