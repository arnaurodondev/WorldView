"""Unit tests for the durable worker-runs last-success store (migration 040).

Covers ``read_last_success`` (fail-soft on error, parses the stored timestamp)
and ``record_success`` (issues an UPSERT with the right bind params + commits).
The SQL runs against a real Postgres in the integration ring; here we assert the
behaviour against a mock session.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.infrastructure.db.worker_runs import read_last_success, record_success

pytestmark = pytest.mark.unit


def _make_factory(execute_side_effect: Any) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute_side_effect)
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    factory._session = session
    return factory


@pytest.mark.asyncio
async def test_read_last_success_returns_stored_timestamp() -> None:
    """A present row returns its ``last_success_at`` datetime."""
    ts = datetime(2026, 6, 18, 2, 0, 0, tzinfo=UTC)

    async def _execute(_stmt: Any, _params: Any | None = None) -> MagicMock:
        result = MagicMock()
        result.first = MagicMock(return_value=(ts,))
        return result

    factory = _make_factory(_execute)
    assert await read_last_success(factory, "computed_metrics_backfill") == ts


@pytest.mark.asyncio
async def test_read_last_success_returns_none_when_no_row() -> None:
    """No row → None (treated as 'no prior run')."""

    async def _execute(_stmt: Any, _params: Any | None = None) -> MagicMock:
        result = MagicMock()
        result.first = MagicMock(return_value=None)
        return result

    factory = _make_factory(_execute)
    assert await read_last_success(factory, "computed_metrics_backfill") is None


@pytest.mark.asyncio
async def test_read_last_success_fail_soft_on_error() -> None:
    """Any DB error (e.g. table missing on a lagging DB) returns None, not raise."""

    async def _execute(_stmt: Any, _params: Any | None = None) -> MagicMock:
        raise RuntimeError('relation "worker_runs" does not exist')

    factory = _make_factory(_execute)
    # Must NOT propagate — the scheduler treats this as "no prior run".
    assert await read_last_success(factory, "computed_metrics_backfill") is None


@pytest.mark.asyncio
async def test_record_success_upserts_with_bind_params_and_commits() -> None:
    """``record_success`` issues an INSERT ... ON CONFLICT UPSERT and commits."""
    ts = datetime(2026, 6, 18, 2, 0, 5, tzinfo=UTC)
    captured: dict[str, Any] = {}

    async def _execute(stmt: Any, params: Any | None = None) -> MagicMock:
        captured["sql"] = str(stmt)
        captured["params"] = params
        return MagicMock()

    factory = _make_factory(_execute)
    await record_success(factory, "computed_metrics_backfill", ts)

    assert "on conflict" in captured["sql"].lower()
    assert captured["params"] == {"name": "computed_metrics_backfill", "ts": ts}
    factory._session.commit.assert_awaited_once()
