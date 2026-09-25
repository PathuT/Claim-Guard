# ADR-003: Own token service issuing one-scope, short-lived JWTs

- **Status:** accepted

## Context
AGT decides whether an *action* is allowed. We also need the *data layer* to refuse
access independently, so a bug or bypass in one layer doesn't expose data.

## Decision
A separate **token service** mints EdDSA-signed JWTs: one agent, one scope, one claim,
TTL ≤ 300 s (shorter for medical and bank data). A separate **data gateway** verifies
them with the public key only. Tokens are revoked when a request ends.

## Alternatives considered
- **Long-lived per-agent API keys** — no per-claim binding; leaked key = broad access.
- **Keycloak / full OAuth server** — production-grade, but heavy for the timeline; our
  claims mirror OAuth token-exchange concepts so migration is straightforward.
- **AGT identity alone** — covers agent identity and trust, not row/field-level data access.
  So we combine them: AGT identity + trust score are prerequisites for minting a JWT (ADR-010).

## Consequences
- Defense in depth: action layer (AGT) + data layer (JWT) must both allow.
- Separate containers keep the private key away from agent code.
- More tokens per claim (one per scope) — acceptable; issuance is cheap.
