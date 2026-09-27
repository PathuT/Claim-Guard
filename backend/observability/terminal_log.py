"""The backend's own story, in the terminal running `npm run dev`.

Every event the Live Run page shows (observability/live_events.py) is also
printed here as one colour-coded line, so the terminal can be shown next to
the browser in a demo and both tell the same story from the real process:

    14:02:11 a3f9c2d1 AGENT      · Intake agent reading the documents
    14:02:14 a3f9c2d1 TOKEN      ✓ Token service minted a scoped JWT for fraud — scope=…

The 8-hex prefix is the OpenTelemetry trace id, the same one Phoenix shows.
Text is the already-redacted event text; tokens appear only as their jti.

Also quiets uvicorn's access log for the console's polling requests
(health, Harbor progress, compliance summary), which would otherwise bury
the story under a GET line every few seconds.

CLAIMGUARD_TERMINAL_LOG=0 turns the event lines off; NO_COLOR drops colour.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time

_ENABLED = os.environ.get("CLAIMGUARD_TERMINAL_LOG", "1") != "0"
_COLOUR = "NO_COLOR" not in os.environ
_lock = threading.Lock()

_RESET = "\033[0m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_LAYER_COLOUR = {
    "api": "\033[94m", "document": "\033[33m", "agent": "\033[95m", "llm": "\033[91m", "rules": "\033[92m",
    "guardrail": "\033[96m", "governance": "\033[93m", "identity": "\033[36m", "token": "\033[36m",
    "gateway": "\033[96m", "database": "\033[34m", "audit": "\033[37m", "state": "\033[93m",
    "payment": "\033[92m", "evals": "\033[33m", "step": "\033[97m",
}
_LEVEL = {"success": ("✓", "\033[92m"), "deny": ("✗", "\033[91m"), "error": ("✗", "\033[91m"), "warn": ("!", "\033[93m")}

try:  # ₹ and ✓ must never crash a request on a Windows code-page console.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, ValueError):
    pass


def _active() -> bool:
    return _ENABLED and "PYTEST_CURRENT_TEST" not in os.environ


def _paint(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if _COLOUR else text


def _write(line: str) -> None:
    with _lock:
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001 - the terminal must never break a claim
            pass


def event(layer: str, title: str | None, detail: str | None, level: str, trace_id: int | None) -> None:
    if not _active():
        return
    mark, mark_colour = _LEVEL.get(level, ("·", _DIM))
    trace = f"{trace_id:032x}"[:8] if trace_id else "--------"
    text = title or ""
    if detail:
        text += _paint(_DIM, f" — {detail}")
    if len(text) > 260:
        text = text[:257] + "…"
    _write(
        f"{_paint(_DIM, time.strftime('%H:%M:%S'))} {_paint(_DIM, trace)} "
        f"{_paint(_LAYER_COLOUR.get(layer, ''), f'{layer.upper():<10}')} {_paint(mark_colour, mark)} {text}"
    )


def step(step_id: str, status: str, summary: str | None, trace_id: int | None) -> None:
    if not _active() or status not in {"active", "done", "blocked"}:
        return
    trace = f"{trace_id:032x}"[:8] if trace_id else "--------"
    if status == "active":
        line = _paint(_BOLD, f"▶ {step_id}")
    else:
        mark = "✓" if status == "done" else "■"
        line = _paint("\033[92m" if status == "done" else "\033[93m", f"{mark} {step_id}") + (f"  {summary}" if summary else "")
    _write(f"{_paint(_DIM, time.strftime('%H:%M:%S'))} {_paint(_DIM, trace)} {_paint(_LAYER_COLOUR['step'], 'STEP'.ljust(10))} {line}")


# --- quieter access log --------------------------------------------------------

_POLLING = re.compile(
    r"^(/healthz|/evals/(suite|claims|latest)|/compliance/summary|/governance/payout-freeze|/audit\b|/claims/[^/?]+/evaluation)"
)


class _PollingFilter(logging.Filter):
    """Drops uvicorn access lines for GET/OPTIONS polling requests; keeps
    every POST (claims, decisions, runs) and every error."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method, path, status = str(args[1]), str(args[2]), args[4]
        if isinstance(status, int) and status >= 400:
            return True
        if method == "OPTIONS":
            return False
        return not (method == "GET" and _POLLING.match(path))


def quiet_polling_access_logs() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _PollingFilter) for f in logger.filters):
        logger.addFilter(_PollingFilter())
