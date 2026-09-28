# ADR-013: NeMo Guardrails as an advisory second opinion, not a decision-maker

- **Status:** accepted
- **Date:** 2026-09-28

## Context

ADR-011 rejected "an LLM judge" for the injection guardrail: probabilistic, costs
tokens, and can itself be attacked by the text it is judging. That reasoning still
holds. `scan_documents` (`backend/agents/guardrails.py`) remains the sole authority
for whether a claim is auto-payable, using a deterministic marker list.

But a marker list is a heuristic with a known failure mode: a novel phrasing (no
literal marker match) passes it silently, and ADR-011 already accepts this as the
cost of using deterministic code (PAY-001/PAY-002/DATA-001 still block the actions
an injection is trying to cause even if the scan misses it). NVIDIA NeMo Guardrails
(`nemoguardrails`, PyPI 0.24.1) offers a second, differently-shaped detector — an
LLM-based rail rather than a string match — that can catch phrasings the marker list
misses, and vice versa. Layering two independently-wrong detectors is the same
defence-in-depth argument this project already makes for tokens-plus-gateway
(ADR-003): a bypass of one still meets the other.

The risk is architectural, not technical: if NeMo's verdict is allowed to *clear* a
claim the marker list flagged, or to *authorize* anything, it quietly becomes the
kind of LLM judge ADR-011 rejected, and an attacker who can fool the rail-checking
model (a second prompt-injection surface) gains real leverage.

## Decision

Add NeMo Guardrails strictly as a second, advisory input to the existing
`document_guardrail` step — never a replacement, and never able to reduce caution.

- New module `backend/agents/nemo_guardrail.py`. Its only export,
  `check_injection(text: str) -> NemoScan`, runs NeMo's built-in jailbreak/injection
  rail against one document's extracted text and returns a flag plus whatever
  rationale NeMo gives. It has no access to governance, tokens, the gateway, or the
  workflow context — it cannot call anything, it only classifies text.
- NeMo is configured to call the **same model provider already selected for the
  agents** (`MODEL_PROVIDER`/`MODEL_ID` env vars, `agents/model_config.py`'s retry
  settings applied the same way) — no new API key, no new vendor account, keeping
  the model-agnostic stance of ADR-001.
- `document_guardrail` (`backend/agents/supervisor.py`) calls both detectors and
  ORs their results:
  `ctx.injection_suspected = scan.flagged or nemo_scan.flagged`.
  Neither detector can clear a flag the other raised. The existing
  `ctx.injection_markers` stays marker-list-only, so the audit trail keeps
  distinguishing "why": a new `ctx.nemo_flagged` (bool) and `ctx.nemo_rationale`
  (str) carry NeMo's own evidence separately, and both appear in the
  `guardrail.documents` span and the live event, exactly like the marker list's
  output does today.
- **Fail closed the same way as everything else, but the failure mode is
  "no opinion," not "no claim."** If NeMo errors (timeout, provider outage, bad
  config), `check_injection` catches it, sets `nemo_flagged=False`, records the
  error in `nemo_rationale`, and the step proceeds on the marker-list result alone
  — exactly today's behaviour. NeMo is additive caution, not a dependency the claim
  pipeline can be starved by; making its unavailability block claims would turn an
  advisory signal into a new denial-of-service surface, which is a worse outcome
  than "one fewer opinion for this claim."
- `nemoguardrails` is a new dependency (`backend/pyproject.toml`), gated behind
  `NEMO_GUARDRAILS_ENABLED=true` (default false) so it never becomes a hard
  requirement to run the existing test suite or `make up`.

## Alternatives considered

- **Replace the marker list with NeMo:** reopens ADR-011's own rejected option.
  Loses the "policy in code is not probabilistic" guarantee this project's whole
  governance story rests on, for a check that sits *before* code governance even
  starts.
- **Let NeMo's verdict override the marker list either way (AND instead of OR):**
  would let NeMo's absence or a false "clear" *reduce* caution below what the
  deterministic scan alone provides. Rejected: an advisory layer must only add
  caution, never remove it.
- **Run NeMo synchronously and block the claim if it can't be reached:** turns an
  optional second opinion into a new availability dependency for every claim.
  Rejected per invariant 7's spirit (fail closed on real errors) but this isn't
  a security-relevant path failing — it's an enhancement being unavailable, so
  fail *open* to "marker list only," not closed to "no claim."
- **NVIDIA-hosted NIM guardrail model (`llama-3.1-nemoguard-8b-content-safety`) via
  a new `NVIDIA_API_KEY`:** purpose-trained for this, but adds a new vendor
  dependency and secret for a project that otherwise deliberately stays
  model-agnostic. Left as a config option (`MODEL_PROVIDER=nvidia` would work if a
  user sets it up) but not the default.

## Consequences

- A phrasing that evades the marker list but reads as an injection to an LLM rail
  now still forces T3, widening real coverage against S06-style attacks without
  touching PAY-001/PAY-002/DATA-001's authority over money and medical data.
- Two failure surfaces to reason about instead of one: the marker list's blind
  spots, and NeMo's own (a rail-checking LLM can itself be fooled by adversarial
  text, same caveat as ADR-011 gave for an LLM judge — this is why it can only add
  caution, never remove it).
- A new dependency and, when enabled, extra latency and token cost per claim (one
  more model call per document). Off by default; `evals/guardrail_bench` (below)
  quantifies whether the added coverage is worth that cost before anyone turns it
  on for a demo or in Harbor.
- `docs/security-matrix.md` and the audit/trace schema gain two new fields
  (`nemo_flagged`, `nemo_rationale`) but no new scope, token, or tier rule — NeMo
  never touches governance directly.

## Related work: guardrail benchmark, and what it actually found

To make "is the second opinion worth it" a measured claim rather than an assertion,
`evals/guardrail_bench/` scores the marker list, NeMo alone, and the OR-combination
against the existing document corpus (`data/synthetic/documents/`): 5 poisoned
samples (POISON-02..05, S06) as positives, the clean S01–S05/S09/S10 samples as
negatives. Full detail and the live-generated report: `evals/guardrail_bench/README.md`
and `evals/guardrail_bench/report.md`.

Run live against `nvidia/nemotron-3.5-content-safety` (the model this ADR wires in),
the result was not the hoped-for "NeMo catches what the marker list misses": on this
corpus, NeMo matched the marker list's recall (5/5 positives caught) but added 3 false
positives on ordinary clinical text (a pneumonia discharge summary, a dengue-adjacent
one, a plain hospital bill) — net precision 0.62 against the marker list's 1.00, no
recall gain. Reading the false positives' rationale shows why:
`nemotron-3.5-content-safety` is NVIDIA's general-purpose **content-safety** model
(toxicity/harm in conversational content), not a prompt-injection/jailbreak detector,
and it appears to key on medical-severity vocabulary ("fever," "breathlessness,"
"oxygen support") as "unsafe" — the ordinary language of a real discharge summary,
unrelated to whether the text carries a hidden instruction.

This does not undermine the ADR's core design — the OR-only, advisory-only,
fail-open, off-by-default contract exists exactly so a mismatch like this costs
nothing when disabled and degrades to "one more claim reaches a human officer" (never
a wrong auto-payout) when enabled. But it does mean the honest, current conclusion is
**recommend `NEMO_GUARDRAILS_ENABLED=false` for this specific model**: it adds real
false-positive cost with no measured recall benefit on this corpus. The architecture
is validated and ready; what remains before recommending this ON by default is
re-running `evals/guardrail_bench` against a model actually trained for prompt-
injection/jailbreak detection specifically (e.g. `meta/llama-guard-4-12b`, seen
available on the NVIDIA NIM catalogue but not yet benchmarked here) rather than
general content safety — `NEMO_RAIL_MODEL_ID` in `agents/nemo_guardrail.py` makes
swapping the model a config change, not a code change.
