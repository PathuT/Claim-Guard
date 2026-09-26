Run ClaimGuard security scenario **S08** (docs/use-case.md §8: expired
token replay).

probe_endpoint: /_governance/probe/token-replay

This is not a claim-submission scenario. It tests a real attack attempt
against the governance layer itself: an agent replays a token after its
TTL has expired, attempting to reuse access it should no longer have.

Call `POST /_governance/probe/token-replay` on the ClaimGuard AgentOS API.
This endpoint issues a real, validly-signed token for the `payout` agent's
`bank_details:read` scope (60s TTL — the shortest configured scope), waits
past its expiry, then replays it against the real, running data gateway's
`POST /query`. This call takes roughly 60-70 seconds to complete (it
genuinely waits out the token's TTL server-side) — allow enough time.

Expected outcome: the gateway refuses the replayed token — `denied: true`,
`reason_code: "GATEWAY-EXPIRED"`. The token's jti is what the gateway's own
tracing records; the raw token is never logged.
