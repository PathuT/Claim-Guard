# ADR-008: Tiered autonomy and no AI-only rejections

- **Status:** accepted

## Context
Automation should speed up clean claims without letting agents make high-impact,
hard-to-reverse decisions alone.

## Decision
Four tiers (T0–T3). Auto payout only ≤ ₹50,000 with no flags. Any rejection, fraud flag,
exclusion/waiting-period issue, or larger payout requires an officer decision, enforced by
AGT rules (PAY-003, PAY-004, STATE-001) and the state machine.

## Alternatives considered
- **Full autonomy** — fastest, unacceptable accountability risk.
- **Human review of every claim** — safe, removes the benefit.

## Consequences
Officer queue and SLA tracking are required features. Thresholds are configuration.
