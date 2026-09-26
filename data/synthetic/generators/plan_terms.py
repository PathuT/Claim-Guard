"""Plan terms (policy_terms) — Silver/Gold wording, clause by clause, from
docs/use-case.md §5. Chunked by clause so coverage's retrieval (M4) can cite a
`clause_id` for every deduction, exactly as the settlement breakdown requires
("₹1,200 deducted: non-payable items (clause 5.G1)" in the S01 walkthrough).

Clause IDs are invented here (not given verbatim in the docs) but the *content*
of every clause matches §5 exactly. If §5 changes, update this list to match —
docs/CLAUDE.md: "insurance rules follow use-case.md section 5 exactly."
"""

from __future__ import annotations

CLAUSES: list[dict] = [
    # --- Sum insured ---
    {"plan": "Silver", "clause_id": "5.S1", "text": "Sum insured: ₹5,00,000 per policy year."},
    {"plan": "Gold", "clause_id": "5.G1_SI", "text": "Sum insured: ₹10,00,000 per policy year."},
    # --- Room rent cap ---
    {"plan": "Silver", "clause_id": "5.S2", "text": "Room rent cap: ₹5,000 per day. Any excess over this cap is deducted from the claim."},
    {"plan": "Gold", "clause_id": "5.G2", "text": "Room rent: no cap, single private room covered in full."},
    # --- Co-pay ---
    {"plan": "Silver", "clause_id": "5.S3", "text": "Co-pay: 0% for members under age 60. 20% co-pay applies for members aged 60 or above."},
    {"plan": "Gold", "clause_id": "5.G3", "text": "Co-pay: 0% for all members regardless of age."},
    # --- Waiting periods ---
    {"plan": "Silver", "clause_id": "5.S4", "text": "Initial waiting period: 30 days from policy start date. Accidents are exempt from this waiting period."},
    {"plan": "Gold", "clause_id": "5.G4", "text": "Initial waiting period: 30 days from policy start date. Accidents are exempt from this waiting period."},
    {"plan": "Silver", "clause_id": "5.S5", "text": "Specific illness waiting period (cataract, hernia, knee replacement): 2 years from policy start date."},
    {"plan": "Gold", "clause_id": "5.G5", "text": "Specific illness waiting period (cataract, hernia, knee replacement): 2 years from policy start date."},
    {"plan": "Silver", "clause_id": "5.S6", "text": "Pre-existing disease (PED) waiting period: 3 years from policy start date."},
    {"plan": "Gold", "clause_id": "5.G6", "text": "Pre-existing disease (PED) waiting period: 2 years from policy start date."},
    # --- Minimum hospitalisation ---
    {"plan": "Silver", "clause_id": "5.S7", "text": "Minimum hospitalisation: 24 continuous hours, except for listed day-care procedures which are covered regardless of duration."},
    {"plan": "Gold", "clause_id": "5.G7", "text": "Minimum hospitalisation: 24 continuous hours, except for listed day-care procedures which are covered regardless of duration."},
    # --- Non-payables (both plans) ---
    {"plan": "Silver", "clause_id": "5.G1", "text": "Non-payable items are never covered under any plan: toiletries, attendant charges, registration and admin fees, and food for attendants."},
    {"plan": "Gold", "clause_id": "5.G1", "text": "Non-payable items are never covered under any plan: toiletries, attendant charges, registration and admin fees, and food for attendants."},
    # --- Exclusions (both plans) ---
    {"plan": "Silver", "clause_id": "5.EX1", "text": "Exclusions: cosmetic surgery is never covered. Dental treatment is excluded unless required due to an accident."},
    {"plan": "Gold", "clause_id": "5.EX1", "text": "Exclusions: cosmetic surgery is never covered. Dental treatment is excluded unless required due to an accident."},
    # --- Procedural rules (both plans) ---
    {"plan": "Silver", "clause_id": "5.P1", "text": "Claims must be submitted within 30 days of discharge."},
    {"plan": "Gold", "clause_id": "5.P1", "text": "Claims must be submitted within 30 days of discharge."},
    {"plan": "Silver", "clause_id": "5.P2", "text": "The same hospital bill can be claimed only once across the policy."},
    {"plan": "Gold", "clause_id": "5.P2", "text": "The same hospital bill can be claimed only once across the policy."},
    {"plan": "Silver", "clause_id": "5.P3", "text": "The claimed amount must match the total of the itemised hospital bill, within a ±₹10 rounding tolerance."},
    {"plan": "Gold", "clause_id": "5.P3", "text": "The claimed amount must match the total of the itemised hospital bill, within a ±₹10 rounding tolerance."},
    {"plan": "Silver", "clause_id": "5.P4", "text": "Room rent excess: only the portion of room charges above the plan's daily cap is deducted; other charges are unaffected."},
    {"plan": "Gold", "clause_id": "5.P4", "text": "Room rent excess: only the portion of room charges above the plan's daily cap is deducted; other charges are unaffected."},
    {"plan": "Silver", "clause_id": "5.P5", "text": "Payout is made only to the policyholder's registered bank account."},
    {"plan": "Gold", "clause_id": "5.P5", "text": "Payout is made only to the policyholder's registered bank account."},
]
