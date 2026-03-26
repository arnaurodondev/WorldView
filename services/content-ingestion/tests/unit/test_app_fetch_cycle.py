"""Unit tests for _run_fetch_cycle in app.py (T-R1-5-02)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import Source, SourceType

pytestmark = pytest.mark.unit


def _make_source(name: str = "test", source_type: SourceType = SourceType.EODHD) -> Source:
    return Source(name=name, source_type=source_type, enabled=True, config={"ticker": "AAPL"})


class TestRunFetchCycle:
    async def test_unknown_source_type_returns_early(self) -> None:
        """If ADAPTER_REGISTRY has no entry for source_type, returns immediately."""
        from content_ingestion.app import _run_fetch_cycle

        source = _make_source(source_type=SourceType.EODHD)
        settings = MagicMock()

        # Patch ADAPTER_REGISTRY to be empty
        with patch("content_ingestion.app.ADAPTER_REGISTRY", {}):
            await _run_fetch_cycle(
                source=source,
                settings=settings,
                session_factory=MagicMock(),
                storage=MagicMock(),
                valkey=MagicMock(),
                http_client=MagicMock(),
            )
        # No assertion needed — just verifying no exception raised

    async def test_empty_fetch_results_skips_write_phase(self) -> None:
        """If adapter returns empty results, we never acquire the advisory lock."""
        from content_ingestion.app import _run_fetch_cycle

        source = _make_source()
        settings = MagicMock(backfill_enabled=False, eodhd_api_key="key")

        mock_adapter = AsyncMock(fetch=AsyncMock(return_value=[]))
        mock_adapter_cls = MagicMock(return_value=mock_adapter)

        mock_session_factory = MagicMock()

        # Read-only session for watermark
        ro_session = AsyncMock()
        ro_session.__aenter__ = AsyncMock(return_value=ro_session)
        ro_session.__aexit__ = AsyncMock(return_value=False)

        # Dedup session
        dedup_session = AsyncMock()
        dedup_session.__aenter__ = AsyncMock(return_value=dedup_session)
        dedup_session.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def session_factory_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ro_session
            return dedup_session

        mock_session_factory.side_effect = session_factory_side_effect

        with (
            patch("content_ingestion.app.ADAPTER_REGISTRY", {SourceType.EODHD: mock_adapter_cls}),
            patch(
                "content_ingestion.infrastructure.db.repositories.adapter_state.AdapterStateRepository.get",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("content_ingestion.app.FetchLogRepository"),
        ):
            await _run_fetch_cycle(
                source=source,
                settings=settings,
                session_factory=mock_session_factory,
                storage=MagicMock(),
                valkey=MagicMock(),
                http_client=MagicMock(),
            )

        # pg_advisory_lock should NOT have been called (no write phase)
        # This is verified by the fact that we only created 2 sessions (ro + dedup),
        # not a 3rd one for the write phase
        assert call_count == 2


class TestMetricsPoller:
    async def test_metrics_poller_updates_gauges(self) -> None:
        """Verify metrics poller queries outbox + DLQ counts."""
        from content_ingestion.app import _metrics_poller

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock(return_value=mock_session)

        import asyncio

        with (
            patch("content_ingestion.app.s4_outbox_pending_total") as mock_outbox,
            patch("content_ingestion.app.s4_dlq_total") as mock_dlq,
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
        from content_ingestion.app import _metrics_poller

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
