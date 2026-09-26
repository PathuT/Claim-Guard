# `main` (Harbor's reserved agent-container name) does almost no real work
# for this task: the "agent" being evaluated is ClaimGuard's own AgentOS
# API, running in the `backend` sidecar (see docker-compose.yaml) — the
# real intake/medical_reviewer/coverage/fraud/payout agents run there, not
# inside this sandbox. evals/harbor/adapter/adapter.py (BaseAgent.run())
# calls that sidecar via environment.exec() (a command run INSIDE this
# container, per Harbor's own environment.exec() contract), addressing it
# by its Compose service name (`http://backend:8000`) since both share one
# Docker network. curl is the only thing this container needs beyond
# staying up for Harbor's build -> start -> agent.run() -> stop lifecycle.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
CMD ["sleep", "infinity"]
