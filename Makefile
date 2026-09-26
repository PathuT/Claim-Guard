# ClaimGuard — local dev commands (no Docker; see ADR for the native-process decision).
# Services run as plain local processes instead of containers. Postgres is
# hosted (Supabase) via DATABASE_URL in .env, not run locally.

# `uv` installs to ~/.local/bin, which isn't always on PATH in every shell
# (e.g. a shell opened before the installer ran) — export it here once so
# every target below finds `uv` regardless of the invoking shell's state.
export PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: up down test test-security lint seed eval compliance-report

# Runs every ready long-running service concurrently in one terminal
# (like `concurrently` in a Node monorepo), via the root package.json.
# Ctrl+C stops all of them. AgentOS/token-service/data-gateway/payments-mock
# join this as each lands (M2-M5); today it's Phoenix + frontend only.
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
	# the custom AgentOS adapter + ClaimGuardVerifier (docs/adr/006), each in
	# its own throwaway Docker Compose sandbox (Postgres + backend sidecar).
	# GROQ_API_KEY must already be set in this shell — docker-compose.yaml's
	# `${GROQ_API_KEY}` interpolation reads it from the invoking process env,
	# never bakes it into the image or evals/harbor/docker/eval.env.
	# --n-concurrent 1: the 8 claim scenarios share two policyholders
	# (Priya/Rahul) via each task's own fresh seed, so concurrency here buys
	# nothing (every trial gets its own throwaway Postgres) but running
	# serially keeps `harbor run`'s console output readable for M7's own
	# "reports both pass rates" requirement — raise it once the Docker
	# environment itself has been confirmed reachable, if faster wall-clock
	# time is wanted over readable output.
	cd evals/harbor && uv run harbor run \
		--path tasks \
		--agent adapter.adapter:ClaimGuardAgent \
		--verifier adapter.verifier:ClaimGuardVerifier \
		--n-concurrent 1 \
		--yes

compliance-report:
	cd backend && uv run python -m api.compliance_report  # added in M9
