"""Unit tests for _metrics_poller in infrastructure/metrics/poller.py.

Note: _run_fetch_cycle was removed in PLAN-0006 Wave B-4 — its functionality
lives in ExecuteContentTaskUseCase (tested in test_execute_task.py).
_metrics_poller was moved from app.py to infrastructure/metrics/poller.py in
PLAN-0011 Wave B-2 (R22 — no background tasks in app.py lifespan).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestMetricsPoller:
    async def test_metrics_poller_updates_gauges(self) -> None:
        """Verify metrics poller queries outbox + DLQ counts."""
        from content_ingestion.infrastructure.metrics.poller import _metrics_poller

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        import asyncio

        with (
            patch("content_ingestion.infrastructure.metrics.poller.s4_outbox_pending_total") as mock_outbox,
            patch("content_ingestion.infrastructure.metrics.poller.s4_dlq_total") as mock_dlq,
        ):
            task = asyncio.create_task(_metrics_poller(mock_factory, interval=9999))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        mock_outbox.set.assert_called()
        mock_dlq.set.assert_called()

    async def test_metrics_poller_handles_db_error(self) -> None:
        """DB error should not crash the poller."""
        from content_ingestion.infrastructure.metrics.poller import _metrics_poller

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        import asyncio

        task = asyncio.create_task(_metrics_poller(mock_factory, interval=9999))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # No assertion — just verifying no unhandled exception
