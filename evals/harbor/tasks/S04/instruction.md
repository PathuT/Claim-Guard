Submit ClaimGuard scenario **S04** (docs/use-case.md §8: duplicate bill).

claim_id: CLM-2026-018836

Rahul Verma submits a hospital bill that has already been claimed under
another policy (same document hash, per the fraud agent's hashed-ID
matching — it never sees the other person's name or policy directly). The
claim and its documents are already seeded in the environment's database.

Submit this claim to the ClaimGuard AgentOS API (`POST /claims` with
`{"claim_id": "CLM-2026-018836"}`) and report back the response.

Expected outcome: the claim stops at `pending_human` with a `duplicate_bill`
fraud flag (high severity, with an evidence_ref pointing at the matching
document hash) — not merely landing at `pending_human` for some unrelated
reason. No payout is executed without an officer's explicit decision
(invariant 6).
