# ADR-006: Harbor for scenario evaluation, including governance evidence

- **Status:** proposed (environment approach to be confirmed)

## Context
Unit tests prove individual controls. We also need end-to-end, reproducible evaluation of
agent behaviour, including attacks, that can run on every change.

## Decision
Use **Harbor** with a custom agent adapter and one task per scenario (S01–S10). Verifiers
check outcome **and** governance evidence (audit entries by rule ID, exported spans).

## Open question
Environment isolation: fresh stack per task vs. shared stack with reset. Decide after
checking the installed Harbor version's environment support; update this ADR.

## Alternatives considered
- **pytest end-to-end only** — works, but no standard harness, parallelism, or reporting.
- **Phoenix evals only** — good for LLM output quality, not for containerized scenario runs.

## Consequences
Scenario suite doubles as the acceptance test set and regression gate.
