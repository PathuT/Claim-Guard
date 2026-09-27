"""Harbor from the console: the S01-S10 scoreboard, running the suite (or one
scenario) from the Live Run page, and the history of per-claim checks.

GET  /evals/suite       every scenario's LATEST Harbor result across all
                        runs in evals/harbor/jobs/, so re-running one
                        scenario updates its row instead of replacing the
                        board; plus the run in progress, if any, with each
                        of its scenarios marked queued / running / done.
POST /evals/suite/run   start evals/harbor/run_evals.py in the background
                        (all scenarios, or the ones listed). One run at a
                        time: every scenario drives the same stack and LLM
                        key.
GET  /evals/claims      the per-claim checks Live Run starts after every
                        claim (api/claim_evaluation.py), newest first.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import tomllib
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.claim_evaluation import CLAIM_JOBS, HARBOR_DIR, EvaluationCheck, _harbor_python

router = APIRouter()

JOBS_DIR = HARBOR_DIR / "jobs"
TASKS_DIR = HARBOR_DIR / "tasks"
SUITE_TIMEOUT_S = 30 * 60


class SuiteRow(BaseModel):
    scenario: str
    description: str | None = None
    verifies: list[str] = []
    uses_ai: bool = True
    state: str = "never_run"  # never_run | queued | running | done
    outcome: float | None = None
    governance: float | None = None
    duration_s: float | None = None
    ran_at: str | None = None
    job: str | None = None
    error: str | None = None
    failures: list[str] = []


class SuiteRun(BaseModel):
    scenarios: list[str]
    started_at: float
    finished: bool = False
    exit_code: int | None = None


class Suite(BaseModel):
    rows: list[SuiteRow]
    outcome_pass_rate: float | None = None
    governance_pass_rate: float | None = None
    scored: int = 0
    last_run_at: str | None = None
    run: SuiteRun | None = None


class SuiteRunRequest(BaseModel):
    scenarios: list[str] = []


class ClaimCheckSummary(BaseModel):
    claim_id: str
    job: str
    ran_at: str | None = None
    outcome: float | None = None
    governance: float | None = None
    expectation_source: str | None = None
    checks: list[EvaluationCheck] = []
    error: str | None = None


_run: SuiteRun | None = None
_run_lock = threading.Lock()


def _scenarios() -> dict[str, dict]:
    """task id -> task.toml [metadata], for every S01-S10 task folder."""
    out: dict[str, dict] = {}
    for toml_path in sorted(TASKS_DIR.glob("*/task.toml")):
        out[toml_path.parent.name] = tomllib.loads(toml_path.read_text(encoding="utf-8")).get("metadata", {})
    return out


def _verifies(meta: dict) -> list[str]:
    """What the verifier checks for this scenario, in plain words."""
    if meta.get("task_type") == "governance_probe":
        return [f"attack refused with {meta.get('expected_reason_code')}"]
    items = [f"ends as {meta.get('expected_final_state')}"]
    if meta.get("expected_payable_amount") is not None:
        items.append(f"payable ₹{meta['expected_payable_amount']:,}")
    items += [f"fraud flag {t}" for t in meta.get("expected_fraud_flag_types", [])]
    items += [f"{rule} in the audit trail" for rule in meta.get("expected_deny_rule_ids", [])]
    items.append(f"≥ {meta.get('expected_min_allowed_entries', 1)} governed decisions")
    return items


def _failures(trial_dir: Path) -> list[str]:
    log = trial_dir / "trial.log"
    if not log.exists():
        return []
    lines = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if "ClaimGuardVerifier" in line and "failures" in line]
    return [line.split(": ", 1)[-1][:400] for line in lines]


def _duration(result: dict) -> float | None:
    if not (result.get("started_at") and result.get("finished_at")):
        return None
    parse = lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))  # noqa: E731
    return round((parse(result["finished_at"]) - parse(result["started_at"])).total_seconds(), 1)


def _job_dirs() -> list[Path]:
    if not JOBS_DIR.exists():
        return []
    return sorted((d for d in JOBS_DIR.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)


def _run_watch(process: subprocess.Popen, run: SuiteRun) -> None:
    try:
        run.exit_code = process.wait(timeout=SUITE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        process.kill()
        run.exit_code = -1
    run.finished = True


@router.get("/evals/suite", response_model=Suite)
def get_suite() -> Suite:
    scenarios = _scenarios()
    rows = {sid: SuiteRow(scenario=sid, description=meta.get("description"), verifies=_verifies(meta),
                          uses_ai=meta.get("task_type") != "governance_probe") for sid, meta in scenarios.items()}

    # Latest scored trial per scenario, newest job first.
    last_run_at: str | None = None
    for job_dir in _job_dirs():
        for trial_dir in (d for d in job_dir.iterdir() if d.is_dir()):
            scenario = trial_dir.name.split("__")[0]
            row = rows.get(scenario)
            result_path = trial_dir / "result.json"
            if row is None or row.state == "done" or not result_path.exists():
                continue
            result = json.loads(result_path.read_text(encoding="utf-8"))
            rewards = (result.get("verifier_result") or {}).get("rewards") or {}
            exception = result.get("exception_info")
            row.state, row.job = "done", job_dir.name
            row.outcome, row.governance = rewards.get("outcome"), rewards.get("governance")
            row.duration_s, row.ran_at = _duration(result), result.get("started_at")
            row.error = (exception or {}).get("exception_message") if exception else None
            row.failures = _failures(trial_dir)
            if row.ran_at and (last_run_at is None or row.ran_at > last_run_at):
                last_run_at = row.ran_at

    # The run in progress: its scenarios are queued until Harbor opens a
    # trial folder for them, running until that trial has a result.
    run = _run
    if run is not None and not run.finished:
        started = datetime.fromtimestamp(run.started_at)
        active = [d for d in _job_dirs() if datetime.fromtimestamp(d.stat().st_ctime) >= started.replace(microsecond=0)]
        in_job = {}
        for job_dir in active:
            for trial_dir in (d for d in job_dir.iterdir() if d.is_dir()):
                in_job[trial_dir.name.split("__")[0]] = (trial_dir / "result.json").exists()
        for scenario in run.scenarios:
            row = rows.get(scenario)
            if row is None:
                continue
            if scenario not in in_job:
                row.state = "queued"
            elif not in_job[scenario]:
                row.state = "running"

    scored = [r for r in rows.values() if r.state == "done"]
    return Suite(
        rows=list(rows.values()),
        outcome_pass_rate=(sum(r.outcome == 1.0 for r in scored) / len(scored)) if scored else None,
        governance_pass_rate=(sum(r.governance == 1.0 for r in scored) / len(scored)) if scored else None,
        scored=len(scored), last_run_at=last_run_at, run=run,
    )


@router.post("/evals/suite/run", response_model=SuiteRun, status_code=202)
def run_suite(req: SuiteRunRequest | None = None) -> SuiteRun:
    global _run
    known = _scenarios()
    requested = [s for s in (req.scenarios if req else []) if s]
    unknown = [s for s in requested if s not in known]
    if unknown:
        raise HTTPException(status_code=400, detail={"reason_code": "EVAL-UNKNOWN-SCENARIO", "message": f"unknown scenario(s): {unknown}"})
    python = _harbor_python()
    with _run_lock:
        if _run is not None and not _run.finished:
            raise HTTPException(status_code=409, detail={"reason_code": "EVAL-RUN-IN-PROGRESS", "message": "a Harbor run is already in progress"})
        scenarios = requested or sorted(known)
        _run = SuiteRun(scenarios=scenarios, started_at=time.time())
        process = subprocess.Popen(  # noqa: S603 - fixed interpreter and script; scenario ids validated above
            [str(python), "run_evals.py", *requested],
            cwd=HARBOR_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        threading.Thread(target=_run_watch, args=(process, _run), daemon=True, name="harbor-suite").start()
        return _run


@router.get("/evals/claims", response_model=list[ClaimCheckSummary])
def list_claim_checks(limit: int = 15) -> list[ClaimCheckSummary]:
    if not CLAIM_JOBS.exists():
        return []
    out: list[ClaimCheckSummary] = []
    for job_dir in sorted((d for d in CLAIM_JOBS.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True):
        trials = [d for d in job_dir.iterdir() if d.is_dir() and (d / "result.json").exists()]
        if not trials:
            continue
        result = json.loads((trials[0] / "result.json").read_text(encoding="utf-8"))
        rewards = (result.get("verifier_result") or {}).get("rewards") or {}
        checks_path = trials[0] / "verifier" / "checks.json"
        checks = json.loads(checks_path.read_text(encoding="utf-8")) if checks_path.exists() else {}
        exception = result.get("exception_info")
        out.append(ClaimCheckSummary(
            claim_id=job_dir.name.split("__")[0], job=job_dir.name, ran_at=result.get("started_at"),
            outcome=rewards.get("outcome"), governance=rewards.get("governance"),
            expectation_source=checks.get("expectation_source"),
            checks=[EvaluationCheck(**c) for c in checks.get("checks", [])],
            error=(exception or {}).get("exception_message") if exception and not rewards else None,
        ))
        if len(out) >= limit:
            break
    return out
