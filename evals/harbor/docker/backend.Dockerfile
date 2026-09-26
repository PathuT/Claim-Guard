# Shared backend image for Harbor task environments (docs/adr/006-evaluation-harbor.md).
#
# Runs all three ClaimGuard backend services (token service, data gateway,
# AgentOS API) in ONE container via a small supervisor script, not three
# separate Compose services — the point of this sandbox is a disposable,
# isolated Postgres + backend stack per task run, not modelling production
# network topology (the real dev stack already does that, natively, no
# Docker; see docs/adr/006). Built from backend/ as the context so it can
# `uv sync` the real backend/pyproject.toml — this is the same code that
# runs in local dev, not a reimplementation for the eval.
#
# Build context: the REPO ROOT (see each task's own docker-compose.yaml:
# `context: ../../../../../backend/..`, i.e. one level above backend/) — not
# backend/ alone. backend/data_gateway/seed.py imports the synthetic-data
# generators from ../../data/synthetic/generators (a sibling of backend/,
# not under it — see that file's own sys.path.insert call), so a
# backend/-only build context left that whole directory unreachable inside
# the image; found by actually running `docker compose up` and reading the
# real ModuleNotFoundError, not by reasoning about the Dockerfile on paper.

FROM python:3.12-slim

# curl: used by the compose healthcheck below to poll AgentOS's /healthz.
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ .
COPY data/synthetic /data/synthetic

# Seed runs once, before any of the three services start (they'd otherwise
# race a not-yet-created schema) — same generators/seed.py `make seed` uses
# for the real dev database, run here against this container's own
# throwaway Postgres (DATABASE_URL/DIRECT_URL point at the `postgres`
# sidecar — see docker-compose.yaml), so there is exactly one seeding
# codepath for both targets (docs/adr/006's own stated consequence).
#
# Same three uvicorn processes local dev runs via `npm run dev` / concurrently
# (package.json) — started here by a plain shell script instead of adding a
# process-manager dependency for three long-running commands. Written inline
# (not COPY'd from evals/harbor/) since this Dockerfile's build context is
# backend/ itself, and an eval-only script has no reason to live there.
RUN printf '%s\n' \
    '#!/bin/sh' \
    'set -e' \
    'uv run python -m data_gateway.seed' \
    'uv run uvicorn auth.app:app --host 0.0.0.0 --port 8100 &' \
    'uv run uvicorn data_gateway.app:app --host 0.0.0.0 --port 8200 &' \
    'uv run uvicorn api.agentos:app --host 0.0.0.0 --port 8000 &' \
    'wait -n' \
    > /app/evals-entrypoint.sh && chmod +x /app/evals-entrypoint.sh

EXPOSE 8000 8100 8200

CMD ["/app/evals-entrypoint.sh"]
