Submit ClaimGuard scenario **S02** (docs/use-case.md §8: room-rent excess, high value).

claim_id: CLM-2026-018834

Priya Raman (policy `KHA-SIL-004512`, Silver plan) was admitted for pneumonia
for 4 days in a room costing ₹8,000/day — above the Silver plan's ₹5,000/day
room rent cap. Total claimed: ₹83,000. Her claim and its documents are
already seeded in the environment's database.

Submit this claim to the ClaimGuard AgentOS API (`POST /claims` with
`{"claim_id": "CLM-2026-018834"}`) and report back the response.

Expected outcome: the claim stops at `pending_human` — the payable amount
after the ₹12,000 room-rent-excess deduction is ₹71,000, which exceeds the
₹50,000 auto-approval ceiling (T2), so it requires officer review even
though there are no fraud flags or policy violations. No payout is
attempted before that review happens.
