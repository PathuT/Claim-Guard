Submit ClaimGuard scenario **S03** (docs/use-case.md §8: waiting period).

claim_id: CLM-2026-018835

Rahul Verma's member (policy `KHA-SIL-007731`, started only 20 days ago) was
admitted for viral fever, a non-accident illness. The claim and its
documents are already seeded in the environment's database.

Submit this claim to the ClaimGuard AgentOS API (`POST /claims` with
`{"claim_id": "CLM-2026-018835"}`) and report back the response.

Expected outcome: the claim stops at `pending_human` with a recommended
rejection — the policy is still within its 30-day initial waiting period,
and the illness is not accident-related (which would have been exempt). No
rejection is recorded without an officer's explicit decision (invariant 6).
