"""Unit tests for the F-201 guard in ``repair_holdings_after_replay_drift``.

The guard exists to prevent the iter-1 incident: zeroing every holding for a
portfolio whose broker sandbox returns ``activity_count=0`` on resync, leaving
the user with a $178k equity curve over $0 of positions.

Coverage:
    - last_synced_at IS NULL          → skip
    - last_synced_at older than 24h   → skip
    - no transactions for portfolio   → skip
    - fresh sync + has transactions   → eligible
    - --force overrides everything    → eligible regardless

We exercise ``_gather_eligible_portfolios`` directly with a fake async session
that emulates SQLAlchemy's ``execute(...).fetchall() / .scalar()`` interface.
The script is too thin around DB calls to deserve a heavier integration
harness — the fake covers exactly what the function reads.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


# Load the script module from its filesystem path. The script lives at
# ``services/portfolio/scripts/repair_holdings_after_replay_drift.py`` and is
# normally invoked via ``python -m portfolio.scripts.repair_…`` inside the
# Docker container, but the ``scripts/`` directory is not a Python package on
# the test host (no ``__init__.py``). Loading via importlib gives the test
# direct access to ``_gather_eligible_portfolios`` without polluting the
# shipped layout.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_holdings_after_replay_drift.py"
_spec = importlib.util.spec_from_file_location(
    "repair_holdings_after_replay_drift_test_module",
    _SCRIPT_PATH,
)
assert _spec is not None and _spec.loader is not None, f"Could not load repair script from {_SCRIPT_PATH}"
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
_gather_eligible_portfolios = _module._gather_eligible_portfolios


# ── Fake async session ──────────────────────────────────────────────────────


class _FakeResult:
    """Minimal stand-in for SQLAlchemy's Result — only the methods we use."""

    def __init__(self, rows: Sequence[Any] | None = None, scalar_value: Any = None) -> None:
        self._rows = list(rows) if rows is not None else []
        self._scalar = scalar_value

    def fetchall(self) -> list[Any]:
        return self._rows

    def scalar(self) -> Any:
        return self._scalar


class _FakeSession:
    """Routes ``execute(text(...), params)`` calls based on the SQL fragment.

    The script issues exactly two query shapes against the session:
      1. ``SELECT DISTINCT bc.portfolio_id, bc.last_synced_at FROM brokerage_connections``
      2. ``SELECT COUNT(*) FROM transactions WHERE portfolio_id = :pid``

    We dispatch on a substring of the SQL text so the test is robust to
    whitespace/formatting changes.
    """

    def __init__(
        self,
        *,
        connection_rows: list[tuple[UUID, datetime | None]],
        tx_counts: dict[UUID, int],
    ) -> None:
        self._connection_rows = connection_rows
        self._tx_counts = tx_counts

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(stmt).lower()
        if "from brokerage_connections" in sql:
            # Maps to gather query — return the configured (portfolio_id, last_synced_at) rows.
            return _FakeResult(rows=self._connection_rows)
        if "from transactions" in sql:
            # Per-portfolio transaction count.
            assert params is not None and "pid" in params
            pid = params["pid"]
            return _FakeResult(scalar_value=self._tx_counts.get(pid, 0))
        raise AssertionError(f"Unexpected SQL in test fake: {sql!r}")


# ── Tests ────────────────────────────────────────────────────────────────────


class TestGatherEligiblePortfolios:
    """Behavioural tests for the guard."""

    async def test_null_last_synced_at_is_skipped(self) -> None:
        """A connection that has never successfully synced must not be zeroed."""
        pid = uuid4()
        session = _FakeSession(
            connection_rows=[(pid, None)],
            tx_counts={pid: 100},  # even with txs, NULL sync is suspicious
        )
        eligible, skipped = await _gather_eligible_portfolios(session, force=False)
        assert eligible == []
        assert skipped == [pid]

    async def test_stale_last_synced_at_is_skipped(self) -> None:
        """A connection that hasn't synced in >24h is treated as broken."""
        pid = uuid4()
        stale = datetime.now(tz=UTC) - timedelta(hours=48)
        session = _FakeSession(
            connection_rows=[(pid, stale)],
            tx_counts={pid: 100},
        )
        eligible, skipped = await _gather_eligible_portfolios(session, force=False)
        assert eligible == []
        assert skipped == [pid]

    async def test_no_transactions_is_skipped(self) -> None:
        """Even with a fresh sync, a portfolio with zero transactions would be orphaned."""
        pid = uuid4()
        fresh = datetime.now(tz=UTC) - timedelta(hours=1)
        session = _FakeSession(
            connection_rows=[(pid, fresh)],
            tx_counts={pid: 0},
        )
        eligible, skipped = await _gather_eligible_portfolios(session, force=False)
        assert eligible == []
        assert skipped == [pid]

    async def test_fresh_sync_and_transactions_are_eligible(self) -> None:
        """Happy path — broker is responsive AND has fed us data."""
        pid = uuid4()
        fresh = datetime.now(tz=UTC) - timedelta(hours=1)
        session = _FakeSession(
            connection_rows=[(pid, fresh)],
            tx_counts={pid: 50},
        )
        eligible, skipped = await _gather_eligible_portfolios(session, force=False)
        assert eligible == [pid]
        assert skipped == []

    async def test_force_overrides_every_guard(self) -> None:
        """``--force`` short-circuits all guard logic — operator accepts the risk."""
        pids = [uuid4(), uuid4(), uuid4()]
        # Three portfolios that would each be skipped without --force:
        #   pid[0] — NULL last_synced_at
        #   pid[1] — stale sync
        #   pid[2] — fresh sync but no transactions
        stale = datetime.now(tz=UTC) - timedelta(days=3)
        fresh = datetime.now(tz=UTC) - timedelta(hours=1)
        session = _FakeSession(
            connection_rows=[
                (pids[0], None),
                (pids[1], stale),
                (pids[2], fresh),
            ],
            tx_counts={pids[2]: 0},
        )
        eligible, skipped = await _gather_eligible_portfolios(session, force=True)
        assert eligible == pids
        assert skipped == []

    async def test_mixed_eligible_and_skipped(self) -> None:
        """Some portfolios pass, others fail — function returns both lists."""
        good = uuid4()
        bad_null = uuid4()
        bad_stale = uuid4()
        fresh = datetime.now(tz=UTC) - timedelta(hours=2)
        stale = datetime.now(tz=UTC) - timedelta(days=2)
        session = _FakeSession(
            connection_rows=[
                (good, fresh),
                (bad_null, None),
                (bad_stale, stale),
            ],
            tx_counts={good: 25},
        )
        eligible, skipped = await _gather_eligible_portfolios(session, force=False)
        assert eligible == [good]
        assert sorted(str(x) for x in skipped) == sorted([str(bad_null), str(bad_stale)])

    async def test_empty_connection_table_returns_empty(self) -> None:
        """No brokerage connections → both lists empty (script then no-ops)."""
        session = _FakeSession(connection_rows=[], tx_counts={})
        eligible, skipped = await _gather_eligible_portfolios(session, force=False)
        assert eligible == []
        assert skipped == []
