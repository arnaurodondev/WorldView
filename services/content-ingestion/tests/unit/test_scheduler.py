"""Unit tests for the IngestionScheduler and advisory lock."""

from __future__ import annotations

import asyncio
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.infrastructure.scheduler.scheduler import ADAPTER_REGISTRY, IngestionScheduler

pytestmark = pytest.mark.unit


def _make_source(
    name: str = "test",
    source_type: SourceType = SourceType.EODHD,
    enabled: bool = True,
) -> Source:
    return Source(name=name, source_type=source_type, enabled=enabled, config={})


class TestAdapterRegistry:
    # Source types whose adapters are registered in ADAPTER_REGISTRY.
    # MANUAL: not polled — delivered via webhook/submit endpoint, no adapter needed.
    # POLYMARKET: adapter added in Wave A-2 (PLAN-0019); excluded here until then.
    # TENANT_UPLOAD: not polled — documents arrive via REST upload API (PLAN-0086).
    # POLYMARKET_GAMMA_EVENTS/CLOB/DATA_TRADES/DATA_OI (PLAN-0056 Wave B1): the
    #   deeper-stream Polymarket adapters route DIRECTLY via
    #   worker._execute_polymarket_task (R24 batch-collect pattern), NOT through
    #   ADAPTER_REGISTRY — same as the base POLYMARKET type. Worker routing is
    #   wired in Wave B3; excluded here because they are never registry adapters.
    _NO_ADAPTER: ClassVar[set[SourceType]] = {
        SourceType.MANUAL,
        SourceType.POLYMARKET,
        SourceType.TENANT_UPLOAD,
        SourceType.POLYMARKET_GAMMA_EVENTS,
        SourceType.POLYMARKET_CLOB,
        SourceType.POLYMARKET_DATA_TRADES,
        SourceType.POLYMARKET_DATA_OI,
    }

    def test_all_source_types_have_adapters(self) -> None:
        """Every SourceType except non-polled types should have an adapter."""
        for st in SourceType:
            if st in self._NO_ADAPTER:
                continue
            assert st in ADAPTER_REGISTRY, f"Missing adapter for {st}"

    def test_manual_not_in_registry(self) -> None:
        assert SourceType.MANUAL not in ADAPTER_REGISTRY

    def test_polymarket_not_in_registry(self) -> None:
        """POLYMARKET is intentionally excluded from ADAPTER_REGISTRY (F-407).

        Polymarket tasks are handled by _execute_polymarket_task() in worker.py
        (R24 compliance: batch-collect all results first, then short-lived DB session
        for dedup).  They do NOT go through the standard SourceAdapter path.
        """
        assert SourceType.POLYMARKET not in ADAPTER_REGISTRY


class TestIngestionScheduler:
    async def test_start_creates_tasks_for_enabled_sources(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)

        sources = [
            _make_source(name="eodhd", source_type=SourceType.EODHD),
            _make_source(name="finnhub", source_type=SourceType.FINNHUB),
        ]
        await scheduler.start(sources)

        assert len(scheduler._tasks) == 2
        assert "eodhd" in scheduler._tasks
        assert "finnhub" in scheduler._tasks

        await scheduler.stop()

    async def test_disabled_sources_are_skipped(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)

        sources = [
            _make_source(name="eodhd", enabled=False),
        ]
        await scheduler.start(sources)

        assert len(scheduler._tasks) == 0
        await scheduler.stop()

    async def test_stop_cancels_all_tasks(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=3600, run_fn=run_fn)

        sources = [_make_source(name="eodhd")]
        await scheduler.start(sources)
        assert len(scheduler._tasks) == 1

        await scheduler.stop()
        assert len(scheduler._tasks) == 0

    async def test_unknown_source_type_skipped(self) -> None:
        run_fn = AsyncMock()
        scheduler = IngestionScheduler(interval_seconds=60, run_fn=run_fn)

        sources = [_make_source(name="manual", source_type=SourceType.MANUAL)]
        await scheduler.start(sources)

        assert len(scheduler._tasks) == 0
        await scheduler.stop()

    async def test_poll_loop_calls_run_fn(self) -> None:
        """Verify run_fn gets called at least once."""
        call_count = 0

        async def counting_fn(source: Source) -> None:
            nonlocal call_count
            call_count += 1

        scheduler = IngestionScheduler(interval_seconds=0, run_fn=counting_fn)
        sources = [_make_source(name="eodhd")]
        await scheduler.start(sources)

        # Let the poll loop run briefly
        await asyncio.sleep(0.1)
        await scheduler.stop()

        assert call_count >= 1
