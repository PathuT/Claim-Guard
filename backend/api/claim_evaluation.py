"""Per-claim Harbor check, started by the Live Run page after every claim.

POST /claims/{claim_id}/evaluation starts evals/harbor/run_claim_eval.py in
the background: a one-task Harbor job, using the same adapter, verifier and
no-Docker environment as the S01-S10 suite, that scores THIS claim on
outcome and governance evidence. GET returns its progress and result.

The check is read-only (the Harbor adapter only GETs the claim), so it
spends no LLM tokens and can run straight after a live claim without
competing for the rate limit. Its results go to evals/harbor/claim_jobs/,
never jobs/, so the S01-S10 scoreboard (/evals/latest) is untouched.

What Harbor expects of the claim depends on where it came from:
- a sample pack -> that pack's expected outcome (PACK_EXPECTATIONS);
- a seeded S01-S10 claim (Live Run's replay) -> that scenario's task.toml;
- the presenter's own PDFs -> only the claim-wide invariants, since nobody
  knows the right answer in advance.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import tomllib
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data_gateway.db import get_session
from data_gateway.models import Claim

router = APIRouter()

HARBOR_DIR = Path(__file__).resolve().parents[2] / "evals" / "harbor"
CLAIM_JOBS = HARBOR_DIR / "claim_jobs"
TIMEOUT_S = 240
ASSESSED_STATES = {"paid", "pending_human", "needs_resubmission", "approved", "approved_partial", "rejected", "auto_approved"}

# Expected outcomes of the Live Run sample packs (api/story_support.py).
PACK_EXPECTATIONS: dict[str, dict] = {
    "jyoti-dengue": {"expected_final_state": "paid", "expected_payable_amount": 37_300},
    "priya-pneumonia": {"expected_final_state": "pending_human"},
    "rahul-poisoned": {"expected_final_state": "pending_human", "expected_flags": ["prompt_injection_suspected"]},
}


class EvaluationRequest(BaseModel):
    pack_id: str | None = None


class EvaluationCheck(BaseModel):
    group: str
    id: str
    label: str
    passed: bool
    detail: str


class ClaimEvaluation(BaseModel):
    claim_id: str
    status: str  # none | running | done | error
    job: str | None = None
    expectation_source: str | None = None
    started_at: float | None = None
    duration_s: float | None = None
    outcome: float | None = None
    governance: float | None = None
    checks: list[EvaluationCheck] = []
    error: str | None = None


_runs: dict[str, ClaimEvaluation] = {}
_lock = threading.Lock()


def _harbor_python() -> Path:
    for candidate in (HARBOR_DIR / ".venv" / "Scripts" / "python.exe", HARBOR_DIR / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    raise HTTPException(status_code=503, detail={
        "reason_code": "HARBOR-NOT-INSTALLED",
        "message": "Harbor's environment is not installed — run `cd evals/harbor && uv sync` once.",
    })


def _expectation(claim_id: str, pack_id: str | None) -> dict:
    if pack_id in PACK_EXPECTATIONS:
        return {"expectation_source": f"sample pack {pack_id}", **PACK_EXPECTATIONS[pack_id]}
    for task_toml in sorted((HARBOR_DIR / "tasks").glob("*/task.toml")):
        metadata = tomllib.loads(task_toml.read_text(encoding="utf-8")).get("metadata", {})
        if metadata.get("claim_id") == claim_id:
            keys = ("expected_final_state", "expected_payable_amount", "expected_fraud_flag_types", "expected_deny_rule_ids")
            return {"expectation_source": f"Harbor task {metadata.get('scenario_id')}", **{k: metadata[k] for k in keys if metadata.get(k) is not None}}
    return {"expectation_source": "claim-wide invariants only (your own documents)"}


def _read_job(claim_id: str, job_dir: Path, run: ClaimEvaluation) -> ClaimEvaluation:
    """Fills `run` from Harbor's own output for the job's single trial."""
    trials = [d for d in job_dir.iterdir() if d.is_dir() and (d / "result.json").exists()] if job_dir.exists() else []
    if not trials:
        run.status, run.error = "error", run.error or "Harbor finished without writing a trial result"
        return run
    trial = trials[0]
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    exception = result.get("exception_info")
    run.outcome, run.governance = rewards.get("outcome"), rewards.get("governance")
    checks_path = trial / "verifier" / "checks.json"
    if checks_path.exists():
        checks = json.loads(checks_path.read_text(encoding="utf-8"))
        run.checks = [EvaluationCheck(**c) for c in checks.get("checks", [])]
        run.expectation_source = checks.get("expectation_source", run.expectation_source)
    if exception and run.outcome is None:
        run.status, run.error = "error", (exception or {}).get("exception_message") or "Harbor trial raised an exception"
    else:
        run.status = "done"
    return run


def _latest_job_dir(claim_id: str) -> Path | None:
    if not CLAIM_JOBS.exists():
        return None
    jobs = sorted(CLAIM_JOBS.glob(f"{claim_id}__*"), key=lambda d: d.name)
    return jobs[-1] if jobs else None


def _watch(claim_id: str, process: subprocess.Popen, run: ClaimEvaluation) -> None:
    try:
        stdout, _ = process.communicate(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        run.status, run.error = "error", f"Harbor did not finish within {TIMEOUT_S} s"
        return
    finally:
        run.duration_s = round(time.time() - (run.started_at or time.time()), 1)
    job_dir: Path | None = None
    for line in reversed((stdout or "").splitlines()):
        try:
            job_dir = Path(json.loads(line)["job_dir"])
            break
        except (ValueError, KeyError, TypeError):
            continue
    job_dir = job_dir or _latest_job_dir(claim_id)
    if job_dir is None:
        run.status, run.error = "error", f"Harbor exited with code {process.returncode} and no job folder"
        return
    run.job = job_dir.name
    _read_job(claim_id, job_dir, run)


@router.post("/claims/{claim_id}/evaluation", response_model=ClaimEvaluation, status_code=202)
def start_claim_evaluation(claim_id: str, req: EvaluationRequest | None = None) -> ClaimEvaluation:
    db = get_session()
    try:
        claim = db.get(Claim, claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail={"reason_code": "AGENTOS-NO-SUCH-CLAIM", "message": f"claim {claim_id!r} does not exist"})
        if claim.status not in ASSESSED_STATES:
            raise HTTPException(status_code=409, detail={"reason_code": "EVAL-NOT-ASSESSED", "message": f"claim is still {claim.status!r}; run it first"})
    finally:
        db.close()

    python = _harbor_python()
    expectation = _expectation(claim_id, req.pack_id if req else None)
    with _lock:
        current = _runs.get(claim_id)
        if current and current.status == "running":
            return current
        run = ClaimEvaluation(claim_id=claim_id, status="running", started_at=time.time(), expectation_source=expectation["expectation_source"])
        _runs[claim_id] = run
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter and script; claim_id validated by run_claim_eval.py
        [str(python), "run_claim_eval.py", claim_id, "--expect", json.dumps(expectation)],
        cwd=HARBOR_DIR, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    threading.Thread(target=_watch, args=(claim_id, process, run), daemon=True, name=f"harbor-{claim_id}").start()
    return run


@router.get("/claims/{claim_id}/evaluation", response_model=ClaimEvaluation)
def get_claim_evaluation(claim_id: str) -> ClaimEvaluation:
    run = _runs.get(claim_id)
    if run is not None:
        return run
    # Not started by this process (e.g. AgentOS restarted): read the latest
    # finished job from disk, if there is one.
    job_dir = _latest_job_dir(claim_id)
    if job_dir is None:
        return ClaimEvaluation(claim_id=claim_id, status="none")
    return _read_job(claim_id, job_dir, ClaimEvaluation(claim_id=claim_id, status="done", job=job_dir.name))

