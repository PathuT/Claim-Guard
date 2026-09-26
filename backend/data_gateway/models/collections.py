"""ORM models for the 9 collections in docs/architecture.md §10.

Field lists and sensitivity notes are taken directly from that table and from
docs/security-matrix.md §3 (field allowlists) and §11 (identity/trust). This
module only defines *storage* — the field-level restrictions (read_limited,
read_pseudonymised, row binding) are enforced by the data gateway in M2, not
here. SQLAlchemy will happily return every column; nothing here is a security
boundary by itself.

Embedding dimension (policy_terms.embedding): 3072, matching
models/gemini-embedding-001 (confirmed against the live API — see M1 notes).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

EMBEDDING_DIM = 3072


class Policyholder(Base):
    """PII. `read_limited` scope (coverage agent) exposes only:
    plan, sum_insured, start_date, member.age, member.member_id — never name/contact.
    """

    __tablename__ = "policyholders"

    policy_number: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    contact: Mapped[str] = mapped_column(String, nullable=False)
    plan: Mapped[str] = mapped_column(String, nullable=False)  # "Silver" | "Gold"
    sum_insured: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    members: Mapped[list[PolicyholderMember]] = relationship(
        back_populates="policyholder", cascade="all, delete-orphan"
    )
    bank_detail: Mapped[BankDetail] = relationship(
        back_populates="policyholder", uselist=False, cascade="all, delete-orphan"
    )


class PolicyholderMember(Base):
    __tablename__ = "policyholder_members"

    member_id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_number: Mapped[str] = mapped_column(
        String, ForeignKey("policyholders.policy_number"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    relationship_to_holder: Mapped[str] = mapped_column(String, default="self")

    policyholder: Mapped[Policyholder] = relationship(back_populates="members")


class BankDetail(Base):
    """Restricted. Row-bound to the claim's policy; `bank_details:read` allowlist
    is account_number + ifsc only."""

    __tablename__ = "bank_details"

    policy_number: Mapped[str] = mapped_column(
        String, ForeignKey("policyholders.policy_number"), primary_key=True
    )
    account_number: Mapped[str] = mapped_column(String, nullable=False)
    ifsc: Mapped[str] = mapped_column(String, nullable=False)

    policyholder: Mapped[Policyholder] = relationship(back_populates="bank_detail")


class PolicyTerm(Base):
    """Internal. Chunked plan wording + embedding for retrieval (coverage agent,
    `policy_terms:read`). One row per clause."""

    __tablename__ = "policy_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan: Mapped[str] = mapped_column(String, nullable=False)  # "Silver" | "Gold"
    clause_id: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "5.G1"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class Hospital(Base):
    __tablename__ = "hospitals"

    hospital_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)
    network: Mapped[bool] = mapped_column(Boolean, default=True)
    watchlist: Mapped[bool] = mapped_column(Boolean, default=False)


class Claim(Base):
    """Internal + PII link. `read_pseudonymised` (fraud agent) replaces
    claim_id/policy_number with keyed hashes and drops PII fields entirely —
    enforced by the gateway in M2, not by this model."""

    __tablename__ = "claims"

    claim_id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_number: Mapped[str] = mapped_column(
        String, ForeignKey("policyholders.policy_number"), nullable=False
    )
    member_id: Mapped[str] = mapped_column(String, nullable=False)
    hospital_id: Mapped[str] = mapped_column(String, ForeignKey("hospitals.hospital_id"), nullable=False)
    admission_date: Mapped[date] = mapped_column(Date, nullable=False)
    discharge_date: Mapped[date] = mapped_column(Date, nullable=False)
    stated_illness: Mapped[str] = mapped_column(Text, nullable=False)  # untrusted free text
    claimed_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    line_items: Mapped[dict] = mapped_column(JSONB, default=dict)  # bill items extracted by intake
    doc_hashes: Mapped[list] = mapped_column(JSONB, default=list)  # sha256 of each uploaded doc
    status: Mapped[str] = mapped_column(String, default="submitted")
    assessment: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # coverage agent's output
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ClaimDocument(Base):
    """Untrusted. Raw uploaded files + extracted text. 5 of the ~40 seeded
    sets are "poisoned" (hidden injected text) for scenario S06."""

    __tablename__ = "claim_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.claim_id"), nullable=False)
    file_ref: Mapped[str] = mapped_column(String, nullable=False)  # path under data/synthetic/documents/
    doc_type: Mapped[str] = mapped_column(String, nullable=False)  # "final_bill" | "discharge_summary" | "pharmacy_bill"
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    is_poisoned: Mapped[bool] = mapped_column(Boolean, default=False)  # seed metadata only, not a real field an agent sees


class MedicalRecord(Base):
    """Highly restricted health data. Only the medical_reviewer agent may
    read this collection (DATA-001 in docs/security-matrix.md)."""

    __tablename__ = "medical_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.claim_id"), nullable=False, unique=True)
    diagnosis_text: Mapped[str] = mapped_column(Text, nullable=False)
    icd10: Mapped[str] = mapped_column(String, nullable=False)
    history: Mapped[str] = mapped_column(Text, default="")
    treatment: Mapped[str] = mapped_column(Text, nullable=False)


class Payment(Base):
    """Mock. Starts empty; only the payout agent (via AGT) writes here from M5."""

    __tablename__ = "payments"

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.claim_id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    account_ref: Mapped[str] = mapped_column(String, nullable=False)
    agt_decision_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Audit(Base):
    """Append-only, hash-chained. Starts empty; only the AGT adapter writes
    here (append-only, docs/security-matrix.md §2). Hash-chaining logic
    (prev_hash -> hash) is added when the AGT adapter is built in M3 —
    this table only reserves the columns for it."""

    __tablename__ = "audit"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    req_id: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)  # "allow" | "deny"
    rule_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prev_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    hash: Mapped[str | None] = mapped_column(String, nullable=True)
    numeric_amount: Mapped[float | None] = mapped_column(Numeric, nullable=True)
