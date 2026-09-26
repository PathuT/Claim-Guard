Submit ClaimGuard scenario **S09** (docs/use-case.md §8: missing document).

claim_id: CLM-2026-018840

Priya's claim has a final bill uploaded but no discharge summary at all.
The claim and its (incomplete) documents are already seeded in the
environment's database.

Submit this claim to the ClaimGuard AgentOS API (`POST /claims` with
`{"claim_id": "CLM-2026-018840"}`) and report back the response.

Expected outcome: the claim stops at `needs_resubmission` before any
medical review or payout is attempted — the document-completeness check
runs before the supervisor (and therefore before any agent/LLM call), since
a missing required document isn't something an agent needs to discover by
trying and failing to extract it.
