"""One retry policy for every agent's typed output.

Found by the Harbor suite (S03): the model occasionally emits invalid JSON
for an output schema — e.g. `"confidence": 0. nine` — Groq rejects it
(`json_validate_failed`, HTTP 400, which neither the SDK nor Agno retries),
and the run's content comes back as the error body instead of the schema.
The workflow then correctly failed closed, but a claim that would have been
fine a second later ended as a 500.

`run_structured` re-asks the same agent, up to MAX_ATTEMPTS in total, until
its content is a valid instance of the schema. Each retry is a live event
(UI and terminal). After the last attempt it raises, so the workflow still
fails closed. Safe to repeat: these agent runs are pure model calls with no
tools and no side effects — every governed data access happens outside them.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from observability.live_events import emit

MAX_ATTEMPTS = 3
T = TypeVar("T", bound=BaseModel)


def _coerce(content: Any, schema: type[T]) -> T:
    if isinstance(content, schema):
        return content
    if isinstance(content, str):
        return schema.model_validate_json(content)
    if isinstance(content, dict):
        return schema.model_validate(content)
    raise ValueError(f"unexpected {type(content).__name__} instead of {schema.__name__}")


def run_structured(agent: Any, message: str, schema: type[T], who: str) -> T:
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _coerce(agent.run(message).content, schema)
        except (ValidationError, ValueError) as exc:
            last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
        if attempt < MAX_ATTEMPTS:
            emit(
                "agent", f"{who} returned malformed output — asking again ({attempt}/{MAX_ATTEMPTS - 1})",
                f"not a valid {schema.__name__}: {last_error}", level="warn",
            )
    raise ValueError(f"{who} did not return a valid {schema.__name__} after {MAX_ATTEMPTS} attempts: {last_error}")
