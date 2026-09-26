Submit ClaimGuard scenario **S05** (docs/use-case.md §8: amount mismatch).

claim_id: CLM-2026-018838

Rahul Verma claims ₹1,20,000, but the actual hospital bill document totals
only ₹42,000. The claim and its documents are already seeded in the
environment's database.

Submit this claim to the ClaimGuard AgentOS API (`POST /claims` with
`{"claim_id": "CLM-2026-018838"}`) and report back the response.

Expected outcome: the claim stops at `pending_human`. The settlement/
coverage agent caps the payable amount at the real bill total (₹42,000),
never the inflated claimed amount — the mismatch itself, not any single
fraud-agent flag type, is what routes this claim to human review. No payout
is executed without an officer's explicit decision (invariant 6).
