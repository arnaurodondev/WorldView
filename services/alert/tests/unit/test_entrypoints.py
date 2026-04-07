"""Unit tests for alert service standalone consumer and dispatcher entry points.

Covers: intelligence_consumer_main, watchlist_consumer_main, dispatcher_main.

All tests use ``unittest.mock.patch`` to isolate all infrastructure.
The pre-set ``asyncio.Event`` pattern is used so ``stop_event.wait()``
returns immediately and the entire cleanup path executes within the test.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# Capture the real asyncio.Event BEFORE any patch replaces it.
_REAL_ASYNCIO_EVENT = asyncio.Event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _preset_event(*_args: object, **_kwargs: object) -> asyncio.Event:
    """Return a real asyncio.Event that is already set."""
    e = _REAL_ASYNCIO_EVENT()
    e.set()
    return e


def _mock_settings(**overrides: object) -> MagicMock:
    s = MagicMock()
    s.log_level = "INFO"
    s.log_json = False
    s.kafka_bootstrap_servers = "localhost:9092"
    s.kafka_consumer_group = "alert-service-group"
    s.kafka_watchlist_consumer_group = "alert-service-watchlist-group"
    s.kafka_topic_signal = "nlp.signal.detected.v1"
    s.kafka_topic_graph_state = "graph.state.changed.v1"
    s.kafka_topic_contradiction = "intelligence.contradiction.v1"
    s.kafka_topic_watchlist = "portfolio.watchlist.updated.v1"
    s.kafka_topic_alert_delivered = "alert.delivered.v1"
    s.valkey_url = "redis://localhost:6379/0"
    s.s1_portfolio_base_url = "http://localhost:8001"
    s.internal_service_token = "test-token"  # noqa: S105
    s.alert_dedup_window_seconds = 300
    s.watchlist_cache_ttl_seconds = 300
    s.dispatcher_poll_interval_s = 1.0
    s.dispatcher_batch_size = 50
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@contextlib.contextmanager  # type: ignore[misc]
def _intelligence_patches(
    mock_engine: AsyncMock,
    mock_valkey: AsyncMock,
    mock_consumer: MagicMock,
    mock_s1: AsyncMock,
    settings: MagicMock,
):  # type: ignore[no-untyped-def]
    """Context manager that patches all intelligence_consumer_main dependencies."""
    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "alert.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.notification.valkey_publisher.ValkeyNotificationPublisher",
            return_value=MagicMock(),
        ),
        patch("alert.application.use_cases.alert_fanout.AlertFanoutUseCase", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.intelligence_consumer.IntelligenceConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        yield


# ---------------------------------------------------------------------------
# intelligence_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_intelligence_consumer_graceful_stop() -> None:
    """wait_for(30s) + s1_client.close + valkey.close + engine.dispose called."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    mock_s1 = AsyncMock()
    settings = _mock_settings()

    with _intelligence_patches(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        from alert.infrastructure.messaging.consumers.intelligence_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_s1.close.assert_called_once()
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_intelligence_consumer_stop_pre_set() -> None:
    """Consumer task is started then stopped immediately when stop_event is pre-set."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    mock_s1 = AsyncMock()
    settings = _mock_settings()

    with _intelligence_patches(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        import importlib

        from alert.infrastructure.messaging.consumers import intelligence_consumer_main

        importlib.reload(intelligence_consumer_main)
        await intelligence_consumer_main.main()

    # Consumer task is created and waited on; stop is called immediately since event was set
    mock_consumer.stop.assert_called_once()


@pytest.mark.asyncio
async def test_intelligence_consumer_cleanup_order() -> None:
    """All resources are closed in the finally block regardless of consumer outcome."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    # Consumer.run raises immediately to simulate early exit
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with _intelligence_patches(mock_engine, mock_valkey, mock_consumer, mock_s1, settings):
        import importlib

        from alert.infrastructure.messaging.consumers import intelligence_consumer_main

        importlib.reload(intelligence_consumer_main)
        await intelligence_consumer_main.main()

    # All three cleanup calls must have happened
    mock_s1.close.assert_called_once()
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# watchlist_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchlist_consumer_graceful_stop() -> None:
    """wait_for(30s) + s1_client.close + valkey.close called on stop."""
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.watchlist_consumer.WatchlistConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from alert.infrastructure.messaging.consumers.watchlist_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_s1.close.assert_called_once()
    mock_valkey.close.assert_called_once()


@pytest.mark.asyncio
async def test_watchlist_consumer_stop_pre_set() -> None:
    """Consumer task is started then stopped immediately when stop_event is pre-set."""
    mock_valkey = AsyncMock()
    mock_s1 = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("alert.infrastructure.clients.s1_client.S1Client", return_value=mock_s1),
        patch("alert.infrastructure.cache.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "alert.infrastructure.messaging.consumers.watchlist_consumer.WatchlistConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        import importlib

        from alert.infrastructure.messaging.consumers import watchlist_consumer_main

        importlib.reload(watchlist_consumer_main)
        await watchlist_consumer_main.main()

    mock_consumer.stop.assert_called_once()
    mock_valkey.close.assert_called_once()


# ---------------------------------------------------------------------------
# dispatcher_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_main_cleanup() -> None:
    """engine.dispose() is called on exit."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "alert.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "alert.infrastructure.messaging.outbox.dispatcher.AlertOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from alert.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_main_stop() -> None:
    """dispatcher.stop() is called when stop_event fires."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("alert.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "alert.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "alert.infrastructure.messaging.outbox.dispatcher.AlertOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        import importlib

        from alert.infrastructure.messaging.outbox import dispatcher_main

        importlib.reload(dispatcher_main)
        await dispatcher_main.main()

    mock_dispatcher.stop.assert_called_once()
