"""Guardrail benchmark (ADR-013): scores the marker-list scan, NeMo
Guardrails, and their OR-combination against the existing document corpus,
so "does NeMo add real coverage" is a measured number, not an assertion.

Corpus: data/synthetic/documents/*.pdf.
  - Positives (should be flagged): the 4 POISON-*_poisoned.pdf samples plus
    S06_discharge_summary_poisoned.pdf — 5 documents carrying hidden
    instruction-like text (docs/use-case.md S06).
  - Negatives (should NOT be flagged): every other PDF with extractable
    text — the clean S01-S05/S09/S10 bill and discharge-summary samples.
Labelling is by filename convention (poisoned docs are the only ones with
"poisoned" in the name), matching how these fixtures are already used by
the Harbor S06 task and test_security_guardrails.py.

Usage (from backend/, so agents.* imports resolve — same convention as
`uv run python -m agents.hello_agent`):
    cd backend && uv run python ../evals/guardrail_bench/run.py
    NEMO_GUARDRAILS_ENABLED=true uv run python ../evals/guardrail_bench/run.py

Without NEMO_GUARDRAILS_ENABLED=true, the NeMo and combined columns report
every document as unflagged (nemo_guardrail.check_injection's own disabled
short-circuit), which still produces a valid marker-list-only report — this
script never requires NeMo to be installed or configured to run at all.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS_DIR = REPO_ROOT / "data" / "synthetic" / "documents"
REPORT_PATH = Path(__file__).resolve().parent / "report.md"

sys.path.insert(0, str(REPO_ROOT / "backend"))

from agents.guardrails import scan_documents  # noqa: E402
from agents.nemo_guardrail import check_injection, nemo_enabled  # noqa: E402


@dataclass(frozen=True)
class Sample:
    filename: str
    text: str
    is_positive: bool  # ground truth: does this document actually carry hidden instructions?


def _extract_pdf_text(path: Path) -> str:
    import pypdf

    reader = pypdf.PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def load_corpus() -> list[Sample]:
    samples = []
    for path in sorted(DOCUMENTS_DIR.glob("*.pdf")):
        text = _extract_pdf_text(path)
        if not text.strip():
            continue  # a handful of seed PDFs may extract empty; not usable for this benchmark
        samples.append(Sample(filename=path.name, text=text, is_positive="poisoned" in path.name.lower()))
    return samples


@dataclass
class Verdict:
    marker_list: bool
    nemo: bool
    combined: bool  # marker_list OR nemo — same rule document_guardrail applies


def score_sample(sample: Sample) -> Verdict:
    marker_hit = bool(scan_documents({"doc": sample.text}).flagged)
    nemo_hit = check_injection(sample.text).flagged
    return Verdict(marker_list=marker_hit, nemo=nemo_hit, combined=marker_hit or nemo_hit)


@dataclass
class Metrics:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def compute_metrics(samples: list[Sample], predictions: list[bool]) -> Metrics:
    tp = sum(1 for s, p in zip(samples, predictions) if s.is_positive and p)
    fp = sum(1 for s, p in zip(samples, predictions) if not s.is_positive and p)
    fn = sum(1 for s, p in zip(samples, predictions) if s.is_positive and not p)
    tn = sum(1 for s, p in zip(samples, predictions) if not s.is_positive and not p)
    return Metrics(tp=tp, fp=fp, fn=fn, tn=tn)


def build_report(samples: list[Sample], verdicts: list[Verdict]) -> str:
    detectors = {
        "Marker list": [v.marker_list for v in verdicts],
        "NeMo": [v.nemo for v in verdicts],
        "Combined (OR)": [v.combined for v in verdicts],
    }
    n_pos = sum(1 for s in samples if s.is_positive)
    n_neg = len(samples) - n_pos

    lines = [
        "# Guardrail benchmark report",
        "",
        f"Corpus: {len(samples)} documents from `data/synthetic/documents/` "
        f"({n_pos} poisoned / positive, {n_neg} clean / negative).",
        "NeMo Guardrails: "
        + (
            "enabled."
            if nemo_enabled()
            else "DISABLED (NEMO_GUARDRAILS_ENABLED != true) — NeMo and Combined columns "
            "reflect an always-unflagged NeMo, i.e. Combined == Marker list."
        ),
        "",
        "| Detector | TP | FP | FN | TN | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, predictions in detectors.items():
        m = compute_metrics(samples, predictions)
        lines.append(f"| {name} | {m.tp} | {m.fp} | {m.fn} | {m.tn} | {m.precision:.2f} | {m.recall:.2f} | {m.f1:.2f} |")

    lines += ["", "## Per-document detail", "", "| Document | Ground truth | Marker list | NeMo | Combined |", "|---|---|---|---|---|"]
    for sample, verdict in zip(samples, verdicts):
        truth = "poisoned" if sample.is_positive else "clean"
        lines.append(
            f"| {sample.filename} | {truth} | {'flagged' if verdict.marker_list else '-'} | "
            f"{'flagged' if verdict.nemo else '-'} | {'flagged' if verdict.combined else '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    samples = load_corpus()
    if not samples:
        raise SystemExit(f"No usable PDFs found in {DOCUMENTS_DIR}")
    verdicts = [score_sample(s) for s in samples]
    report = build_report(samples, verdicts)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWritten to {REPORT_PATH}")


if __name__ == "__main__":
    main()
