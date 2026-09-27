"""Custom Harbor agent adapter (docs/architecture.md §12, docs/adr/006):
submits a scenario's claim to the ClaimGuard AgentOS API, running as the
`backend` sidecar in each task's docker-compose.yaml environment, and waits
for a terminal or pending_human state.

Built on harbor.agents.base.BaseAgent (confirmed via harbor==0.23.0's real
source, not guessed) rather than BaseInstalledAgent: the agent loop here
doesn't run inside the sandbox at all — the real intake/medical_reviewer/
coverage/fraud/payout agents run inside the `backend` sidecar's own AgentOS
process. This adapter's whole job is: extract the claim_id from the task's
instruction text, call POST /claims, and report the result into
AgentContext.

S07/S08 (docs/use-case.md §8) are a different shape: attack attempts
against the governance layer itself, not a claim reaching a particular
state. Their instruction.md carries a `probe_endpoint:` line instead of
`claim_id:`, naming one of api/governance_selftest.py's POST endpoints —
this adapter calls that endpoint instead of /claims when present.

Reaches the backend via `environment.exec()` — a curl call executed
through whichever BaseEnvironment the job was configured with. Originally
this ran INSIDE a per-task Docker Compose sandbox's `main` container,
addressing a `backend` sidecar by its Compose service name (ADR-006's
original design). Docker was dropped from this project entirely (see
ADR-006's "Environment isolation: revisited" section) in favour of
environment_backend.local_host:LocalHostEnvironment, which runs `exec()`
directly on the host — so BACKEND_URL now points at the real, already-
running local dev-stack AgentOS process on localhost, not a Compose
sidecar. The curl-based approach itself didn't need to change at all:
this adapter has no idea which BaseEnvironment it's running under, by
design.
"""

from __future__ import annotations

import json
import re
import shlex

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

BACKEND_URL = "http://localhost:8000"
CLAIM_ID_RE = re.compile(r"^claim_id:\s*(\S+)\s*$", re.MULTILINE)
PROBE_ENDPOINT_RE = re.compile(r"^probe_endpoint:\s*(\S+)\s*$", re.MULTILINE)
# live_claim tasks (run_claim_eval.py): the claim has already been run from
# the Live Run page, so the adapter only reads its current state — running
# it again would spend LLM tokens and fail the state machine's transitions.
REVIEW_CLAIM_ID_RE = re.compile(r"^review_claim_id:\s*(\S+)\s*$", re.MULTILINE)


class ClaimGuardAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "claimguard-agentos"

    def version(self) -> str | None:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        """Nothing to install — `main` only needs curl, already baked into
        each task's environment/Dockerfile."""
        return

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        context.metadata = context.metadata or {}

        probe_match = PROBE_ENDPOINT_RE.search(instruction)
        if probe_match is not None:
            await self._run_probe(probe_match.group(1), environment, context)
            return

        review_match = REVIEW_CLAIM_ID_RE.search(instruction)
        if review_match is not None:
            await self._review_claim(review_match.group(1), environment, context)
            return

        match = CLAIM_ID_RE.search(instruction)
        if match is None:
            raise ValueError(
                f"instruction.md has no 'claim_id: <id>' or 'probe_endpoint: <path>' line for "
                f"{self.name()} to parse — every ClaimGuard task's instruction.md must include "
                "one (see tasks/S01/instruction.md or tasks/S07/instruction.md)"
            )
        claim_id = match.group(1)

        body = json.dumps({"claim_id": claim_id})
        # -sS: silent but still show errors; -f would swallow the response
        # body on a non-2xx status, which we want to see (the verifier
        # checks final_state, including needs_resubmission/pending_human,
        # not just 200 OK).
        command = (
            f"curl -sS -X POST {BACKEND_URL}/claims "
            f"-H 'Content-Type: application/json' "
            f"-d {shlex.quote(body)}"
        )
        result = await environment.exec(command, timeout_sec=280)

        context.metadata["claim_id"] = claim_id
        context.metadata["agentos_response_raw"] = result.stdout
        context.metadata["agentos_exec_return_code"] = result.return_code
        if result.stderr:
            context.metadata["agentos_exec_stderr"] = result.stderr

        if result.return_code != 0:
            raise RuntimeError(
                f"POST /claims failed (curl exit {result.return_code}) for claim_id={claim_id!r}: "
                f"stderr={result.stderr!r} stdout={result.stdout!r}"
            )

        # Parsed here (not just left as raw JSON in metadata) so a
        # malformed/unexpected response surfaces as a clear agent-side
        # error rather than a confusing verifier failure later.
        try:
            parsed = json.loads(result.stdout or "")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AgentOS response for claim_id={claim_id!r} was not valid JSON: {result.stdout!r}") from exc
        context.metadata["agentos_response"] = parsed

    async def _review_claim(self, claim_id: str, environment: BaseEnvironment, context: AgentContext) -> None:
        """live_claim tasks: record the finished claim's state (GET, never
        POST) so the trial log shows what the verifier then scores."""
        result = await environment.exec(f"curl -sS {BACKEND_URL}/claims/{claim_id}", timeout_sec=30)
        context.metadata["claim_id"] = claim_id
        context.metadata["agentos_response_raw"] = result.stdout
        context.metadata["agentos_exec_return_code"] = result.return_code
        if result.return_code != 0:
            raise RuntimeError(f"GET /claims/{claim_id} failed (curl exit {result.return_code}): stderr={result.stderr!r}")
        try:
            context.metadata["agentos_response"] = json.loads(result.stdout or "")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"AgentOS response for claim_id={claim_id!r} was not valid JSON: {result.stdout!r}") from exc

    async def _run_probe(self, probe_path: str, environment: BaseEnvironment, context: AgentContext) -> None:
        """S07/S08: calls one of api/governance_selftest.py's probe
        endpoints (e.g. /_governance/probe/scope-matrix) instead of
        /claims. S08's probe sleeps ~66s server-side (waiting out a real
        token TTL) — the 280s exec timeout below covers that comfortably."""
        command = f"curl -sS -X POST {BACKEND_URL}{probe_path}"
        result = await environment.exec(command, timeout_sec=280)

        context.metadata["probe_endpoint"] = probe_path
        context.metadata["agentos_response_raw"] = result.stdout
        context.metadata["agentos_exec_return_code"] = result.return_code
        if result.stderr:
            context.metadata["agentos_exec_stderr"] = result.stderr

        if result.return_code != 0:
            raise RuntimeError(
                f"probe {probe_path!r} failed (curl exit {result.return_code}): "
                f"stderr={result.stderr!r} stdout={result.stdout!r}"
            )

        try:
            parsed = json.loads(result.stdout or "")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"probe {probe_path!r} response was not valid JSON: {result.stdout!r}") from exc
        context.metadata["agentos_response"] = parsed
