# ClaimGuard — local dev commands (no Docker; see ADR for the native-process decision).
# Services run as plain local processes instead of containers. Postgres is
# hosted (Supabase) via DATABASE_URL in .env, not run locally.

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
	cd backend && PATH="$$HOME/.local/bin:$$PATH" uv run python -m data_gateway.seed

eval:
	cd evals/harbor && uv run harbor run  # added in M7

compliance-report:
	cd backend && uv run python -m api.compliance_report  # added in M9
