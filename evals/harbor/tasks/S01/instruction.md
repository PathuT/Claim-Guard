Submit ClaimGuard scenario **S01** (docs/use-case.md §8: happy path).

claim_id: CLM-2026-018833

Priya Raman (policy `KHA-SIL-004512`) was admitted for dengue fever for 3 days
at Sunrise Multispeciality Hospital and paid ₹38,500 herself. Her claim
(`CLM-2026-018833`) and its documents (final bill, discharge summary) are
already seeded in the environment's database.

Submit this claim to the ClaimGuard AgentOS API (`POST /claims` with
`{"claim_id": "CLM-2026-018833"}`) and report back the response.

Expected outcome: the claim is approved automatically (tier T2) and
₹37,300 is paid — ₹1,200 less than claimed, deducted as non-payable items
(registration fee + toiletries, clause 5.G1). No fraud flags. No human
review needed.
