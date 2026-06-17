"""Tests for migration 0024 — Alpaca 1d OHLCV once-daily cadence.

Verifies:
1. Revision chain (0024 → 0023).
2. Upgrade sets the daily interval to 86_400 s (once daily); downgrade restores
   the prior 6h (21_600 s) cadence.
3. Idempotency: the UPDATE is scoped by ``base_interval_sec`` so a re-run matches
   no rows (upgrade only touches rows still at the prior interval, and vice versa).
4. The 1m timeframe is never targeted (only timeframe = '1d').
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_VERSIONS_DIR = Path(__file__).resolve().parents[3] / "alembic" / "versions"


class _FakeBind:
    """Captures the (sql_text, params) of every ``execute`` for assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return None


def _load_migration(filename: str, fake_bind: _FakeBind):
    """Load a migration module with ``alembic.op.get_bind`` stubbed to *fake_bind*."""
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"_migration_{filename}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    alembic_stub = type(sys)("alembic")
    op_stub = type(sys)("alembic.op")
    op_stub.get_bind = lambda: fake_bind  # type: ignore[attr-defined]
    alembic_stub.op = op_stub  # type: ignore[attr-defined]
    sys.modules["alembic"] = alembic_stub
    sys.modules["alembic.op"] = op_stub
    spec.loader.exec_module(mod)
    return mod


class TestMigration0024:
    _FILE = "0024_alpaca_daily_once_daily_cadence.py"

    def test_revision_chain(self) -> None:
        mod = _load_migration(self._FILE, _FakeBind())
        assert mod.revision == "0024"
        assert mod.down_revision == "0023"

    def test_constants(self) -> None:
        mod = _load_migration(self._FILE, _FakeBind())
        assert mod._DAILY_INTERVAL_SEC == 86400  # once daily
        assert mod._PRIOR_INTERVAL_SEC == 21600  # prior 6h cadence

    def test_upgrade_sets_once_daily_and_is_idempotent(self) -> None:
        fake = _FakeBind()
        mod = _load_migration(self._FILE, fake)
        mod.upgrade()
        assert len(fake.calls) == 1
        sql, params = fake.calls[0]
        # Targets only alpaca/ohlcv/1d rows still at the prior interval.
        assert "provider = 'alpaca'" in sql
        assert "timeframe = '1d'" in sql
        assert "timeframe = '1m'" not in sql  # 1m cadence untouched
        assert "base_interval_sec = :prior" in sql  # idempotency guard
        assert params == {"target": 86400, "prior": 21600}

    def test_downgrade_restores_prior_cadence(self) -> None:
        fake = _FakeBind()
        mod = _load_migration(self._FILE, fake)
        mod.downgrade()
        assert len(fake.calls) == 1
        _sql, params = fake.calls[0]
        # Restore swaps target/prior so it only touches rows at once-daily.
        assert params == {"target": 21600, "prior": 86400}
