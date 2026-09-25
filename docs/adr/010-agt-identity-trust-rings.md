# ADR-010: AGT identity, trust scoring, and rings gate credential issuance

- **Status:** accepted

## Context
AGT policies decide whether an action is allowed, and JWTs decide whether data can be
read. If the two aren't linked, a token could be issued to an agent that AGT considers
unverified or misbehaving.

## Decision
Chain them: **AGT identity → trust check → scoped JWT → gateway.**
- The token service mints a JWT only for a verified AGT identity (signed assertion).
- Sensitive scopes require a minimum AGT trust score (per agent, per request).
- Agents are placed in AGT privilege rings; payout and medical_reviewer are most restricted.
- Rules ID-001, TRUST-001, RING-001 are added to the security matrix.

## Alternatives considered
- **JWTs keyed on agent name only** — no cryptographic proof of which agent asked.
- **Global (cross-request) trust scores** — one attacked claim could lock an agent out
  of all claims; per-request scoping limits the blast radius.
- **Using AGT identity without JWTs** — no row/field-level control at the data layer.

## Consequences
- Uses more of AGT than the policy engine alone, which is a stronger showcase of the framework.
- Trust thresholds need tuning from eval results.
- Depends on AGT preview APIs for identity and trust; verify against the pinned version.
