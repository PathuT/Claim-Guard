"""M1 seed entrypoint: `uv run python -m data_gateway.seed` (wired to `make seed`).

Populates every collection in docs/architecture.md §10 with synthetic data per
docs/use-case.md §4.2, generates the PDF documents scenarios S01/S02/S06/S09/S10
need, embeds policy_terms via Gemini, and computes real sha256 hashes for every
document row.

Idempotent (docs/plan.md M1: "make seed is idempotent"): truncates and
re-inserts every table each run rather than checking for existing rows, so
re-running always produces the same, complete state.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data" / "synthetic" / "generators"))

from claims import gen_historical_claims, gen_scenario_claims
from documents import generate_all, generate_extra_poisoned
from plan_terms import CLAUSES
from reference_data import gen_hospitals, gen_policyholders

from data_gateway.db import direct_engine, get_direct_session
from data_gateway.models import (
    BankDetail,
    Base,
    Claim,
    ClaimDocument,
    Hospital,
    MedicalRecord,
    Payment,
    Policyholder,
    PolicyholderMember,
    PolicyTerm,
)

# Historical claim_ids to attach the 4 extra poisoned documents to (S06 is the 5th).
EXTRA_POISON_TARGETS = [
    ("CLM-2026-001010", "POISON-02"),
    ("CLM-2026-001050", "POISON-03"),
    ("CLM-2026-001090", "POISON-04"),
    ("CLM-2026-001130", "POISON-05"),
]


def _sha256_file(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _extract_pdf_text(path: str) -> str:
    import pypdf

    reader = pypdf.PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _embed_policy_terms() -> list[list[float] | None]:
    """Embeds every clause via Gemini. Returns None per-row (rather than
    failing the whole seed) if GEMINI_API_KEY is missing or a call errors,
    since policy_terms rows are still useful for M4's exact-clause lookups
    even without a vector vector for retrieval yet."""
    import os

    if not os.environ.get("GEMINI_API_KEY"):
        print("  GEMINI_API_KEY not set — skipping embeddings (policy_terms will have embedding=NULL).")
        return [None] * len(CLAUSES)

    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    embeddings: list[list[float] | None] = []
    for i, clause in enumerate(CLAUSES, 1):
        try:
            result = client.models.embed_content(model="models/gemini-embedding-001", contents=clause["text"])
            embeddings.append(list(result.embeddings[0].values))
        except Exception as exc:  # noqa: BLE001 - one bad clause shouldn't kill the whole seed
            print(f"  embedding failed for clause {clause['clause_id']}: {exc}")
            embeddings.append(None)
        if i % 5 == 0 or i == len(CLAUSES):
            print(f"  embedded {i}/{len(CLAUSES)} clauses")
    return embeddings


def main() -> None:
    print("Creating tables (if not already present)...")
    Base.metadata.create_all(direct_engine)

    print("Generating reference data...")
    policyholders, members, bank_details = gen_policyholders(n=60)
    hospitals = gen_hospitals(n=25, n_watchlisted=3)
    hospitals_by_id = {h["hospital_id"]: h for h in hospitals}
    watchlisted_ids = [h["hospital_id"] for h in hospitals if h["watchlist"]]

    print("Generating claims (scenario + historical)...")
    scenario_claims, scenario_records = gen_scenario_claims()
    # Resolve S10's placeholder watchlisted-hospital reference to a real id.
    for c in scenario_claims:
        if c["hospital_id"] == "HOSP-WATCHLIST-S10":
            c["hospital_id"] = watchlisted_ids[0]

    hist_claims, hist_records = gen_historical_claims(policyholders, hospitals, n=400)
    # Historical claims used a placeholder member_id; resolve to each policy's first member.
    members_by_policy: dict[str, str] = {}
    for m in members:
        members_by_policy.setdefault(m["policy_number"], m["member_id"])
    for c in hist_claims:
        c["member_id"] = members_by_policy[c["policy_number"]]

    all_claims = scenario_claims + hist_claims
    all_records = scenario_records + hist_records
    claims_by_id = {c["claim_id"]: c for c in all_claims}

    print("Generating PDF documents for S01/S02/S06/S09/S10...")
    doc_manifest = generate_all(claims_by_id, hospitals_by_id)
    for claim_id, tag in EXTRA_POISON_TARGETS:
        doc_manifest.append(generate_extra_poisoned(claim_id, tag))

    print("Hashing + extracting text for each document...")
    document_rows = []
    for doc in doc_manifest:
        document_rows.append(
            {
                "claim_id": doc["claim_id"],
                "file_ref": doc["file_ref"],
                "doc_type": doc["doc_type"],
                "extracted_text": _extract_pdf_text(doc["file_ref"]),
                "sha256": _sha256_file(doc["file_ref"]),
                "is_poisoned": doc["is_poisoned"],
            }
        )
    n_poisoned = sum(1 for d in document_rows if d["is_poisoned"])
    print(f"  {len(document_rows)} documents, {n_poisoned} poisoned (spec: 5)")
    assert n_poisoned == 5, f"expected exactly 5 poisoned documents, got {n_poisoned}"

    print("Embedding policy terms (Gemini)...")
    embeddings = _embed_policy_terms()

    print("Writing to database...")
    session = get_direct_session()
    try:
        # Idempotent: clear dependent tables first (FK order), then reference tables.
        for model in [
            Payment, ClaimDocument, MedicalRecord, Claim, BankDetail,
            PolicyholderMember, Policyholder, Hospital, PolicyTerm,
        ]:
            session.query(model).delete()
        session.commit()

        session.bulk_insert_mappings(Hospital, hospitals)
        session.bulk_insert_mappings(Policyholder, policyholders)
        session.bulk_insert_mappings(PolicyholderMember, members)
        session.bulk_insert_mappings(BankDetail, bank_details)
        session.bulk_insert_mappings(Claim, all_claims)
        session.bulk_insert_mappings(MedicalRecord, all_records)
        session.bulk_insert_mappings(ClaimDocument, document_rows)

        for clause, embedding in zip(CLAUSES, embeddings, strict=True):
            session.add(PolicyTerm(plan=clause["plan"], clause_id=clause["clause_id"], text=clause["text"], embedding=embedding))

        session.commit()
    finally:
        session.close()

    print("\nSeed complete:")
    print(f"  policyholders: {len(policyholders)}  members: {len(members)}  bank_details: {len(bank_details)}")
    print(f"  hospitals: {len(hospitals)} ({len(watchlisted_ids)} watchlisted)")
    print(f"  claims: {len(all_claims)} ({len(scenario_claims)} scenario + {len(hist_claims)} historical)")
    print(f"  medical_records: {len(all_records)}")
    print(f"  claim_documents: {len(document_rows)} ({n_poisoned} poisoned)")
    print(f"  policy_terms: {len(CLAUSES)}")


if __name__ == "__main__":
    main()
