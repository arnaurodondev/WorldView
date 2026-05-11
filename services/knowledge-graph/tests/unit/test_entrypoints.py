"""Unit tests for knowledge-graph standalone consumer and dispatcher entry points.

Covers: enriched_consumer_main, entity_consumer_main, fundamentals_consumer_main,
        instrument_consumer_main, dispatcher_main.

All tests use ``unittest.mock.patch`` to isolate infrastructure.
The pre-set ``asyncio.Event`` pattern is used so ``stop_event.wait()``
returns immediately and the entire cleanup path executes within the test.
"""

from __future__ import annotations

import asyncio
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
    s.kafka_consumer_group = "kg-service-group"
    s.kafka_topic_enriched = "nlp.article.enriched.v1"
    s.kafka_topic_entity_created = "entity.canonical.created.v1"
    s.kafka_topic_instrument_created = "market.instrument.created"
    s.kafka_topic_dataset_fetched = "market.dataset.fetched"
    s.kafka_topic_entity_dirtied = "entity.dirtied.v1"
    s.valkey_url = "redis://localhost:6379/0"
    s.ollama_base_url = "http://ollama:11434"
    s.embedding_model_id = "nomic-embed-text"
    s.relation_canonicalization_threshold = 0.85
    s.storage_endpoint = "http://localhost:9000"
    s.storage_access_key = "key"
    s.storage_secret_key = "secret"  # noqa: S105
    s.dispatcher_poll_interval_s = 1.0
    s.dispatcher_batch_size = 50
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# enriched_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enriched_consumer_uses_ollama_base_url() -> None:
    """OllamaEmbeddingAdapter is constructed with settings.ollama_base_url.

    Guards against BP-085 regression where the wrong URL was used.
    """
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("knowledge_graph.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "ml_clients.adapters.ollama_embedding.OllamaEmbeddingAdapter", return_value=MagicMock()
        ) as mock_embedding_cls,
        patch("confluent_kafka.Producer", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.EnrichedArticleConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main import main

        await main()

    # Verify ollama_base_url from settings was passed to the adapter
    call_kwargs = mock_embedding_cls.call_args
    assert call_kwargs is not None
    assert call_kwargs.kwargs.get("base_url") == settings.ollama_base_url or (
        call_kwargs.args and call_kwargs.args[0] == settings.ollama_base_url
    )


@pytest.mark.asyncio
async def test_enriched_consumer_graceful_stop() -> None:
    """valkey.close() and engine.dispose() called on graceful stop."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("knowledge_graph.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("ml_clients.adapters.ollama_embedding.OllamaEmbeddingAdapter", return_value=MagicMock()),
        patch("confluent_kafka.Producer", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.messaging.consumers.enriched_consumer.EnrichedArticleConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# entity_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_consumer_graceful_stop() -> None:
    """valkey.close() and engine.dispose() called on entity consumer stop."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("knowledge_graph.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "knowledge_graph.infrastructure.messaging.consumers.entity_consumer.EntityCreatedConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_valkey.close.assert_called_once()
    mock_engine.dispose.assert_called_once()


# ---------------------------------------------------------------------------
# fundamentals_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fundamentals_consumer_group_id_from_settings() -> None:
    """Consumer group_id uses f\"{settings.kafka_consumer_group}-fundamentals\"."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("knowledge_graph.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "knowledge_graph.infrastructure.llm.fallback_chain.FallbackChainClient",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.workers.definition_refresh.DefinitionRefreshWorker",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer.FundamentalsDescriptionConsumer",
            return_value=mock_consumer,
        ) as mock_consumer_cls,
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer_main import main

        await main()

    # Verify FundamentalsDescriptionConsumer was constructed with the correct group_id
    call_kwargs = mock_consumer_cls.call_args
    assert call_kwargs is not None
    config_arg = call_kwargs.kwargs.get("config") or (call_kwargs.args[0] if call_kwargs.args else None)
    assert config_arg is not None
    assert config_arg.group_id == f"{settings.kafka_consumer_group}-fundamentals"
    mock_consumer.run.assert_called_once()


# ---------------------------------------------------------------------------
# instrument_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_instrument_consumer_group_id_from_settings() -> None:
    """Consumer group_id uses f\"{settings.kafka_consumer_group}-instrument\"."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()
    settings = _mock_settings()

    with (
        patch("knowledge_graph.config.Settings", return_value=settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "knowledge_graph.infrastructure.llm.fallback_chain.FallbackChainClient",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.workers.definition_refresh.DefinitionRefreshWorker",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.messaging.consumers.instrument_consumer.InstrumentEntityConsumer",
            return_value=mock_consumer,
        ) as mock_instrument_cls,
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.instrument_consumer_main import main

        await main()

    # Verify InstrumentEntityConsumer was constructed with the correct group_id
    call_kwargs = mock_instrument_cls.call_args
    assert call_kwargs is not None
    config_arg = call_kwargs.kwargs.get("config") or (call_kwargs.args[0] if call_kwargs.args else None)
    assert config_arg is not None
    assert config_arg.group_id == f"{settings.kafka_consumer_group}-instrument"
    mock_consumer.run.assert_called_once()


@pytest.mark.asyncio
async def test_any_consumer_stop_pre_set() -> None:
    """With a pre-set stop event, entity consumer exits quickly after cleanup."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("knowledge_graph.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "knowledge_graph.infrastructure.messaging.consumers.entity_consumer.EntityCreatedConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main import main

        await main()

    # Verify cleanup path executed
    mock_engine.dispose.assert_called_once()
    mock_valkey.close.assert_called_once()


# ---------------------------------------------------------------------------
# dispatcher_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_main_cleanup() -> None:
    """engine.dispose() called on exit from knowledge-graph dispatcher main()."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.stop = MagicMock()

    # Dispatcher uses run_forever() (not run()) — supervised restart pattern
    async def _fake_run_forever() -> None:
        return  # exits immediately

    mock_dispatcher.run_forever = _fake_run_forever

    with (
        patch("knowledge_graph.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("confluent_kafka.Producer", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_main_stop() -> None:
    """dispatcher.stop() called when stop_event fires in dispatcher main()."""
    mock_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.stop = MagicMock()

    async def _fake_run_forever() -> None:
        return

    mock_dispatcher.run_forever = _fake_run_forever

    with (
        patch("knowledge_graph.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.intelligence_db.session._build_factories",
            return_value=(mock_engine, mock_engine, MagicMock(), MagicMock()),
        ),
        patch("confluent_kafka.Producer", return_value=MagicMock()),
        patch(
            "knowledge_graph.infrastructure.messaging.outbox.dispatcher.OutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_dispatcher.stop.assert_called_once()
