"""Compliance kill switch: an emergency freeze on AUTOMATED payouts (GOV-004,
docs/security-matrix.md §8, ADR-012).

Why a file and not an in-memory flag: AgentOS (which runs the automated T2
payout) and the officer decision API are separate processes, and the toggle
is set through AgentOS's /governance/payout-freeze endpoint — the freeze has
to be visible to every process that can call execute_payout, the moment it
is set. A small JSON file next to flight_recorder.db (same "relative to the
backend cwd, overridable by env" convention — GOVERNANCE_CONTROLS_PATH here,
FLIGHT_RECORDER_DB_PATH there) gives that with no new infrastructure, and
it is re-read on every execute_payout governance check rather than cached,
so there is no stale window to reason about.

Writes are atomic (temp file in the same directory + os.replace), so a
reader in another process sees either the old state or the new one, never a
half-written file.

Reading FAILS CLOSED (docs/engineering-guide.md invariant 7):
  - file missing            -> not frozen (the normal first-run state; the
                               switch has simply never been touched)
  - file present but unreadable, not JSON, wrong shape, or `frozen` not a
    real boolean            -> FROZEN, with `fail_closed=True` and a reason
                               saying why. A corrupted control must stop
                               automated money movement, not silently
                               re-enable it. Recovery is an explicit,
                               governed and audited "resume" through the
                               same endpoint, which rewrites a valid file.

This module only stores state. Who may change it (compliance_officer /
set_payout_freeze, GOV-001) and the audit entry for every change are
enforced by governance/adapter.check_and_audit() in api/governance_controls.py;
what the freeze *does* is rule GOV-004 in governance/rules.py.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

CONTROLS_PATH_ENV = "GOVERNANCE_CONTROLS_PATH"
DEFAULT_CONTROLS_PATH = "governance_controls.json"

# Windows only: os.replace onto a file another process has open for reading
# at that instant raises PermissionError. Reads are a single short open(), so
# a few brief retries are enough; anything longer is a real failure and is
# raised to the caller.
_REPLACE_ATTEMPTS = 20
_REPLACE_RETRY_SECONDS = 0.05


@dataclass(frozen=True)
class PayoutFreezeState:
    frozen: bool
    reason: str | None = None
    set_by: str | None = None
    set_at: str | None = None  # ISO-8601, UTC
    # True only when `frozen` was forced because the stored state could not
    # be read/validated — never written to disk.
    fail_closed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


NOT_FROZEN = PayoutFreezeState(frozen=False)


def controls_path() -> Path:
    """Resolved at call time (not import time) so tests can point it at a
    throwaway file with monkeypatch.setenv."""
    return Path(os.environ.get(CONTROLS_PATH_ENV, DEFAULT_CONTROLS_PATH))


def _fail_closed(why: str) -> PayoutFreezeState:
    return PayoutFreezeState(
        frozen=True,
        reason=f"governance controls state unreadable ({why}) — automated payouts held until a compliance officer resets the switch",
        fail_closed=True,
    )


def read_payout_freeze() -> PayoutFreezeState:
    """The trusted store GOV-004 reads from. Never raises: every failure is
    mapped to a frozen state (see module docstring)."""
    path = controls_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return NOT_FROZEN
    except OSError as exc:
        return _fail_closed(f"{type(exc).__name__}")

    try:
        data = json.loads(raw)
    except ValueError:
        return _fail_closed("not valid JSON")
    if not isinstance(data, dict):
        return _fail_closed("not a JSON object")

    frozen = data.get("frozen")
    if not isinstance(frozen, bool):
        return _fail_closed("'frozen' is missing or not a boolean")
    reason, set_by, set_at = (data.get(key) for key in ("reason", "set_by", "set_at"))
    if any(value is not None and not isinstance(value, str) for value in (reason, set_by, set_at)):
        return _fail_closed("reason/set_by/set_at must be strings")

    return PayoutFreezeState(frozen=frozen, reason=reason, set_by=set_by, set_at=set_at)


def write_payout_freeze(*, frozen: bool, reason: str, set_by: str) -> PayoutFreezeState:
    """Atomically replace the stored state. Callers must have already passed
    check_and_audit() (compliance_officer / set_payout_freeze) — this
    function is storage only and does no authorisation of its own."""
    state = PayoutFreezeState(
        frozen=bool(frozen),
        reason=reason,
        set_by=set_by,
        set_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    payload = {key: value for key, value in state.to_dict().items() if key != "fail_closed"}

    path = controls_path()
    directory = path.parent if str(path.parent) else Path(".")
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return state


def _replace_with_retry(src: str, dst: Path) -> None:
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_RETRY_SECONDS)
