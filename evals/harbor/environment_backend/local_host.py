"""Custom Harbor environment (docs/adr/006's "Environment isolation:
revisited" section): runs the agent adapter's commands directly on this
host, with NO container/VM sandbox at all — `start`/`stop` are no-ops,
`exec` is a plain `subprocess.run`, file transfer is a plain filesystem
copy. There is nothing to isolate: the adapter/verifier only ever issue
plain HTTP calls to `http://localhost:8000` (the real, already-running
AgentOS API dev process), never a filesystem or process boundary the task
needs protecting from.

Built on harbor.environments.base.BaseEnvironment (confirmed via the real
installed harbor==0.23.0 source — only 8 abstract methods: type,
_validate_definition, start, stop, upload_file, upload_dir, download_file,
download_dir, exec), the same first-class custom-environment mechanism
`--env module.path:ClassName` documents for the agent/verifier layers this
project already uses.

Explicitly chosen over dropping Harbor's own job/trial orchestration
entirely (docs/adr/006): the user asked for Harbor specifically, without
Docker — this is what satisfies both at once, rather than either dropping
Harbor (a plain pytest/script runner) or keeping Docker.

Real, accepted consequence: with no isolation, all 10 scenarios run against
the SAME database the real dev stack already has running — reseed with
`make seed` before `make eval` for a deterministic run, same discipline
ADR-006 already documents for this tradeoff.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path, PurePosixPath

from harbor.environments.base import BaseEnvironment, ExecResult


def _windows_posix_shell() -> str | None:
    """On Windows, `create_subprocess_shell` means cmd.exe — which doesn't
    understand the POSIX quoting the adapter's commands use (curl -d
    '{"claim_id": ...}') or Harbor's own setup commands (chmod -R ...).
    Every task command was written for a POSIX shell (what a container
    would have provided), so run them through Git for Windows' bash
    instead. Deliberately NOT a bare shutil.which("bash"): on Windows that
    can resolve to System32\\bash.exe, which runs inside WSL — a different
    machine as far as files and processes are concerned."""
    if os.name != "nt":
        return None
    candidates = []
    git = shutil.which("git")
    if git:
        git_root = Path(git).resolve().parent.parent  # <Git>/cmd/git.exe -> <Git>
        candidates.append(git_root / "bin" / "bash.exe")
    candidates += [Path(r"C:\Program Files\Git\bin\bash.exe"), Path(r"C:\Program Files (x86)\Git\bin\bash.exe")]
    return next((str(c) for c in candidates if c.exists()), None)


_POSIX_SHELL = _windows_posix_shell()


class LocalHostEnvironment(BaseEnvironment):
    @staticmethod
    def type() -> str:
        return "local_host"

    def _resolve_virtual_path(self, path: str) -> Path:
        """Harbor's own trial.py hardcodes container-mount-root paths
        (/logs/agent, /logs/verifier, /logs/artifacts, /logs/user-agent —
        see harbor.models.trial.paths.EnvironmentPaths) when asking any
        BaseEnvironment to upload/download its own log/artifact
        directories. On a real Docker sandbox these are separate mounted
        volumes inside the container; on bare host there is no container
        root to mount them onto, and blindly treating `/logs` as an
        absolute host path would try to create/write into the real
        machine's own filesystem root (confirmed live: an earlier version
        of this environment did exactly that and hit "Read-only file
        system: '/logs'" against the real macOS root). Instead, map each
        known virtual path onto the REAL local directory Harbor already
        created for this exact purpose (self.trial_paths.agent_dir etc. —
        real paths under the trial's own results directory, not
        container-relative at all) — anything else passes through
        unchanged (task-defined paths under /tests, /solution are simply
        never used by this project's own tasks, which have no solution/
        step scripts)."""
        known_roots: dict[str, Path] = {
            "/logs/agent": self.trial_paths.agent_dir,
            "/logs/user-agent": self.trial_paths.user_agent_dir,
            "/logs/verifier": self.trial_paths.verifier_dir,
            "/logs/artifacts": self.trial_paths.artifacts_dir,
        }
        posix_path = PurePosixPath(path)
        for virtual_root, real_root in known_roots.items():
            virtual_posix = PurePosixPath(virtual_root)
            if posix_path == virtual_posix or virtual_posix in posix_path.parents:
                return Path(real_root) / posix_path.relative_to(virtual_posix)
        return Path(path)

    def _validate_definition(self):
        """No environment/Dockerfile or docker-compose.yaml is required —
        this backend needs no environment/ definition files at all, since
        there is nothing to build or start. Each task's environment/
        directory (kept from the earlier Docker-based design) is simply
        unused here; not deleted, so `--env docker` still works as a
        fallback for anyone who reinstalls Docker later."""
        return

    async def start(self, force_build: bool) -> None:
        """Nothing to start — the adapter/verifier's HTTP calls go straight
        to the real dev-stack process the operator already started
        (`make up`/`npm run dev:agentos`, etc.), which this environment
        assumes is already running (see run_scenarios.py's own healthz
        check before this environment is ever constructed, in the plain
        script this class is an alternative to — or the equivalent check
        an operator does by hand before `harbor run --env
        environment_backend.local_host:LocalHostEnvironment`)."""
        return

    async def stop(self, delete: bool) -> None:
        """Nothing to stop — this environment started no process and owns
        no container/VM to tear down."""
        return

    async def upload_file(self, source_path: Path | str, target_path: str) -> None:
        target = self._resolve_virtual_path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source_path, target)

    async def upload_dir(self, source_dir: Path | str, target_dir: str) -> None:
        target = self._resolve_virtual_path(target_dir)
        if not Path(source_dir).exists():
            return  # nothing to copy — matches a real sandbox's own "empty dir" case
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target, dirs_exist_ok=True)

    async def download_file(self, source_path: str, target_path: Path | str) -> None:
        source = self._resolve_virtual_path(source_path)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, target)

    async def download_dir(self, source_dir: str, target_dir: Path | str) -> None:
        source = self._resolve_virtual_path(source_dir)
        if not source.exists():
            return  # nothing to copy — this project's tasks never write into /logs/agent themselves
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True)

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | int | None = None,
    ) -> ExecResult:
        """Plain subprocess exec on this host — `user` is accepted (per the
        abstract signature) but not honoured: there is no privilege
        boundary here to switch across, and every ClaimGuard task's own
        command (a curl call from adapter.py/verifier.py) never needed
        one."""
        # Harbor passes `env` as the variables to ADD for this command; a
        # container merges them onto its own environment, so do the same
        # here rather than replacing the host's (which would drop PATH).
        full_env = {**os.environ, **env} if env else None
        try:
            if _POSIX_SHELL:
                proc = await asyncio.create_subprocess_exec(
                    _POSIX_SHELL, "-c", command,
                    cwd=cwd, env=full_env,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    cwd=cwd,
                    env=full_env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
            return ExecResult(
                stdout=stdout_bytes.decode(errors="replace"),
                stderr=stderr_bytes.decode(errors="replace"),
                return_code=proc.returncode if proc.returncode is not None else -1,
            )
        except TimeoutError:
            return ExecResult(stdout=None, stderr=f"command timed out after {timeout_sec}s", return_code=-1)
