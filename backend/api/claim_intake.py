"""Real claim intake from an actual browser upload — the genuine entrypoint
into the whole story this project demonstrates (docs/use-case.md §1:
"Claim submission: member, hospital, admission/discharge dates, stated
illness, claimed amount, documents"), as opposed to the pre-seeded
claim_ids api/agentos.py's POST /claims replays.

Before this module existed, EVERY claim in the system was placed directly
into Postgres by data/synthetic/generators/ at `make seed` time — a real
PDF, a real sha256, but never through an actual HTTP upload. This endpoint
closes that gap: a policyholder attaches two real PDF files (their own
final bill and discharge summary, whatever real document they actually
have — not one of the seed generator's own known-structure files), and the
SAME text-extraction function the seed generator already uses on its own
PDFs (data_gateway.seed._extract_pdf_text, real pypdf text extraction, not
a fixed-structure parser) runs on the uploaded bytes instead. Nothing about
the downstream 5-agent pipeline changes — intake's own agent already
handles unpredictable raw text via an LLM call, not regex, so it needs no
change at all to work on a real, previously-unseen PDF's extracted text.

Storage: uploaded files land in data/uploads/ (NOT data/synthetic/
documents/, which `make seed` truncates/regenerates on every run — mixing
real uploads into that directory would silently lose them on the next
reseed).
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from data_gateway.db import get_session
from data_gateway.models import (
    Claim,
    ClaimDocument,
    Hospital,
    Policyholder,
    PolicyholderMember,
)

router = APIRouter()

UPLOADS_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"
REQUIRED_UPLOAD_DOC_TYPES = ("final_bill", "discharge_summary")


def _get_db() -> Session:
    db = get_session()
    try:
        yield db
    finally:
        db.close()


def _extract_pdf_text(raw_bytes: bytes) -> str:
    """Same real extraction data_gateway.seed._extract_pdf_text uses on the
    seed generator's own PDFs — generic pypdf text extraction, not a
    fixed-structure parser, so it works the same way on a real uploaded
    PDF it has never seen before. Takes bytes (an upload has no path on
    disk yet at extraction time) rather than a file path, via pypdf's own
    BytesIO-stream support."""
    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


class NewClaimResponse(BaseModel):
    claim_id: str
    status: str
    missing_documents: list[str] = []


@router.post("/claims/new", response_model=NewClaimResponse)
async def submit_new_claim(
    db: Session = Depends(_get_db),
    policy_number: str = Form(...),
    member_id: str = Form(...),
    hospital_id: str = Form(...),
    admission_date: date = Form(...),
    discharge_date: date = Form(...),
    stated_illness: str = Form(...),  # untrusted free text — never treated as instructions downstream
    claimed_amount: int = Form(...),
    final_bill: UploadFile = File(...),
    discharge_summary: UploadFile = File(...),
) -> NewClaimResponse:
    """The real form a policyholder fills in, with two real file
    attachments — the actual start of the story docs/use-case.md §1
    describes, not a pre-seeded claim_id. Creates a brand-new Claim row
    (status=submitted) plus two real ClaimDocument rows with genuinely
    extracted text and a real sha256 computed from the uploaded bytes
    (never a hash of a seed-generator file this claim never touched).

    Deliberately does NOT run the agent pipeline itself — that's
    POST /claims's job, unchanged, called separately by the Console right
    after this endpoint returns (mirroring how a real system would treat
    "receive the claim" and "assess the claim" as two distinct steps, the
    second of which can be retried/re-triggered independently).
    """
    policyholder = db.get(Policyholder, policy_number)
    if policyholder is None:
        raise HTTPException(status_code=404, detail={"reason_code": "INTAKE-NO-SUCH-POLICY", "message": f"policy {policy_number!r} does not exist"})
    member = db.get(PolicyholderMember, member_id)
    if member is None or member.policy_number != policy_number:
        raise HTTPException(status_code=404, detail={"reason_code": "INTAKE-NO-SUCH-MEMBER", "message": f"member {member_id!r} not found under policy {policy_number!r}"})
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(status_code=404, detail={"reason_code": "INTAKE-NO-SUCH-HOSPITAL", "message": f"hospital {hospital_id!r} does not exist"})

    claim_id = f"CLM-{date.today().year}-{uuid.uuid4().hex[:9].upper()}"  # noqa: DTZ011 - calendar date only, matches settlement.py's own precedent
    claim = Claim(
        claim_id=claim_id, policy_number=policy_number, member_id=member_id, hospital_id=hospital_id,
        admission_date=admission_date, discharge_date=discharge_date, stated_illness=stated_illness,
        claimed_amount=claimed_amount, status="submitted",
    )
    db.add(claim)

    claim_upload_dir = UPLOADS_DIR / claim_id
    claim_upload_dir.mkdir(parents=True, exist_ok=True)

    uploaded_files = {"final_bill": final_bill, "discharge_summary": discharge_summary}
    missing: list[str] = []
    for doc_type, upload in uploaded_files.items():
        raw_bytes = await upload.read()
        if not raw_bytes:
            missing.append(doc_type)
            continue
        file_path = claim_upload_dir / f"{doc_type}.pdf"
        file_path.write_bytes(raw_bytes)
        try:
            extracted_text = _extract_pdf_text(raw_bytes)
        except Exception as exc:  # noqa: BLE001 - pypdf raising on a malformed/non-PDF upload; fail closed with a clear 422, not a 500
            db.rollback()
            raise HTTPException(status_code=422, detail={"reason_code": "INTAKE-UNREADABLE-PDF", "message": f"could not read {doc_type} as a PDF: {exc}"}) from None

        db.add(ClaimDocument(
            claim_id=claim_id, file_ref=str(file_path), doc_type=doc_type,
            extracted_text=extracted_text, sha256=hashlib.sha256(raw_bytes).hexdigest(), is_poisoned=False,
        ))

    db.commit()

    return NewClaimResponse(claim_id=claim_id, status="submitted", missing_documents=missing)
