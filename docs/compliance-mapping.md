# ClaimGuard — Compliance Mapping

Maps regulatory expectations to concrete controls and the tests that prove them.
This is a **demonstration of compliance-by-design**, not legal advice or a certified
compliance claim. Clause wording is paraphrased; check the current texts before
presenting specifics.

Every row must have a passing test or Harbor task before the demo.

---

## 1. DPDP Act 2023 (India) — personal data protection

| Principle | Control in ClaimGuard | Evidence / test |
|---|---|---|
| **Purpose limitation** | Tokens bound to one `claim_id` and one scope; data used only for that claim's assessment | `test_token_row_binding`, S07 |
| **Data minimisation** | Coverage gets plan, SI, start date, age only; fraud sees pseudonyms; medical text stays with medical_reviewer | `test_field_allowlists`, `test_medical_access_only_reviewer`, S04 |
| **Accuracy** | Claimed vs bill total check; schema-validated findings; officer review for exceptions | S05, `test_finding_schema_rejects_invalid` |
| **Storage limitation** | Tokens revoked at terminal state; retention setting per collection (documented, enforced by a cleanup job for synthetic data) | `test_tokens_revoked_on_completion` |
| **Security safeguards** | Short-lived EdDSA tokens, separate signing service, fail-closed policies, redacted traces | `make test-security`, S08 |
| **Accountability** | Hash-chained audit log; rule IDs on every decision; ADRs for design choices | `test_audit_chain_integrity` |
| **Notice & rights (access, correction)** | Policyholder sees own claims, breakdown and reasons; correction via resubmission | S09, console walkthrough |
| **Breach readiness** | Medical-data access report shows who accessed what and when; anomaly = denied access spikes | Compliance dashboard |

## 2. Insurance-specific expectations (IRDAI policyholder protection, paraphrased)

| Expectation | Control | Evidence / test |
|---|---|---|
| Clear reasons for deductions and rejections | Every deduction carries `clause_id`; officer must enter a reason to reject | S01 breakdown, S03 |
| A human is accountable for rejecting a claim | STATE-001: no `rejected` without officer decision | S03, `test_no_ai_only_rejection` |
| Timely settlement | Auto-settlement for T2; SLA timer on `pending_human` queue shown to officers | S01 latency in scoreboard |
| Fair, consistent decisions | Deterministic plan-term rules applied in code where possible; eval suite run on every change | Harbor regression runs |

## 3. OWASP Top 10 for Agentic Applications

Map each risk to the controls that address it. Verify the risk names against the current
OWASP list before presenting.

| Risk area | Control | Scenario |
|---|---|---|
| Goal hijack / prompt injection | Documents treated as data; AGT payout rules independent of model output | S06 |
| Tool misuse | Per-agent tool allowlist (GOV-001), argument checks (DATA-002) | S06, S07 |
| Identity & privilege abuse | AGT cryptographic agent identity, trust-gated one-scope tokens, no widening on delegation | S07, S08 |
| Memory / context poisoning | No long-term agent memory of document content across claims | Design + test |
| Insecure inter-agent communication | Schema-validated findings only; no raw data passed between agents | `test_finding_schema_*` |
| Cascading failures | Fail closed + route to human; per-request tool budget (GOV-002) | `test_tool_budget` |
| Human-agent trust exploitation | Officers see evidence and clause refs, not just a recommendation | Console review |
| Rogue agent behaviour | Trust score decays on denials and cuts off sensitive scopes (TRUST-001); every action audited | S06 |

---

## 4. Compliance report (generated)

`make compliance-report` produces a Markdown/HTML report for Divya containing:

- Test results for every row above
- Harbor scoreboard (outcome + governance pass rates)
- Medical-data access summary (by agent and by officer break-glass)
- Denied actions by rule ID
- Audit chain integrity check result
