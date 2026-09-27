"""Invariant 10 (append-only, hash-chained audit log) with more than one writer.

AGT's FlightRecorder caches the chain head per instance, so two recorders on
the same file — exactly what AgentOS and the officer API are, as separate
processes — fork the chain. Two instances in one process reproduce that
deterministically. governance/flight_recorder.ChainSafeFlightRecorder must
keep the chain valid; the stock recorder is asserted to break, so this test
fails loudly if a future AGT release changes that behaviour and the wrapper
needs revisiting.
"""

from __future__ import annotations

import sqlite3

from agent_control_plane import FlightRecorder

from governance.flight_recorder import ChainSafeFlightRecorder


def _interleave(first, second) -> None:
    for i in range(5):
        for recorder in (first, second):
            trace_id = recorder.start_trace(agent_id="agent", tool_name="tool", tool_args={"i": i})
            recorder.log_success(trace_id)


def test_security_stock_recorder_forks_chain_with_two_writers(tmp_path):
    db = str(tmp_path / "audit.db")
    first, second = FlightRecorder(db_path=db, enable_batching=False), FlightRecorder(db_path=db, enable_batching=False)
    _interleave(first, second)
    assert FlightRecorder(db_path=db, enable_batching=False).verify_integrity()["valid"] is False


def test_security_chain_safe_recorder_stays_valid_with_two_writers(tmp_path):
    db = str(tmp_path / "audit.db")
    first, second = ChainSafeFlightRecorder(db_path=db, enable_batching=False), ChainSafeFlightRecorder(db_path=db, enable_batching=False)
    _interleave(first, second)
    result = FlightRecorder(db_path=db, enable_batching=False).verify_integrity()
    assert result["valid"] is True
    assert result["total_entries"] == 10


def test_security_chain_safe_recorder_still_detects_tampering(tmp_path):
    db = str(tmp_path / "audit.db")
    recorder = ChainSafeFlightRecorder(db_path=db, enable_batching=False)
    _interleave(recorder, recorder)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE audit_log SET agent_id = 'attacker' WHERE id = 3")
    conn.commit()
    conn.close()
    assert FlightRecorder(db_path=db, enable_batching=False).verify_integrity()["valid"] is False
