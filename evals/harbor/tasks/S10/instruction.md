Submit ClaimGuard scenario **S10** (docs/use-case.md §8: day-care + watchlisted hospital).

claim_id: CLM-2026-018841

Rahul Verma had a same-day, ~10-hour hospital stay (not a listed day-care
procedure, and short of the minimum hospitalisation duration) at a
watchlisted hospital. The claim and its documents are already seeded in the
environment's database.

Submit this claim to the ClaimGuard AgentOS API (`POST /claims` with
`{"claim_id": "CLM-2026-018841"}`) and report back the response.

Expected outcome: the claim stops at `pending_human` with BOTH flags
visible — a coverage flag (`minimum_hospitalisation_not_met`) and a fraud
flag (`watchlisted_hospital`, with an evidence_ref naming the hospital_id)
— giving the reviewing officer both clause references, not just one.
