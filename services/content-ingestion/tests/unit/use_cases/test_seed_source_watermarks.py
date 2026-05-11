"""Tests for SeedSourceWatermarksUseCase (PLAN-0055 A-3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.seed_source_watermarks import (
    SeedSourceWatermarksUseCase,
    SeedWatermarkSummary,
)

pytestmark = pytest.mark.unit


def _make_settings(*, on: bool = True, initial_days: int = 14, years: int = 3) -> MagicMock:
    s = MagicMock()
    s.backfill_on_startup = on
    s.backfill_initial_days = initial_days
    s.backfill_years = years
    return s


def _make_source(source_id: str = "abc") -> MagicMock:
    s = MagicMock()
    s.id = source_id
    s.name = f"src-{source_id}"
    return s


def _make_uow(
    sources: list[MagicMock] | None = None,
    state_for: dict | None = None,
) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.sources = AsyncMock(list_enabled=AsyncMock(return_value=sources or []))
    uow.adapter_state = AsyncMock()
    state_map = state_for or {}
    uow.adapter_state.get = AsyncMock(side_effect=lambda sid: state_map.get(sid))
    uow.adapter_state.upsert = AsyncMock()
    return uow


class TestSeedSourceWatermarks:
    async def test_disabled_returns_empty_summary(self) -> None:
        settings = _make_settings(on=False)
        uow_factory = MagicMock(return_value=_make_uow())
        uc = SeedSourceWatermarksUseCase(uow_factory=uow_factory, settings=settings)
        summary = await uc.execute()
        assert summary == SeedWatermarkSummary()
        # Did not even build a UoW.
        uow_factory.assert_not_called()

    async def test_seeds_null_watermarks(self) -> None:
        # Two sources, both with NULL watermarks → both seeded.
        s1 = _make_source("s1")
        s2 = _make_source("s2")
        settings = _make_settings(initial_days=14, years=3)
        uow_factory = MagicMock(side_effect=lambda: _make_uow(sources=[s1, s2], state_for={}))
        uc = SeedSourceWatermarksUseCase(uow_factory=uow_factory, settings=settings)
        summary = await uc.execute()
        assert summary.seeded == 2
        assert summary.skipped == 0
        assert summary.failed == 0

    async def test_skips_existing_watermarks(self) -> None:
        # Source with non-NULL watermark → skipped (idempotent re-run).
        s1 = _make_source("s1")
        existing_state = MagicMock()
        existing_state.last_watermark = datetime(2026, 1, 1, tzinfo=UTC)
        settings = _make_settings()
        uow_factory = MagicMock(side_effect=lambda: _make_uow(sources=[s1], state_for={s1.id: existing_state}))
        uc = SeedSourceWatermarksUseCase(uow_factory=uow_factory, settings=settings)
        summary = await uc.execute()
        assert summary.seeded == 0
        assert summary.skipped == 1

    async def test_horizon_clamped_by_years(self) -> None:
        # initial_days=10000 but years=3 → should clamp to 3*365=1095 days max.
        # We assert via the upsert call: the target_watermark must be > now-10000d.
        s1 = _make_source("s1")
        settings = _make_settings(initial_days=10000, years=3)
        uow = _make_uow(sources=[s1], state_for={})
        uow_factory = MagicMock(return_value=uow)
        uc = SeedSourceWatermarksUseCase(uow_factory=uow_factory, settings=settings)
        await uc.execute()
        # Find the upsert call (ignore the list_enabled call's UoW).
        # Each call to uow_factory returns the same `uow` for the test.
        assert uow.adapter_state.upsert.called
        kwargs = uow.adapter_state.upsert.call_args.kwargs
        target = kwargs["last_watermark"]
        # Must be within the last 3 years (clamp), not 10000 days.
        assert (datetime.now(tz=UTC) - target) <= timedelta(days=1095 + 1)
