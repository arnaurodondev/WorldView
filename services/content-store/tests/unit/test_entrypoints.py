"""Unit tests for content-store standalone consumer and dispatcher entry points.

Covers: article_consumer_main, dispatcher_main.

All tests use ``unittest.mock.patch`` to isolate infrastructure — no real DB,
Kafka, MinIO, or Valkey connections are made.

The flat ``main()`` coroutines are exercised by patching ``asyncio.Event`` to
return a pre-set event, causing ``stop_event.wait()`` to return immediately and
the entire cleanup path to execute within the test.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit

# Capture the real asyncio.Event class BEFORE any test patch replaces it.
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
    s.minio_endpoint = "localhost:9000"
    s.minio_secure = False
    s.minio_access_key = "key"
    s.minio_secret_key = "secret"  # noqa: S105
    s.valkey_url = "redis://localhost:6379/0"
    s.lsh_num_bands = 10
    s.lsh_rows_per_band = 5
    s.minhash_num_perm = 128
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# article_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_article_consumer_main_stop_before_run() -> None:
    """Pre-set stop_event causes article main() to exit after starting consumer."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("content_store.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("content_store.infrastructure.valkey.lsh_client.ValkeyLSHClient", return_value=MagicMock()),
        patch("content_store.infrastructure.valkey.lsh_client.LSHConfig", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumer",
            return_value=mock_consumer,
        ),
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumerConfig",
            return_value=MagicMock(),
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from content_store.infrastructure.messaging.consumers.article_consumer_main import main

        await main()

    mock_consumer.run.assert_called_once()
    mock_consumer.stop.assert_called_once()


@pytest.mark.asyncio
async def test_article_consumer_main_graceful_stop() -> None:
    """valkey.close() and engine.dispose() both called on graceful stop."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("content_store.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("content_store.infrastructure.valkey.lsh_client.ValkeyLSHClient", return_value=MagicMock()),
        patch("content_store.infrastructure.valkey.lsh_client.LSHConfig", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumer",
            return_value=mock_consumer,
        ),
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumerConfig",
            return_value=MagicMock(),
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from content_store.infrastructure.messaging.consumers.article_consumer_main import main

        await main()

    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_article_consumer_main_timeout_cancels() -> None:
    """When wait_for times out, cleanup still runs."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.stop = MagicMock()

    async def run_forever() -> None:
        await asyncio.sleep(9999)

    mock_consumer.run = run_forever

    with (
        patch("content_store.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("content_store.infrastructure.valkey.lsh_client.ValkeyLSHClient", return_value=MagicMock()),
        patch("content_store.infrastructure.valkey.lsh_client.LSHConfig", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumer",
            return_value=mock_consumer,
        ),
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumerConfig",
            return_value=MagicMock(),
        ),
        patch("asyncio.Event", side_effect=_preset_event),
        patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
    ):
        from content_store.infrastructure.messaging.consumers.article_consumer_main import main

        await main()

    # Cleanup still runs after timeout
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_article_consumer_main_lsh_client_used() -> None:
    """LSHConfig is built from settings and ValkeyLSHClient is constructed."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    mock_lsh_client = MagicMock()

    settings = _mock_settings()

    with (
        patch("content_store.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("storage.factory.build_object_storage", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "content_store.infrastructure.valkey.lsh_client.LSHConfig", return_value=MagicMock()
        ) as mock_lsh_config_cls,
        patch(
            "content_store.infrastructure.valkey.lsh_client.ValkeyLSHClient", return_value=mock_lsh_client
        ) as mock_lsh_client_cls,
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumer",
            return_value=mock_consumer,
        ),
        patch(
            "content_store.infrastructure.messaging.consumers.article_consumer.ArticleConsumerConfig",
            return_value=MagicMock(),
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from content_store.infrastructure.messaging.consumers.article_consumer_main import main

        await main()

    # LSH config built from settings fields
    mock_lsh_config_cls.assert_called_once_with(
        num_bands=settings.lsh_num_bands,
        rows_per_band=settings.lsh_rows_per_band,
        num_perm=settings.minhash_num_perm,
    )
    # ValkeyLSHClient constructed with valkey + lsh_config
    mock_lsh_client_cls.assert_called_once()


# ---------------------------------------------------------------------------
# dispatcher_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_main_stop_delegates() -> None:
    """dispatcher.stop() is called when stop_event fires in main()."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()

    with (
        patch("content_store.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "content_store.infrastructure.messaging.outbox.dispatcher.ContentStoreOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from content_store.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_dispatcher.stop.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_main_cleanup() -> None:
    """engine.dispose() called on exit from dispatcher main()."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()

    with (
        patch("content_store.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "content_store.infrastructure.db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "content_store.infrastructure.messaging.outbox.dispatcher.ContentStoreOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from content_store.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_engine.dispose.assert_called_once()
