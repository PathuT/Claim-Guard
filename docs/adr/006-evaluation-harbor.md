# ADR-006: Harbor for scenario evaluation, including governance evidence

- **Status:** accepted (environment isolation approach decided; see below)

## Context
Unit tests prove individual controls. We also need end-to-end, reproducible evaluation of
agent behaviour, including attacks, that can run on every change.

## Decision
Use **Harbor** (PyPI `harbor`, current release 0.23.0 — the project moved from
`laude-institute/harbor` to `harbor-framework/harbor`; the old GitHub URL now redirects) with
a custom agent adapter and one task per scenario (S01–S10). Verifiers check outcome **and**
governance evidence (audit entries by rule ID, exported spans).

Confirmed against Harbor's own docs (not guessed) before deciding the environment approach:
- A Harbor task's `environment/` directory natively supports `docker-compose.yaml` for
  multi-container environments — Harbor reserves the service name `main` for the agent
  container and treats every other named service as a sidecar on the same Docker network,
  auto-merging your compose file onto its own base compose file. This is documented as
  first-class usage ("MCPs are commonly used to mock external services like databases or
  APIs and can be implemented as services in the docker-compose.yaml file"), not a hack.
- A Harbor **verifier** is not confined to the sandbox by default: the built-in
  `tests/test.sh` path *is* sandbox-confined, but a custom `BaseVerifier` subclass's
  `verify()` method "runs in the Harbor process itself... can call sandbox operations
  through `self.environment`" — i.e. it can connect to Postgres directly, query an OTLP
  backend for span attributes, or hit any host-reachable service, with no sandbox
  confinement at all. This is exactly what "Governance evidence: expected audit entries...
  and expected spans from an OTLP file export" (docs/architecture.md §12) needs, and it's a
  documented, first-class use case ("Best for: Custom orchestration or host-side checks"),
  not a workaround.

## Open question — resolved
**Environment isolation: fresh stack per task vs. shared stack with reset.**

Fresh stack per task, via Harbor's native `environment/docker-compose.yaml` support —
matching docs/architecture.md §12's own stated preference ("preferred option is a fresh
stack + seed per task run so results are reproducible").

This creates a **narrow, explicitly scoped exception** to this project's own no-Docker
decision (README: "No Docker. Every service runs as a native local process... see docs/adr/
for the reasoning if this changes"). The exception is scoped as follows and no further:

- **What stays unchanged:** the actual local dev stack this project runs day to day (token
  service, data gateway, AgentOS API, the frontend, Phoenix) continues to run exactly as
  every prior milestone built it — native `uv run uvicorn ...` processes, `npm run dev`,
  no Docker anywhere in `backend/`, `frontend/`, or the Makefile. Nothing about M0–M6's
  actual runtime changes.
- **What Docker is scoped to:** `evals/harbor/tasks/S01..S10/environment/docker-compose.yaml`
  builds a throwaway copy of that same stack (Postgres + token service + data gateway +
  AgentOS, seeded fresh) *only* for the duration of one Harbor task run, as `main`'s
  sidecar services. This exists because Harbor's own task-isolation model requires an
  `environment/` definition per task, and Docker Compose is the natively-supported,
  documented way to give it one — not because this project's own architecture changed its
  mind about Docker.
- **Why not avoid Docker entirely here too:** the alternative (run all 10 Harbor tasks
  against one already-running native-process dev stack, no isolation) was considered and
  rejected — see "Alternatives considered" below. Reusing one live stack across scenarios
  that share policyholders (Priya's S01/S02/S03/S09, Rahul's S04/S05/S06/S10) risks one
  scenario's payout or state transition silently changing another's expected input (e.g.
  S01's payout consuming sum insured that S02's PAY-006 check then sees as already spent),
  making eval results depend on run order rather than being reproducible per docs/plan.md
  M7's own "Done when."

## Alternatives considered
- **pytest end-to-end only** — works, but no standard harness, parallelism, or reporting.
- **Phoenix evals only** — good for LLM output quality, not for containerized scenario runs.
- **Shared, already-running native-process stack, no per-task isolation** — avoids Docker
  entirely, but see "Why not avoid Docker entirely here too" above: state leaking between
  scenarios that share a policyholder makes results order-dependent, contradicting
  docs/architecture.md §12's explicit reproducibility goal for this milestone specifically.
- **A different sandbox provider** (Modal, E2B, Daytona, etc.) instead of local Docker —
  Harbor supports several, but per its own docs only `docker`/`podman`/`ec2`/`islo`/`vercel`
  have *native* Compose support; everything else is either Docker-in-Docker (slower, more
  moving parts for a local-first project) or doesn't support multi-container at all. Local
  Docker is the natively-supported, simplest-to-run-locally choice among the ones that work.

## Consequences
- Scenario suite doubles as the acceptance test set and regression gate.
- Docker becomes a real, if narrowly-scoped, dependency of `make eval` specifically — anyone
  running `make eval` needs a local Docker daemon, even though nothing else in this project
  does. This is called out explicitly in the README/Makefile at the point `make eval` is
  documented, so it isn't a silent surprise contradicting the project's own "No Docker" line.
- Each task's `environment/docker-compose.yaml` re-seeds its own throwaway Postgres from the
  same generators `make seed` already uses (data/synthetic/generators/), not a hand-maintained
  duplicate fixture set — one seeding codepath, run against two different targets (the real
  Supabase-hosted dev database, or a task's disposable container).

## Implementation notes (found only by actually running `docker compose build`/`up`, not by reading Compose's spec)
- **`build.context`/`build.dockerfile` both resolve relative to `context`, not to the compose
  file's own directory**, on the real installed Docker Compose (v2.x, classic builder,
  confirmed via Colima on this machine) — the opposite of what an early draft of this ADR's
  own reasoning assumed from reading the Compose Specification's prose. `context:` is 5
  levels up from `environment/` (to the repo root); `dockerfile:` is then repo-root-relative
  (`evals/harbor/docker/backend.Dockerfile`), not relative to `environment/` itself.
- **The build context must be the repo root, not `backend/` alone.**
  `backend/data_gateway/seed.py` imports the synthetic-data generators from a sibling
  `data/synthetic/generators/` directory (via `sys.path.insert`, `parents[2]` from its own
  file) — a `backend/`-only context left that directory unreachable inside the image
  (`ModuleNotFoundError: No module named 'claims'` on first real `docker compose up`). Fixed
  by widening the context to the repo root and `COPY`ing `backend/` to `/app` and
  `data/synthetic` to `/data/synthetic` separately, mirroring backend/'s real position one
  level under the repo root so seed.py's own `parents[2]`-relative logic needs no code change.
- Each task directory also needs a placeholder `tests/test.sh` (never executed — a custom
  `--verifier` at the job level fully replaces it) purely to satisfy Harbor's own
  `TaskModel.is_valid_dir()` directory-shape check, which requires the default test path to
  exist unless a task declares its own separate verifier *environment* in `task.toml`
  (`[verifier.environment]`) — a different mechanism than the CLI's `--verifier` flag.
- `harbor run --path <dir>` treats `<dir>` as a **dataset** directory and iterates its
  *children* looking for valid task subdirectories — pass the tasks/ parent directory with
  `--include-task-name S01`, not a single task's own directory, to run just one scenario.
- `adapter.adapter`/`adapter.verifier`'s import paths need `evals/harbor/adapter/__init__.py`
  (a real package, not just a directory) and `PYTHONPATH` set to `evals/harbor` when invoking
  `harbor run` — the installed `harbor` console-script's own `sys.path[0]` is its own
  `.venv/bin/` directory, not the invoking shell's cwd, so cwd alone (which works for
  `uv run python -c ...`) is not enough here.
