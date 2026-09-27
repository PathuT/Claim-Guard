"""Shared test setup.

Every test gets its own empty governance-controls file (ADR-012), so the suite
never reads the real payout kill switch. Without this, freezing automated
payouts on the Compliance page would make the older payout tests fail.
Tests that need a specific freeze state still set GOVERNANCE_CONTROLS_PATH
themselves; monkeypatch applies their value on top of this one.
"""

import pytest

from governance.controls import CONTROLS_PATH_ENV


@pytest.fixture(autouse=True)
def isolated_governance_controls(tmp_path, monkeypatch):
    monkeypatch.setenv(CONTROLS_PATH_ENV, str(tmp_path / "governance_controls.json"))
