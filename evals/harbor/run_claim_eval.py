"""Harbor check for ONE claim that has just been run from the Live Run page.

    uv run python run_claim_eval.py CLM-2026-123456
    uv run python run_claim_eval.py CLM-2026-123456 --expect '{"expected_final_state": "paid", ...}'

Writes a one-task Harbor dataset for that claim (live_tasks/<claim_id>/,
task_type = "live_claim") and runs it through the same adapter, verifier and
no-Docker environment as the S01-S10 suite. The adapter only READS the claim
(GET /claims/{id}); nothing is re-run, so the check spends no LLM tokens.

Results go to claim_jobs/, not jobs/, so a per-claim check never replaces
the S01-S10 scoreboard (/evals/latest reads jobs/). The backend starts this
script after every Live Run (backend/api/claim_evaluation.py) and reads the
trial's result.json and verifier/checks.json back for the console.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE_TASKS = HERE / "live_tasks"
CLAIM_JOBS = HERE / "claim_jobs"
CLAIM_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
EXPECTATION_KEYS = {
    "expectation_source", "expected_final_state", "expected_payable_amount",
    "expected_flags", "expected_fraud_flag_types", "expected_deny_rule_ids",
}


def _toml_value(value: object) -> str:
    # JSON strings, integers and arrays of strings are valid TOML values;
    # ensure_ascii keeps the file plain ASCII (\uXXXX escapes) on any platform.
    return json.dumps(value, ensure_ascii=True)


def write_task(claim_id: str, expectation: dict) -> Path:
    task_dir = LIVE_TASKS / claim_id
    if task_dir.exists():
        shutil.rmtree(task_dir)
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "tests").mkdir()

    metadata = {"task_type": "live_claim", "claim_id": claim_id, **{k: v for k, v in expectation.items() if k in EXPECTATION_KEYS and v is not None}}
    lines = ['schema_version = "1.4"', "", "[metadata]"]
    lines += [f"{key} = {_toml_value(value)}" for key, value in metadata.items()]
    lines += ["", "[agent]", "timeout_sec = 60.0", "", "[verifier]", "timeout_sec = 90.0", "", "[environment]", "build_timeout_sec = 60.0", ""]
    (task_dir / "task.toml").write_text("\n".join(lines), encoding="utf-8")

    (task_dir / "instruction.md").write_text(
        f"Check ClaimGuard claim **{claim_id}**, which has just been assessed from the Live Run page.\n\n"
        f"review_claim_id: {claim_id}\n\n"
        "Read its final state (do not submit it again). The verifier scores the outcome and the\n"
        "governance evidence in its audit trail.\n",
        encoding="utf-8",
    )
    (task_dir / "environment" / "README.md").write_text(
        "No container: this task runs on environment_backend.local_host:LocalHostEnvironment.\n", encoding="utf-8"
    )
    (task_dir / "tests" / "test.sh").write_text(
        "#!/bin/bash\n# Placeholder required by Harbor's task-shape check; the custom ClaimGuardVerifier replaces it.\nexit 0\n",
        encoding="utf-8",
    )
    return task_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("claim_id")
    parser.add_argument("--expect", default="{}", help="JSON object of expected_* fields for this claim")
    args = parser.parse_args()

    if not CLAIM_ID_RE.match(args.claim_id):
        print(json.dumps({"error": f"invalid claim id {args.claim_id!r}"}))
        return 2
    expectation = json.loads(args.expect)

    task_dir = write_task(args.claim_id, expectation)
    job_name = f"{args.claim_id}__{datetime.now().strftime('%Y-%m-%d__%H-%M-%S')}"  # noqa: DTZ005 - local folder name only
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join(filter(None, [str(HERE), os.environ.get("PYTHONPATH")]))}
    command = [
        sys.executable, "-m", "harbor.cli.main", "run",
        "--path", str(task_dir),
        "--agent", "adapter.adapter:ClaimGuardAgent",
        "--verifier", "adapter.verifier:ClaimGuardVerifier",
        "--env", "environment_backend.local_host:LocalHostEnvironment",
        "--jobs-dir", str(CLAIM_JOBS),
        "--job-name", job_name,
        "--n-concurrent", "1",
    ]
    code = subprocess.call(command, cwd=HERE, env=env)
    print(json.dumps({"job_dir": str(CLAIM_JOBS / job_name), "exit_code": code}))
    return code


if __name__ == "__main__":
    sys.exit(main())
