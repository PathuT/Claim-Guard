"""Shared FlightRecorder instance for the governance adapter.

One process-wide recorder, backed by a local SQLite file (AGT's own storage
choice — docs/CLAUDE.md invariant 10 only requires append-only + hash-chained,
which FlightRecorder already provides; see M3 notes on why this isn't mirrored
into Postgres yet). Path is configurable via FLIGHT_RECORDER_DB_PATH so tests
can point it at a throwaway file instead of the real audit trail.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_control_plane import FlightRecorder
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_recorder: FlightRecorder | None = None


def get_recorder() -> FlightRecorder:
    global _recorder
    if _recorder is None:
        db_path = os.environ.get("FLIGHT_RECORDER_DB_PATH", "flight_recorder.db")
        _recorder = FlightRecorder(db_path=db_path, enable_batching=False)
    return _recorder


def reset_recorder_for_tests(db_path: str) -> FlightRecorder:
    """Test-only: force a fresh recorder against a throwaway path, so
    tests never touch the real flight_recorder.db or leak state between
    each other via the module-level singleton."""
    global _recorder
    if _recorder is not None:
        _recorder.close()
    _recorder = FlightRecorder(db_path=db_path, enable_batching=False)
    return _recorder
