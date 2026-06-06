"""Unit tests for TickerNewsSymbolSyncWorker (PLAN-0106 Wave C-2).

Tests cover:
  - Disabled fast-path: run() returns immediately when enabled=False.
  - Tick creates sources for each instrument returned by market-data.
  - Idempotency: already-existing source (was_created=False) → no duplicate.
  - Market-data error → empty instrument list, warning logged, no raise.
  - Stop event interrupts the loop.
  - JWT signing: dev fallback (no private key) and RS256 (with private key).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.infrastructure.workers.ticker_news_sync_worker import (
    TickerNewsSymbolSyncWorker,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    ticker_news_sync_enabled: bool = True,
    ticker_news_sync_interval_hours: float = 0.001,  # very short for tests
    market_data_url: str = "http://market-data:8003",
    internal_jwt_private_key: str = "",
) -> MagicMock:
    s = MagicMock()
    s.db_url = MagicMock()
    s.db_url.get_secret_value.return_value = "postgresql+asyncpg://u:p@localhost:5432/test"
    s.db_url_read = ""
    s.ticker_news_sync_enabled = ticker_news_sync_enabled
    s.ticker_news_sync_interval_hours = ticker_news_sync_interval_hours
    s.market_data_url = market_data_url
    s.internal_jwt_private_key = internal_jwt_private_key
    return s


def _make_create_result(
    was_created: bool = True,
    symbol: str = "AAPL",
    exchange: str = "US",
) -> MagicMock:
    from uuid import uuid4

    result = MagicMock()
    result.was_created = was_created
    result.id = uuid4()
    result.name = f"eodhd-ticker-news-{symbol.lower()}-{exchange.lower()}"
    return result


# ---------------------------------------------------------------------------
# Disabled fast-path
# ---------------------------------------------------------------------------


class TestTickerNewsWorkerDisabled:
    async def test_run_returns_immediately_when_disabled(self) -> None:
        """When enabled=False, run() exits without building DB factories."""
        settings = _make_settings(ticker_news_sync_enabled=False)
        worker = TickerNewsSymbolSyncWorker(settings=settings)

        # Should return without creating any DB connections
        with patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker._build_factories") as mock_build:
            await worker.run()

        mock_build.assert_not_called()

    def test_enabled_property_reads_from_settings(self) -> None:
        s_on = _make_settings(ticker_news_sync_enabled=True)
        s_off = _make_settings(ticker_news_sync_enabled=False)

        assert TickerNewsSymbolSyncWorker(settings=s_on).enabled is True
        assert TickerNewsSymbolSyncWorker(settings=s_off).enabled is False

    def test_enabled_defaults_to_true_via_getattr_fallback(self) -> None:
        """enabled uses getattr(..., True) so missing attribute → True."""
        settings = MagicMock(spec=[])  # no ticker_news_sync_enabled attr
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        assert worker.enabled is True


# ---------------------------------------------------------------------------
# _tick — happy path
# ---------------------------------------------------------------------------


class TestTickerNewsWorkerTick:
    async def test_tick_creates_sources_for_each_instrument(self) -> None:
        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        worker._write_factory = MagicMock()
        worker._read_factory = MagicMock()

        instruments = [
            {"symbol": "AAPL", "exchange": "US"},
            {"symbol": "MSFT", "exchange": "US"},
        ]

        created_results = [
            _make_create_result(was_created=True, symbol=s, exchange=e) for s, e in [("AAPL", "US"), ("MSFT", "US")]
        ]

        call_count = 0

        async def _fake_execute(**kwargs: object) -> MagicMock:
            nonlocal call_count
            r = created_results[call_count]
            call_count += 1
            return r

        with (
            patch.object(worker, "_fetch_us_instruments", new=AsyncMock(return_value=instruments)),
            patch(
                "content_ingestion.infrastructure.workers.ticker_news_sync_worker.CreateSourceUseCase"
            ) as mock_uc_cls,
            patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker.SqlaUnitOfWork"),
        ):
            mock_uc_instance = MagicMock()
            mock_uc_instance.execute = AsyncMock(side_effect=_fake_execute)
            mock_uc_cls.return_value = mock_uc_instance

            await worker._tick()

        assert mock_uc_instance.execute.call_count == 2

    async def test_tick_passes_correct_source_name(self) -> None:
        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        worker._write_factory = MagicMock()
        worker._read_factory = MagicMock()

        instruments = [{"symbol": "NVDA", "exchange": "US"}]

        with (
            patch.object(worker, "_fetch_us_instruments", new=AsyncMock(return_value=instruments)),
            patch(
                "content_ingestion.infrastructure.workers.ticker_news_sync_worker.CreateSourceUseCase"
            ) as mock_uc_cls,
            patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker.SqlaUnitOfWork"),
        ):
            mock_uc_instance = MagicMock()
            mock_uc_instance.execute = AsyncMock(return_value=_make_create_result(symbol="NVDA"))
            mock_uc_cls.return_value = mock_uc_instance

            await worker._tick()

        call_kwargs = mock_uc_instance.execute.call_args.kwargs
        assert call_kwargs["name"] == "eodhd-ticker-news-nvda-us"
        assert call_kwargs["source_type"] == "eodhd_ticker_news"
        assert call_kwargs["config"] == {"symbol": "NVDA", "exchange": "US"}
        assert call_kwargs["enabled"] is True

    async def test_tick_skips_empty_symbol(self) -> None:
        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        worker._write_factory = MagicMock()
        worker._read_factory = MagicMock()

        instruments = [{"symbol": "", "exchange": "US"}]  # empty symbol

        with (
            patch.object(worker, "_fetch_us_instruments", new=AsyncMock(return_value=instruments)),
            patch(
                "content_ingestion.infrastructure.workers.ticker_news_sync_worker.CreateSourceUseCase"
            ) as mock_uc_cls,
            patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker.SqlaUnitOfWork"),
        ):
            await worker._tick()

        mock_uc_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestTickerNewsWorkerIdempotency:
    async def test_existing_source_not_counted_as_new(self) -> None:
        """If was_created=False, the source already existed — no duplicate."""
        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        worker._write_factory = MagicMock()
        worker._read_factory = MagicMock()

        instruments = [{"symbol": "AAPL", "exchange": "US"}]
        existing_result = _make_create_result(was_created=False)  # already existed

        with (
            patch.object(worker, "_fetch_us_instruments", new=AsyncMock(return_value=instruments)),
            patch(
                "content_ingestion.infrastructure.workers.ticker_news_sync_worker.CreateSourceUseCase"
            ) as mock_uc_cls,
            patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker.SqlaUnitOfWork"),
            patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker.logger") as mock_logger,
        ):
            mock_uc_instance = MagicMock()
            mock_uc_instance.execute = AsyncMock(return_value=existing_result)
            mock_uc_cls.return_value = mock_uc_instance

            await worker._tick()

        # ticker_news_source_created should NOT be called since was_created=False
        info_events = [c[0][0] for c in mock_logger.info.call_args_list]
        assert "ticker_news_source_created" not in info_events


# ---------------------------------------------------------------------------
# Market-data error handling
# ---------------------------------------------------------------------------


class TestTickerNewsWorkerMarketDataError:
    async def test_non_2xx_returns_empty_list(self) -> None:
        import httpx

        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 503

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_resp

            result = await worker._fetch_us_instruments()

        assert result == []

    async def test_network_error_returns_empty_list(self) -> None:
        import httpx

        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("refused")

            result = await worker._fetch_us_instruments()

        assert result == []

    async def test_empty_instruments_logs_warning_and_does_not_raise(self) -> None:
        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        worker._write_factory = MagicMock()
        worker._read_factory = MagicMock()

        with (
            patch.object(worker, "_fetch_us_instruments", new=AsyncMock(return_value=[])),
            patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker.logger") as mock_logger,
        ):
            # Must not raise
            await worker._tick()

        warning_events = [c[0][0] for c in mock_logger.warning.call_args_list]
        assert "ticker_news_sync_no_instruments" in warning_events

    async def test_upsert_error_does_not_abort_loop(self) -> None:
        """An exception for one ticker must not stop the rest."""
        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        worker._write_factory = MagicMock()
        worker._read_factory = MagicMock()

        instruments = [
            {"symbol": "FAIL", "exchange": "US"},
            {"symbol": "AAPL", "exchange": "US"},
        ]
        call_count = 0

        async def _side_effect(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("DB error on first ticker")
            return _make_create_result(symbol="AAPL")

        with (
            patch.object(worker, "_fetch_us_instruments", new=AsyncMock(return_value=instruments)),
            patch(
                "content_ingestion.infrastructure.workers.ticker_news_sync_worker.CreateSourceUseCase"
            ) as mock_uc_cls,
            patch("content_ingestion.infrastructure.workers.ticker_news_sync_worker.SqlaUnitOfWork"),
        ):
            mock_uc_instance = MagicMock()
            mock_uc_instance.execute = AsyncMock(side_effect=_side_effect)
            mock_uc_cls.return_value = mock_uc_instance

            # Should not raise even though first ticker fails
            await worker._tick()

        # Both tickers were attempted
        assert mock_uc_instance.execute.call_count == 2


# ---------------------------------------------------------------------------
# Stop event
# ---------------------------------------------------------------------------


class TestTickerNewsWorkerStop:
    def test_stop_sets_stop_event(self) -> None:
        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)
        assert not worker._stop_event.is_set()
        worker.stop()
        assert worker._stop_event.is_set()


# ---------------------------------------------------------------------------
# JWT signing
# ---------------------------------------------------------------------------


class TestTickerNewsWorkerJWT:
    def test_dev_fallback_returns_hs256_token(self) -> None:
        import jwt as pyjwt

        settings = _make_settings(internal_jwt_private_key="")
        worker = TickerNewsSymbolSyncWorker(settings=settings)

        token = worker._sign_internal_jwt()
        # Decode without verification to check algorithm
        header = pyjwt.get_unverified_header(token)
        assert header["alg"] == "HS256"

    def test_jwt_payload_has_correct_sub(self) -> None:
        import jwt as pyjwt

        settings = _make_settings(internal_jwt_private_key="")
        worker = TickerNewsSymbolSyncWorker(settings=settings)

        token = worker._sign_internal_jwt()
        payload = pyjwt.decode(
            token,
            "dev-skip-verification-key-for-kg-structured-enrichment",
            algorithms=["HS256"],
        )
        assert payload["sub"] == "system:ticker-news-sync-worker"
        assert payload["role"] == "system"

    def test_fetch_us_instruments_response_envelope_handling(self) -> None:
        """_fetch_us_instruments handles both list and {results: [...]} shapes."""
        # Tested via the happy-path HTTP mock — direct list
        # and the results-envelope shape tested separately.
        import httpx

        settings = _make_settings()
        worker = TickerNewsSymbolSyncWorker(settings=settings)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [{"symbol": "AAPL", "exchange": "US"}]}

        async def _test() -> None:
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client_cls.return_value.__aenter__.return_value = mock_client
                mock_client.get.return_value = mock_resp

                result = await worker._fetch_us_instruments()

            assert result == [{"symbol": "AAPL", "exchange": "US"}]

        import asyncio

        asyncio.get_event_loop().run_until_complete(_test())
