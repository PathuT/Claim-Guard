# ClaimGuard — local dev commands (no Docker; see ADR for the native-process decision).
# Services run as plain local processes instead of containers. Postgres is
# hosted (Supabase) via DATABASE_URL in .env, not run locally.

# `uv` installs to ~/.local/bin, which isn't always on PATH in every shell
# (e.g. a shell opened before the installer ran) — export it here once so
# every target below finds `uv` regardless of the invoking shell's state.
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: up down test test-security lint seed eval compliance-report

# Runs every long-running service concurrently in one terminal (like
# `concurrently` in a Node monorepo), via the root package.json: Phoenix,
# the frontend/Console, the token service, the data gateway, AgentOS, and
# the officer decision API. Ctrl+C stops all of them.
up:
	npm run dev

down:
	@echo "Ctrl+C in the 'make up' terminal stops everything (concurrently forwards SIGINT to all)."

test:
	cd backend && uv run pytest

test-security:
	cd backend && uv run pytest tests/ -k security

lint:
	cd backend && uv run ruff check . && uv run mypy .
	cd frontend && npm run lint

seed:
	cd backend && uv run python -m data_gateway.seed

eval:
	# M7: runs all 10 ClaimGuard scenarios (S01-S10, evals/harbor/tasks/) via
	# the custom AgentOS adapter + ClaimGuardVerifier (docs/adr/006). No
	# Docker: each task runs straight on the host through a custom
	# BaseEnvironment (evals/harbor/environment_backend/local_host.py, see
	# ADR-006 for why Docker was tried first and dropped). Needs the real
	# dev stack already running in another terminal (`make up`) — the
	# adapter talks to the real http://localhost:8000, not a per-task
	# sandboxed backend.
	cd evals/harbor && PYTHONPATH=$$(pwd) uv run harbor run \
		--path tasks \
		--agent adapter.adapter:ClaimGuardAgent \
		--verifier adapter.verifier:ClaimGuardVerifier \
		--env environment_backend.local_host:LocalHostEnvironment

compliance-report:
	cd backend && uv run python -m api.compliance_report  # added in M9
