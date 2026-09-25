# ADR-007: Medical data isolated behind a structured finding

- **Status:** accepted

## Context
Several agents need medical conclusions (diagnosis, pre-existing, exclusion) but not the
medical record itself.

## Decision
Only `medical_reviewer` reads `medical_records`. It emits a schema-validated **medical
finding** (ICD-10 code + boolean flags + confidence). Other agents receive only this.
Free-text notes go to officers only.

## Alternatives considered
- **All agents read medical records** — simpler, violates data minimisation.
- **Redacted copies of records** — redaction of free text is unreliable.

## Consequences
Clean DPDP minimisation story; coverage decisions depend on finding quality, so the
finding is covered by evals. Invalid findings route to a human.
