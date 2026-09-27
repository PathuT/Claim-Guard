# ADR-012: Compliance kill switch for automated payouts (GOV-004)

- **Status:** accepted
- **Date:** 2026-09-27

## Context
T2 payouts (≤ ₹50,000, all checks passed) move money with no human in the loop. The
PAY rules check each payout against trusted values, but they cannot catch a problem
nobody has written a rule for yet: a new fraud pattern, a bad plan-terms load, a model
regression. When compliance (Divya) suspects something like that, she needs to stop
agents paying out **now**, without a deploy and without stopping the humans who are
deciding T3 claims. The pause itself has to be accountable: who did it, when, and why.

## Decision
- A new rule **GOV-004** in `governance/rules.py`, evaluated first among the rules:
  `execute_payout` is denied while automated payouts are frozen **unless** the call
  carries an `officer_approval_id`. Officer-approved payouts are human decisions and
  still go through.
- The freeze state is stored in a small JSON file (`governance/controls.py`, path from
  `GOVERNANCE_CONTROLS_PATH`, default `governance_controls.json` in the backend working
  directory). AgentOS and the officer API are separate processes, so the state must be
  shared. Writes are atomic (temp file + `os.replace`). The file is re-read on every
  `execute_payout` check, so there is no cache to go stale.
- `check_and_audit()` reads the state and puts it in `ctx.trusted["payout_freeze"]`
  for every `execute_payout` call, **replacing** any value the caller supplied. The rule
  accepts only the state object the adapter produced, so a missing or spoofed value is
  denied.
- Reads fail closed (invariant 7). A missing file means "never touched, not frozen". A
  file that is unreadable, not JSON, or has a non-boolean `frozen` means **frozen**.
- Toggling is governed and audited. `POST /governance/payout-freeze` (on AgentOS)
  requires `officer_id` and a non-empty `reason`. It runs `check_and_audit()` as
  `compliance_officer` / `set_payout_freeze` (GOV-001 allowlist; no agent holds this
  tool) and writes the state only when that is allowed. Every freeze and resume, with
  its reason, lands in the hash-chained FlightRecorder log. `GET` returns the state.
- A frozen automated payout needs no new routing. The supervisor already treats a
  `ToolCallDenied` from `governed_payout` as "hand the claim to a human officer", so the
  claim goes to `pending_human` with GOV-004 in the audit log and the trace.

## Alternatives considered
- **Environment variable or config flag:** needs a restart to change, leaves no audit
  trail, and is invisible to compliance.
- **In-memory flag in AgentOS:** the officer API process would not see it, and it
  would reset silently on restart.
- **Postgres row:** durable and shared, but every governance check would then depend on
  the database being reachable. The adapter reads no other data from Postgres (callers
  pass trusted values in), and this would be the only exception. A local file matches
  how the audit log (`flight_recorder.db`) is already stored.
- **Freezing all payouts, including officer-approved ones:** it would also block the
  human path that should handle claims during an incident. Officers can simply stop
  approving if they need to.
- **Failing open on a corrupt file:** a damaged control would silently restart
  automated money movement. That breaks invariant 7.

## Consequences
- Compliance can stop automated payouts from the console in one step. While frozen,
  every T2 claim goes to the officer queue instead of being paid.
- If the controls file is damaged, the system stops paying automatically until a
  compliance officer resumes it. Resuming rewrites a valid file, and that resume is
  audited too.
- The file is per deployment and lives next to `flight_recorder.db`. A multi-host
  deployment would need to move it to a shared store and keep the same fail-closed
  read semantics.
- Tests must point `GOVERNANCE_CONTROLS_PATH` at a temporary file. The existing
  governance tests read the default path; they pass only while the real switch is off.
