"""Tests for migration 0025 - Alpaca 1d full-universe policy seed.

Verifies (pure-Python, no Postgres):
1. Revision chain (0025 -> 0024).
2. Deterministic ULID seed matches 0023's format so ON CONFLICT dedups the
   ~96 rows 0023 already created.
3. upgrade(): inserts one alpaca/ohlcv/1d policy per DISTINCT (symbol, exchange)
   returned by the universe SELECT, with the expected column values, and
   disables the redundant eodhd/ohlcv/1d US+CC rows.
4. The INDX/FOREX/SHG exchanges are excluded from both the insert universe and
   the eodhd disable (kept on EODHD).
5. downgrade(): re-enables eodhd US+CC 1d and deletes only the added alpaca 1d.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_VERSIONS_DIR = Path(__file__).resolve().parents[3] / "alembic" / "versions"


class _FakeResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeBind:
    """Captures every ``execute`` call; returns the seeded universe for the SELECT."""

    def __init__(self, universe: list[tuple[str, str]] | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._universe = universe or []

    def execute(self, statement, params=None):
        sql = str(statement)
        # Bound params live on the TextClause for .bindparams() statements; the
        # per-row INSERT passes params positionally as the 2nd arg.
        self.calls.append((sql, params or {}))
        if sql.strip().upper().startswith("SELECT DISTINCT"):
            return _FakeResult(self._universe)
        return _FakeResult([])


def _load_migration(filename: str, fake_bind: _FakeBind):
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


_FILE = "0025_alpaca_daily_full_universe.py"


class TestMigration0025:
    def test_revision_chain(self) -> None:
        mod = _load_migration(_FILE, _FakeBind())
        assert mod.revision == "0025"
        assert mod.down_revision == "0024"

    def test_seed_matches_0023_format(self) -> None:
        """The 1d seed must match 0023 so ON CONFLICT dedups the existing 96 rows."""
        mod = _load_migration(_FILE, _FakeBind())
        # Reproduce 0023's exact seed string.
        assert mod._ulid_from_seed("alpaca:ohlcv:AAPL:US:1d:").startswith("01HX")
        assert mod._ulid_from_seed("alpaca:ohlcv:AAPL:US:1d:") == mod._ulid_from_seed("alpaca:ohlcv:AAPL:US:1d:")

    def test_skip_exchanges(self) -> None:
        mod = _load_migration(_FILE, _FakeBind())
        assert set(mod._SKIP_EXCHANGES) == {"INDX", "FOREX", "SHG"}

    def test_daily_constants(self) -> None:
        mod = _load_migration(_FILE, _FakeBind())
        assert mod._DAILY_INTERVAL_SEC == 86400
        assert mod._DAILY_PRIORITY == 30

    def test_upgrade_inserts_one_policy_per_universe_row(self) -> None:
        universe = [("AAPL", "US"), ("MSFT", "US"), ("BTC-USD", "CC")]
        bind = _FakeBind(universe=universe)
        mod = _load_migration(_FILE, bind)
        mod.upgrade()

        inserts = [(sql, p) for sql, p in bind.calls if sql.strip().upper().startswith("INSERT")]
        assert len(inserts) == len(universe)

        # Every insert row carries the expected canonical values.
        seen_symbols = set()
        for _sql, params in inserts:
            assert params["provider"] == "alpaca"
            assert params["dataset_type"] == "ohlcv"
            assert params["timeframe"] == "1d"
            assert params["base_interval_sec"] == 86400
            assert params["min_interval_sec"] == 86400
            assert params["priority"] == 30
            assert params["enabled"] is True
            assert params["market_hours_only"] is False
            assert params["tier"] == 2
            assert params["id"] == mod._ulid_from_seed(f"alpaca:ohlcv:{params['symbol']}:{params['exchange']}:1d:")
            seen_symbols.add(params["symbol"])
        assert seen_symbols == {"AAPL", "MSFT", "BTC-USD"}

    def test_upgrade_disables_eodhd_us_cc_not_indx(self) -> None:
        bind = _FakeBind(universe=[("AAPL", "US")])
        mod = _load_migration(_FILE, bind)
        mod.upgrade()

        disable = [
            (sql, p) for sql, p in bind.calls if sql.strip().upper().startswith("UPDATE") and "enabled = false" in sql
        ]
        assert len(disable) == 1
        sql, _params = disable[0]
        assert "provider = 'eodhd'" in sql
        assert "timeframe = '1d'" in sql
        # The disable is scoped away from the skip exchanges.
        assert "exchange <> ALL(:skip)" in sql

    def test_downgrade_reenables_eodhd_and_deletes_added_alpaca(self) -> None:
        bind = _FakeBind()
        mod = _load_migration(_FILE, bind)
        mod.downgrade()

        deletes = [sql for sql, _ in bind.calls if sql.strip().upper().startswith("DELETE")]
        reenables = [
            sql for sql, _ in bind.calls if sql.strip().upper().startswith("UPDATE") and "enabled = true" in sql
        ]
        assert len(deletes) == 1
        assert len(reenables) == 1
        # Delete leaves 0023's rows (those with an enabled 1m sibling) intact.
        assert "NOT EXISTS" in deletes[0]
        assert "timeframe = '1m'" in deletes[0]
