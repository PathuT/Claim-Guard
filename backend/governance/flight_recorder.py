"""Shared FlightRecorder instance for the governance adapter.

One process-wide recorder, backed by a local SQLite file (AGT's own storage
choice — docs/engineering-guide.md invariant 10 only requires append-only + hash-chained,
which FlightRecorder already provides; see M3 notes on why this isn't mirrored
into Postgres yet). Path is configurable via FLIGHT_RECORDER_DB_PATH so tests
can point it at a throwaway file instead of the real audit trail.

Multi-writer safety (`ChainSafeFlightRecorder`): AGT's FlightRecorder caches
the hash-chain head (`_last_hash`) in memory, read once when the recorder is
created, and computes each new entry's hash from that cache without a lock.
ClaimGuard has several processes appending to the same audit file — AgentOS
and the separate officer decision API, plus any script or test run — so a
process whose cache was stale linked its next entry to the wrong
predecessor, and verify_integrity() reported the chain broken. Found live:
the chain broke at the first entry written by a second process; the same
thing happens in normal use as soon as an officer decides a claim after
AgentOS has written anything. The fix keeps AGT's hashing and storage
untouched and only serialises the append: under one cross-process file lock
(plus a thread lock), re-read the real chain head from the database, then let
AGT compute and commit the entry (batching is off, so the INSERT is committed
before the lock is released).
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path

from agent_control_plane import FlightRecorder
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@contextmanager
def _interprocess_lock(lock_path: str):
    """Exclusive OS-level lock on a sidecar file — msvcrt on Windows, flock
    elsewhere. Blocks until acquired; released on exit even on error."""
    with open(lock_path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # retries for ~10 s internally
                    break
                except OSError:
                    continue
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ChainSafeFlightRecorder(FlightRecorder):
    """AGT FlightRecorder whose appends stay correctly chained when several
    processes (or threads) write to the same audit file. See module docstring."""

    def __init__(self, db_path: str, **kwargs) -> None:
        super().__init__(db_path=db_path, **kwargs)
        self._append_lock = threading.Lock()
        self._lock_path = f"{db_path}.lock"

    def _read_chain_head(self) -> str | None:
        cursor = self._get_connection().cursor()
        cursor.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        return row[0] if row else None

    def start_trace(self, *args, **kwargs) -> str:
        with self._append_lock, _interprocess_lock(self._lock_path):
            self._last_hash = self._read_chain_head()
            return super().start_trace(*args, **kwargs)


_recorder: FlightRecorder | None = None


def get_recorder() -> FlightRecorder:
    global _recorder
    if _recorder is None:
        db_path = os.environ.get("FLIGHT_RECORDER_DB_PATH", "flight_recorder.db")
        _recorder = ChainSafeFlightRecorder(db_path=db_path, enable_batching=False)
    return _recorder


def reset_recorder_for_tests(db_path: str) -> FlightRecorder:
    """Test-only: force a fresh recorder against a throwaway path, so
    tests never touch the real flight_recorder.db or leak state between
    each other via the module-level singleton."""
    global _recorder
    if _recorder is not None:
        _recorder.close()
    _recorder = ChainSafeFlightRecorder(db_path=db_path, enable_batching=False)
    return _recorder
