# ClaimGuard — Security Matrix

**Single source of truth for access.** Token service scopes, gateway filters, and AGT
policies are all derived from this file. If code and this file disagree, the code is wrong.

---

## 1. Scope vocabulary

| Scope suffix | Meaning |
|---|---|
| `read` | Read rows bound to the current claim, all allowed fields for that collection |
| `read_limited` | Read rows bound to the current claim, **field allowlist only** |
| `read_pseudonymised` | Read across claims, identifiers replaced by keyed hashes, PII fields removed |
| `write` | Insert/update rows bound to the current claim |
| `append` | Insert only, never update or delete |

**Row binding:** unless the scope is `read_pseudonymised`, the gateway only returns rows
where `claim_id` (or the claim's `policy_number`) equals the token's `claim_id` claim.

---

## 2. Agent × collection matrix

`—` = no access. Anything not listed is denied.

| Agent | policyholders | bank_details | policy_terms | claims | claim_documents | medical_records | hospitals | payments | audit |
|---|---|---|---|---|---|---|---|---|---|
| `supervisor` | — | — | — | — | — | — | — | — | — |
| `intake` | — | — | — | write | read | write | — | — | — |
| `medical_reviewer` | — | — | — | read | — | **read** | — | — | — |
| `coverage` | read_limited | — | read | read | — | — | — | — | — |
| `fraud` | — | — | — | read_pseudonymised | — | — | read | — | — |
| `payout` | — | read | — | read | — | — | — | write | — |
| AGT adapter (system) | — | — | — | — | — | — | — | — | append |

`supervisor` coordinates only. It holds findings passed to it, never raw data.

## 3. Field allowlists

| Scope | Allowed fields |
|---|---|
| `policyholders:read_limited` | plan, sum_insured, start_date, member.age, member.member_id |
| `claims:read_pseudonymised` | claim_pseudo_id, person_pseudo_id, hospital_id, admission_date, discharge_date, claimed_amount, doc_hashes, status |
| `claims:read` (medical_reviewer) | claim_id, admission_date, discharge_date, stated_illness |
| `claims:read` (coverage, payout) | claim_id, member_id, dates, claimed_amount, line_items, status, assessment |
| `bank_details:read` | account_number, ifsc (row-bound to claim's policy) |

## 4. Token lifetimes

| Scope | TTL | Reason |
|---|---|---|
| `medical_records:*` | 120 s | Most sensitive; one review pass |
| `bank_details:read` | 60 s | Needed only for the payout call |
| `payments:write` | 60 s | Single action |
| everything else | 300 s | Normal task duration |

Tokens for a `req_id` are **revoked when the request reaches a terminal or
`pending_human` state**, even if not yet expired.

---

## 5. JWT claims

```json
{
  "iss": "claimguard-token-service",
  "sub": "agent:coverage",
  "aud": "data-gateway",
  "scope": "policy_terms:read",
  "req_id": "req_01J9Z...",
  "claim_id": "CLM-2026-018833",
  "parent": "agent:supervisor",
  "jti": "a3f1...",
  "iat": 1790244000,
  "exp": 1790244300,
  "kid": "ts-2026-09"
}
```

- Signed with **EdDSA (Ed25519)**. Gateway verifies with the public key from the token
  service's JWKS endpoint.
- **One scope per token.** An agent needing two collections gets two tokens.
- `parent` records the delegation chain; the token service rejects a request if the
  requested scope isn't allowed for `sub` in section 2 (delegation never widens).

## 6. Gateway validation checklist (all must pass)

1. Signature valid for a known `kid`
2. `aud` = `data-gateway`, `iss` correct
3. `exp` in the future (max 5 s clock skew)
4. `jti` not revoked
5. `scope` matches the requested collection and operation
6. Row binding: requested rows belong to the token's `claim_id`
7. Response filtered to the field allowlist

Any failure → 403 with a reason code, audit entry, and `gateway.access` span with
`decision=deny`.

---

## 7. Tool allowlist per agent (enforced by AGT)

| Agent | Allowed tools |
|---|---|
| `supervisor` | `delegate`, `set_claim_state` (non-terminal only), `request_human_review` |
| `intake` | `read_claim_documents`, `write_claim_items`, `write_medical_facts` |
| `medical_reviewer` | `read_medical_record`, `read_claim_basic`, `submit_medical_finding` |
| `coverage` | `search_policy_terms`, `read_policy_limited`, `read_claim`, `submit_assessment` |
| `fraud` | `search_claims_pseudonymised`, `read_hospital`, `submit_fraud_screen` |
| `payout` | `read_bank_details`, `execute_payout` |

Any tool not in the agent's row is denied, even if the tool exists.

Human console roles whose actions are routed through the same adapter so they land in
the same audit log (they are not agents and hold no data scopes):

| Role | Governed tools |
|---|---|
| `claims_officer` | `break_glass_discharge_summary_access` |
| `compliance_officer` | `set_payout_freeze` (GOV-004 kill switch) |

---

## 8. AGT policy rules

Rule IDs appear in audit entries, spans, and Harbor verifiers.

| Rule | Condition | Effect |
|---|---|---|
| **GOV-001** | Tool not in agent's allowlist | Deny |
| **GOV-002** | Per-request tool-call budget exceeded (e.g. 40 calls) | Deny (circuit breaker) |
| **GOV-003** | Requested scope not in matrix for this agent | Deny |
| **GOV-004** | `execute_payout` while compliance has frozen automated payouts, and no officer approval record. Freeze state is read by the adapter from the governance controls store, never from the caller; an unreadable store counts as frozen (fail closed). See ADR-012 | Deny, route to human |
| **PAY-001** | Payout amount ≠ assessed payable for the claim | Deny |
| **PAY-002** | Payout account ≠ registered account for the claim's policy | Deny |
| **PAY-003** | Payout > ₹50,000 without an officer approval record | Deny |
| **PAY-004** | Claim has any fraud flag and no officer approval record | Deny |
| **PAY-005** | Second payout for same claim | Deny |
| **PAY-006** | Payout exceeds remaining sum insured | Deny |
| **STATE-001** | Transition to `rejected` without officer decision record | Deny |
| **STATE-002** | Transition to `approved`/`paid` skipping required steps | Deny |
| **DATA-001** | `medical_records:*` requested by any agent except intake (write) and medical_reviewer (read) | Deny |
| **DATA-002** | Tool arguments contain an account number not from `bank_details` | Deny |

Policies are written in YAML for simple allow/deny rules and Rego where logic is needed
(PAY rules). The exact file format must follow the installed AGT version's schema —
check its docs before writing them.

Illustrative Rego for PAY-001/002/003 (adapt to AGT's input shape):

```rego
package claimguard.payout

default allow := false

allow if {
    input.tool == "execute_payout"
    input.args.amount == input.context.assessed_payable
    input.args.account_ref == input.context.registered_account_ref
    within_auto_limit_or_approved
}

within_auto_limit_or_approved if input.args.amount <= 50000
within_auto_limit_or_approved if input.context.officer_approval_id != null
```

`input.context` values are fetched by the AGT adapter from trusted stores, **never from
the agent's arguments**.

---

## 9. Human roles (console RBAC)

| Role | Can |
|---|---|
| `policyholder` | Submit claims for own policy, view own claims and breakdowns |
| `claims_officer` | View T3 queue, findings, flags, clauses; decide; open full discharge summary via **audited break-glass** (reason required) |
| `compliance_officer` | View audit log, denials, medical-data access report, compliance report; **freeze / resume automated payouts** (GOV-004 kill switch, reason required, audited as `set_payout_freeze`); cannot decide claims |
| `platform_engineer` | View traces and eval results; no claim data in console |

## 10. Keys and secrets

- Token service Ed25519 key pair; private key only in token-service container; `kid`
  rotation supported (old key kept for validation until its tokens expire).
- Pseudonymisation HMAC key only in the data gateway.
- LLM API key only in agentos.
- All from environment variables / Docker secrets; `.env.example` committed, `.env` never.

---

## 11. Agent identity, trust gating, and privilege rings (AGT)

This section ties AGT and the JWTs together into one chain:
**AGT identity → trust check → scoped JWT → gateway**.

### 11.1 Identity

- Every agent is registered with an **AGT identity** (Ed25519 key pair) at startup.
  Private keys live only in the agentos container's secret store.
- To get a token, the AGT adapter sends the token service a **signed identity assertion**
  (agent id, `req_id`, requested scope, timestamp) signed with the agent's AGT key.
- The token service verifies the signature against the registered public key.
  Unknown agent, bad signature, or stale timestamp (> 30 s) → refuse.
- The JWT `sub` is the verified AGT identity, so every token traces back to a
  cryptographic agent identity, not just a name string.

### 11.2 Trust-score gating

AGT keeps a behavioural trust score per agent (0–1000) that decays on anomalous
actions (e.g. repeated denials). Scores are scoped **per agent per request** in this
system, so one bad claim doesn't lock an agent out of every other claim.

| Scope | Minimum trust score |
|---|---|
| `medical_records:read` | 700 |
| `bank_details:read` | 800 |
| `payments:write` | 800 |
| all other scopes | 400 |

- Below threshold → token refused with reason `TRUST-001`, claim routed to `pending_human`.
- Every denial (GOV/PAY/DATA/STATE rules) reports to AGT so the score reflects behaviour.
- Delegation respects AGT trust ceilings: a delegated agent can't exceed its parent's trust.
- Scenario S06 should show the score dropping after injected payout attempts.

Thresholds are starting values; tune them from Harbor results and record changes in an ADR.

### 11.3 Privilege rings

Map agents to AGT's execution rings (check the installed version's ring definitions):

| Ring | Contents |
|---|---|
| Most privileged | AGT kernel / governance infrastructure only |
| Standard | `supervisor`, `intake`, `fraud` |
| Restricted | `coverage` |
| Most restricted | `medical_reviewer`, `payout` (sensitive data or money; tightest limits, lowest tool budgets) |

### 11.4 New rule IDs

| Rule | Condition | Effect |
|---|---|---|
| **ID-001** | Identity assertion missing, invalid, or stale | Refuse token |
| **TRUST-001** | Agent trust score below scope threshold | Refuse token, route to human |
| **RING-001** | Tool call exceeds the agent's ring permissions or budget | Deny |
