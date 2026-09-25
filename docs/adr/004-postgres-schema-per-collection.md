# ADR-004: One Postgres, schema per collection, access only via gateway

- **Status:** accepted

## Context
Collections have very different sensitivity. We need isolation without running many databases.

## Decision
Single Postgres 16 instance, one schema per collection, pgvector for plan terms.
Only the data gateway has DB credentials. Pseudonymisation via keyed HMAC in the gateway.

## Alternatives considered
- **Separate databases per collection** — stronger isolation, more ops overhead.
- **Row-level security only** — good complement, but scope/field logic is clearer in the gateway.
- **Separate vector DB** — unnecessary at this scale.

## Consequences
Isolation is enforced by the gateway, so gateway tests are security-critical.
Postgres RLS can be added later as a second layer.
