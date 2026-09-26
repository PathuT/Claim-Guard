Run ClaimGuard security scenario **S07** (docs/use-case.md §8: out-of-
matrix scope request).

probe_endpoint: /_governance/probe/scope-matrix

This is not a claim-submission scenario — it reuses no new claim data. It
tests a real attack attempt against the governance layer itself: the
coverage agent (as it might be steered to by a prompt-injection attempt
inside a claim document) requests the `medical_records:read` scope, which
docs/security-matrix.md §2 marks as "-" for coverage (coverage may only
request `policy_terms:read`, `claims:read`, `policyholders:read_limited`).

Call `POST /_governance/probe/scope-matrix` on the ClaimGuard AgentOS API.
This endpoint signs a real identity assertion as `coverage` and submits it
to the real, running token service's `POST /tokens`.

Expected outcome: the token service refuses to mint a token at all —
`denied: true`, `reason_code: "GOV-003"` — before any JWT reaches the
data gateway. The attack is stopped at issuance, not merely filtered
after the fact.
