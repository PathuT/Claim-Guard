# Guardrail benchmark

Scores the deterministic marker-list scan (`agents.guardrails.scan_documents`),
NeMo Guardrails (`agents.nemo_guardrail.check_injection`, ADR-013), and their
OR-combination against the existing document corpus in
`data/synthetic/documents/`: the 5 poisoned samples (POISON-02..05, S06) as
positives, the clean S01-S05/S09/S10 samples as negatives.

This turns "does the second opinion actually help" into a measured
precision/recall/F1 comparison instead of an assertion — see ADR-013's
"Related work" section.

## Run it

```bash
cd backend
uv run python ../evals/guardrail_bench/run.py                              # marker list only
NEMO_GUARDRAILS_ENABLED=true uv run python ../evals/guardrail_bench/run.py  # + NeMo (needs uv sync --extra nemo)
```

Writes `report.md` next to this file and prints it to stdout.

## Reading the result

- **Marker list** alone already scores 1.00/1.00/1.00 on this corpus, because
  it was written against these exact fixtures — that is expected, not
  evidence NeMo is unnecessary. The real question this benchmark exists to
  answer is what happens on a **held-out** attack: a phrasing that isn't one
  of the fixed marker strings.
- Add a new poisoned PDF with a novel phrasing (no literal marker-list match)
  to `data/synthetic/documents/` — named with "poisoned" in the filename so
  the loader labels it a positive — and re-run. If the marker list scores a
  false negative there but NeMo (or the combination) catches it, that is the
  concrete case ADR-013's defence-in-depth argument rests on.
- **NeMo is disabled by default.** With `NEMO_GUARDRAILS_ENABLED` unset, the
  report still runs (marker-list-only), rather than failing, so this script
  never requires an NVIDIA API key to run.

### A real finding from running this: nemotron-3.5-content-safety is a
### content-safety classifier, not an injection detector

Running this benchmark live (`NEMO_GUARDRAILS_ENABLED=true`) against the
full corpus surfaced a genuine mismatch, not just a number:

| Detector | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| Marker list | 5 | 0 | 0 | 14 | 1.00 | 1.00 | 1.00 |
| NeMo (nemotron-3.5-content-safety) | 5 | 3 | 0 | 11 | 0.62 | 1.00 | 0.77 |
| Combined (OR) | 5 | 3 | 0 | 11 | 0.62 | 1.00 | 0.77 |

NeMo matched the marker list's recall (it flagged every poisoned document)
but added 3 false positives — on *ordinary clinical text*: a pneumonia
discharge summary, a dengue-adjacent one, and a plain hospital bill. Reading
`nemo_rationale` on those three shows why: `nemotron-3.5-content-safety` is
NVIDIA's general-purpose content-safety model (built to catch toxic/harmful/
unsafe conversational content), not a prompt-injection or jailbreak
detector. It appears to key on illness/medical severity language ("fever,"
"breathlessness," "oxygen support") as "unsafe" content, which is exactly
the ordinary vocabulary of a real discharge summary — unrelated to whether
the document carries a hidden instruction.

**What this means for ADR-013's design, not just this one model's score:**
the OR-only, advisory-only, off-by-default contract exists precisely so a
mismatch like this costs nothing by default and degrades gracefully when
turned on — a false positive here means "one more claim reaches a human
officer," never a wrong auto-payout or a blocked claim. But it also means
the honest conclusion from this benchmark is **not** "NeMo strengthens
detection" on this corpus — it is "this specific NIM model trades marker-
list-equivalent recall for a real precision cost, because it is answering a
different question than the one being asked." A model actually trained for
prompt-injection/jailbreak detection (rather than general content safety)
would need to be re-benchmarked here before being recommended over the
marker list alone.
