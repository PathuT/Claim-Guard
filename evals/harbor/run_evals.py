"""Cross-platform entrypoint for the ClaimGuard Harbor suite — no Docker.

    uv run python run_evals.py            # all 10 scenarios (S01-S10)
    uv run python run_evals.py S01 S06    # just these

Equivalent to the `harbor run ... --env environment_backend.local_host:
LocalHostEnvironment` command in README.md, but works the same from macOS/
Linux shells and from Windows cmd/PowerShell, where inline `VAR=value cmd`
syntax doesn't exist. It sets two things for the harbor process:

- PYTHONPATH=<this dir>, so harbor can import adapter/ and
  environment_backend/ by module path;
- PYTHONUTF8=1, because harbor writes each trial's result.json with the
  platform's default text encoding — cp1252 on Windows, which cannot encode
  the ₹ sign in claim explanations and crashed the first live run on
  Windows at the very last step (writing the result).

Needs the real dev stack already running (`npm run dev` from the repo root).
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTOS_HEALTH = "http://localhost:8000/healthz"


def main() -> int:
    try:
        urllib.request.urlopen(AGENTOS_HEALTH, timeout=3)  # noqa: S310 - fixed localhost URL
    except OSError:
        print(f"AgentOS is not reachable at {AGENTOS_HEALTH} — start the stack first (`npm run dev` from the repo root).")
        return 1

    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join(filter(None, [str(HERE), os.environ.get("PYTHONPATH")]))}
    command = [
        sys.executable, "-m", "harbor.cli.main", "run",
        "--path", "tasks",
        "--agent", "adapter.adapter:ClaimGuardAgent",
        "--verifier", "adapter.verifier:ClaimGuardVerifier",
        "--env", "environment_backend.local_host:LocalHostEnvironment",
        # One scenario at a time: every task drives the SAME local stack and
        # the same rate-limited LLM key (Groq on-demand: 8,000 tokens/min,
        # ~6,600 per claim). Harbor's default parallelism made 5/10 trials
        # fail with 429-induced 500s on the first full run.
        "--n-concurrent", "1",
    ]
    for scenario in sys.argv[1:]:
        command += ["--include-task-name", scenario]
    return subprocess.call(command, cwd=HERE, env=env)


if __name__ == "__main__":
    sys.exit(main())
