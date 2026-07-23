"""Unit tests for market-data standalone consumer and dispatcher entry points.

Covers: ohlcv_consumer_main, quotes_consumer_main, fundamentals_consumer_main,
        dispatcher_main (DispatcherProcess class).

All tests use ``unittest.mock.patch`` to isolate infrastructure — no real DB,
Kafka, MinIO, or Valkey connections are made.

The flat ``main()`` coroutines are exercised by patching ``asyncio.Event`` to
return a pre-set event, causing ``stop_event.wait()`` to return immediately and
the entire cleanup path to execute within the test.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force METRICS_PORT=0 so the real start_metrics_server picks an ephemeral
# port and never collides with the Docker stack's worldview-prometheus on 9100.
# PLAN-0107 FU — see audit 2026-05-29.
os.environ["METRICS_PORT"] = "0"

pytestmark = pytest.mark.unit

# Capture the real asyncio.Event class BEFORE any test patch replaces it.
# _preset_event must not call asyncio.Event() after the patch or recursion occurs.
_REAL_ASYNCIO_EVENT = asyncio.Event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _preset_event(*_args: object, **_kwargs: object) -> asyncio.Event:
    """Return a real asyncio.Event that is already set.

    Used as ``side_effect`` for ``patch("asyncio.Event")``, so
    ``stop_event.wait()`` inside the entrypoint returns immediately.
    """
    e = _REAL_ASYNCIO_EVENT()
    e.set()
    return e


def _mock_settings(**overrides: object) -> MagicMock:
    s = MagicMock()
    s.service_name = "market-data"
    s.log_level = "INFO"
    s.log_json = False
    s.storage_endpoint = "http://localhost:9000"
    s.storage_access_key = MagicMock(get_secret_value=lambda: "key")
    s.storage_secret_key = MagicMock(get_secret_value=lambda: "secret")
    s.kafka_bootstrap_servers = "localhost:9092"
    s.valkey_url = "redis://localhost:6379/0"
    # PLAN-0102 T-W6-02 / BP-617: integer typed so consumer_main's arithmetic
    # (session_timeout_ms = max(60_000, (timeout_s + 30) * 1_000)) works under
    # a MagicMock Settings stub. Default mirrors Settings().fundamentals_timeout_s.
    s.fundamentals_timeout_s = 90
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_supervised_consumer() -> MagicMock:
    """Return a mock consumer whose ``run()`` blocks until ``stop()`` fires.

    F-005 / BP-704: the consumer mains now drive the run loop through
    ``run_consumer_supervised``, which races ``run()`` against the stop event.
    A bare ``AsyncMock`` ``run()`` returns instantly and would be (correctly)
    flagged as an unexpected consumer exit — exactly the wedge-detection
    behaviour. Model the real contract instead: ``run()`` blocks until
    ``stop()`` releases a gate, so the supervisor takes the graceful path.
    """
    mock_consumer = MagicMock()
    _run_gate = _REAL_ASYNCIO_EVENT()

    async def _run_until_stopped() -> None:
        await _run_gate.wait()

    mock_consumer.run = _run_until_stopped
    mock_consumer.stop = MagicMock(side_effect=lambda: _run_gate.set())
    return mock_consumer


# ---------------------------------------------------------------------------
# ohlcv_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ohlcv_consumer_main_stop_before_run() -> None:
    """Pre-set stop_event causes main() to exit immediately after starting consumer."""
    mock_engine = AsyncMock()
    mock_consumer = MagicMock()
    # FAILURE MODE 2 supervision: a real run() blocks until stop() is signalled.
    # Model that contract so the supervisor takes the graceful-stop path (a
    # bare AsyncMock that returns instantly would now be flagged as an
    # unexpected run() exit — which is exactly the wedge-detection behaviour).
    _run_gate = _REAL_ASYNCIO_EVENT()

    async def _run_until_stopped() -> None:
        await _run_gate.wait()

    mock_consumer.run = _run_until_stopped
    mock_consumer.stop = MagicMock(side_effect=lambda: _run_gate.set())

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(
            "market_data.infrastructure.messaging.consumers.ohlcv_consumer.OHLCVConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer_main import main

        await main()

    # Consumer was started and gracefully stopped (stop() drains the run loop).
    mock_consumer.stop.assert_called_once()


@pytest.mark.asyncio
async def test_ohlcv_consumer_main_engine_disposed() -> None:
    """write_engine.dispose() is always called in the finally block."""
    mock_write_engine = AsyncMock()
    mock_read_engine = AsyncMock()
    mock_consumer = MagicMock()
    # run() blocks until stop() — see test_ohlcv_consumer_main_stop_before_run.
    _run_gate = _REAL_ASYNCIO_EVENT()

    async def _run_until_stopped() -> None:
        await _run_gate.wait()

    mock_consumer.run = _run_until_stopped
    mock_consumer.stop = MagicMock(side_effect=lambda: _run_gate.set())

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_write_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_read_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(
            "market_data.infrastructure.messaging.consumers.ohlcv_consumer.OHLCVConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer_main import main

        await main()

    mock_write_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_ohlcv_consumer_main_timeout_cancels() -> None:
    """When wait_for times out the consumer task is cancelled."""
    mock_engine = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.stop = MagicMock()

    # Consumer that never exits on its own
    async def run_forever() -> None:
        await asyncio.sleep(9999)

    mock_consumer.run = run_forever

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(
            "market_data.infrastructure.messaging.consumers.ohlcv_consumer.OHLCVConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
        # Force timeout so the test doesn't take 30 s
        patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
    ):
        from market_data.infrastructure.messaging.consumers.ohlcv_consumer_main import main

        await main()

    # Cleanup still runs after timeout
    mock_engine.dispose.assert_called()


# ---------------------------------------------------------------------------
# quotes_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quotes_consumer_main_stop_before_run() -> None:
    """Pre-set stop_event causes quotes main() to exit immediately."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("messaging.valkey.client.create_valkey_client_from_url", return_value=mock_valkey),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(
            "market_data.infrastructure.messaging.consumers.quotes_consumer.QuotesConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from market_data.infrastructure.messaging.consumers.quotes_consumer_main import main

        await main()

    # Supervised shutdown drains the run loop via stop().
    mock_consumer.stop.assert_called_once()


@pytest.mark.asyncio
async def test_quotes_consumer_main_graceful_stop() -> None:
    """valkey.close() and engine.dispose() called on graceful stop."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("messaging.valkey.client.create_valkey_client_from_url", return_value=mock_valkey),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(
            "market_data.infrastructure.messaging.consumers.quotes_consumer.QuotesConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from market_data.infrastructure.messaging.consumers.quotes_consumer_main import main

        await main()

    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called()


# ---------------------------------------------------------------------------
# fundamentals_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fundamentals_consumer_main_stop_before_run() -> None:
    """Pre-set stop_event causes fundamentals main() to exit immediately."""
    mock_engine = AsyncMock()
    mock_consumer = _make_supervised_consumer()

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(
            "market_data.infrastructure.messaging.consumers.fundamentals_consumer.FundamentalsConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer_main import main

        await main()

    # Supervised shutdown drains the run loop via stop().
    mock_consumer.stop.assert_called_once()


@pytest.mark.asyncio
async def test_fundamentals_consumer_main_engine_disposed() -> None:
    """write_engine.dispose() called on exit from fundamentals consumer."""
    mock_engine = AsyncMock()
    mock_consumer = _make_supervised_consumer()

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(
            "market_data.infrastructure.messaging.consumers.fundamentals_consumer.FundamentalsConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from market_data.infrastructure.messaging.consumers.fundamentals_consumer_main import main

        await main()

    mock_engine.dispose.assert_called()


# ---------------------------------------------------------------------------
# F-005 / BP-704 — every consumer main wires a stall-aware /healthz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("main_module", "consumer_path"),
    [
        (
            "market_data.infrastructure.messaging.consumers.insider_transactions_consumer_main",
            "market_data.infrastructure.messaging.consumers.insider_transactions_consumer.InsiderTransactionsConsumer",
        ),
        (
            "market_data.infrastructure.messaging.consumers.quotes_consumer_main",
            "market_data.infrastructure.messaging.consumers.quotes_consumer.QuotesConsumer",
        ),
        (
            "market_data.infrastructure.messaging.consumers.fundamentals_consumer_main",
            "market_data.infrastructure.messaging.consumers.fundamentals_consumer.FundamentalsConsumer",
        ),
        (
            "market_data.infrastructure.messaging.consumers.intraday_resampling_consumer_main",
            "market_data.infrastructure.messaging.consumers.intraday_resampling_consumer.IntradayResamplingConsumer",
        ),
        (
            "market_data.infrastructure.messaging.consumers.prediction_market_consumer_main",
            "market_data.infrastructure.messaging.consumers.prediction_market_consumer.PredictionMarketConsumer",
        ),
        # fix/earnings-consumer-ci: the earnings-calendar consumer main ships a
        # compose container (docker-compose.test.yml) but was never exercised
        # by an entrypoint test. Assert it boots and wires the stall-aware
        # /healthz probe like every other consumer so CI catches a broken start.
        (
            "market_data.infrastructure.messaging.consumers.earnings_calendar_consumer_main",
            "market_data.infrastructure.messaging.consumers.earnings_calendar_consumer.EarningsCalendarConsumer",
        ),
    ],
)
async def test_consumer_main_wires_stall_aware_healthz(main_module: str, consumer_path: str) -> None:
    """Each consumer main calls start_metrics_server with a non-None liveness_probe.

    This is the load-bearing F-005 / BP-704 assertion: /healthz must EXIST on
    9100 (so the Docker healthcheck passes) AND be stall-aware (a bound probe so
    it flips to 503 when the poll loop wedges). Patching start_metrics_server in
    the consumer-main module namespace lets us inspect the call args without
    binding a real socket.
    """
    import importlib

    mod = importlib.import_module(main_module)
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    captured: dict[str, object] = {}

    def _fake_start(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        return MagicMock(aclose=AsyncMock())

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(f"{main_module}.start_metrics_server", side_effect=_fake_start),
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=MagicMock()),
        patch("messaging.valkey.client.create_valkey_client_from_url", return_value=mock_valkey),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch(consumer_path, return_value=mock_consumer),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        await mod.main()

    assert captured.get("liveness_probe") is not None


# ---------------------------------------------------------------------------
# dispatcher_main — DispatcherProcess class
# ---------------------------------------------------------------------------


def test_dispatcher_main_stop_delegates_to_dispatcher() -> None:
    """DispatcherProcess.stop() calls the underlying dispatcher's stop()."""
    from market_data.infrastructure.messaging.outbox.dispatcher_main import DispatcherProcess

    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()

    # outbox_retention_seconds / ingestion_events_retention_days must be real
    # ints (0 = pruner disabled) — _build_retention_workers compares them
    # against 0, which raises on a bare MagicMock attribute.
    settings = MagicMock()
    settings.outbox_retention_seconds = 0
    settings.ingestion_events_retention_days = 0

    with (
        patch("market_data.infrastructure.messaging.outbox.dispatcher_main.build_write_engine"),
        patch("market_data.infrastructure.messaging.outbox.dispatcher_main.build_session_factory"),
        patch(
            "market_data.infrastructure.messaging.outbox.dispatcher_main.create_dispatcher",
            return_value=mock_dispatcher,
        ),
    ):
        process = DispatcherProcess(settings=settings)
        process.stop()

    mock_dispatcher.stop.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_main_run_delegates_to_dispatcher() -> None:
    """DispatcherProcess.run() awaits the underlying dispatcher's run()."""
    from market_data.infrastructure.messaging.outbox.dispatcher_main import DispatcherProcess

    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()

    # outbox_retention_seconds / ingestion_events_retention_days must be real
    # ints (0 = pruner disabled) — _build_retention_workers compares them
    # against 0, which raises on a bare MagicMock attribute.
    settings = MagicMock()
    settings.outbox_retention_seconds = 0
    settings.ingestion_events_retention_days = 0

    with (
        patch("market_data.infrastructure.messaging.outbox.dispatcher_main.build_write_engine"),
        patch("market_data.infrastructure.messaging.outbox.dispatcher_main.build_session_factory"),
        patch(
            "market_data.infrastructure.messaging.outbox.dispatcher_main.create_dispatcher",
            return_value=mock_dispatcher,
        ),
    ):
        process = DispatcherProcess(settings=settings)
        await process.run()

    mock_dispatcher.run.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_main_run_dispatcher_delegates_to_process() -> None:
    """_run_dispatcher() creates a DispatcherProcess and calls run()."""
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()

    with (
        patch("market_data.config.Settings", return_value=_mock_settings()),
        patch("market_data.infrastructure.messaging.outbox.dispatcher_main.build_write_engine"),
        patch("market_data.infrastructure.messaging.outbox.dispatcher_main.build_session_factory"),
        patch(
            "market_data.infrastructure.messaging.outbox.dispatcher_main.create_dispatcher",
            return_value=mock_dispatcher,
        ),
    ):
        from market_data.infrastructure.messaging.outbox.dispatcher_main import _run_dispatcher

        await _run_dispatcher()

    mock_dispatcher.run.assert_called_once()
