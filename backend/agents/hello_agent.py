"""M0 skeleton check: one Agno agent call, traced into Phoenix.

Not one of the six ClaimGuard agents (supervisor/intake/medical_reviewer/
coverage/fraud/payout) — those start in M4. This just proves the plumbing:
Agno -> OpenInference -> Phoenix collector works end to end before any
security or business logic is layered on.

Usage:
    uv run phoenix serve                  # in one terminal
    uv run python -m agents.hello_agent   # in another
                                           # (run as a module, not a script path,
                                           # so sibling packages like `observability` resolve)

Reads MODEL_PROVIDER from the environment to pick which Agno model class to
use (default: groq). Agno is model-agnostic (docs/CLAUDE.md); pick whichever
provider key you've set in .env.
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from observability.tracing import setup_tracing

# .env lives at the repo root (one .env for all services), not in backend/.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_PROVIDER_KEY_ENV = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def check_phoenix_reachable(endpoint: str) -> bool:
    """Fail fast with one clear message instead of a 15s retry-storm of
    connection-refused warnings from the OTel exporter."""
    try:
        urllib.request.urlopen(endpoint, timeout=2)
        return True
    except (urllib.error.URLError, OSError):
        return False


def build_model():
    provider = os.environ.get("MODEL_PROVIDER", "groq").lower()

    if provider not in _PROVIDER_KEY_ENV:
        raise SystemExit(
            f"Unknown MODEL_PROVIDER: {provider!r} (use groq|gemini|anthropic)"
        )

    key_env = _PROVIDER_KEY_ENV[provider]
    if not os.environ.get(key_env):
        raise SystemExit(
            f"{key_env} is not set in .env. Add it, then re-run "
            f"(or set MODEL_PROVIDER to a provider you do have a key for)."
        )

    if provider == "groq":
        from agno.models.groq import Groq

        return Groq(id=os.environ.get("MODEL_ID", "openai/gpt-oss-120b"))

    if provider == "gemini":
        from agno.models.google import Gemini

        return Gemini(id=os.environ.get("MODEL_ID", "gemini-3.7-flash"))

    from agno.models.anthropic import Claude

    return Claude(id=os.environ.get("MODEL_ID", "claude-sonnet-5"))


def main() -> int:
    phoenix_endpoint = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    if not check_phoenix_reachable(phoenix_endpoint):
        print(
            f"Phoenix is not reachable at {phoenix_endpoint}.\n"
            f"Start it first: cd backend && uv run phoenix serve",
            file=sys.stderr,
        )
        return 1

    model = build_model()
    setup_tracing(service_name="claimguard-hello-agent")

    from agno.agent import Agent

    agent = Agent(
        name="hello_agent",
        model=model,
        instructions="You are a smoke-test agent for the ClaimGuard skeleton. Reply in one short sentence.",
        markdown=False,
    )

    try:
        response = agent.run("Say hello and confirm you are working.")
    except Exception as exc:  # noqa: BLE001 - surface any provider error clearly, then exit non-zero
        print(f"Agent run failed: {exc}", file=sys.stderr)
        return 1

    print(response.content)
    print(f"\nTrace sent. Check Phoenix at {phoenix_endpoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
