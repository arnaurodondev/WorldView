"""Unit tests for knowledge-graph standalone consumer and dispatcher entry points.

Covers: enriched_consumer_main, entity_consumer_main, fundamentals_consumer_main,
        instrument_consumer_main, dispatcher_main.

All tests use ``unittest.mock.patch`` to isolate infrastructure.
The pre-set ``asyncio.Event`` pattern is used so ``stop_event.wait()``
returns immediately and the entire cleanup path executes within the test.
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


def _make_supervised_consumer() -> MagicMock:
    """Build a MagicMock consumer that cooperates with ``run_consumer_supervised``.

    BP-704: the consumer mains now drive the run loop through
    ``run_consumer_supervised``, which races ``consumer.run()`` against the
    stop event. A real consumer's ``run()`` blocks until ``stop()`` is called;
    an ``AsyncMock`` that returns instantly would instead be treated as an
    unexpected exit (``ConsumerExited``). So we model ``run()`` as a coroutine
    that waits on a gate which ``stop()`` releases — exactly like the live
    consumer's poll loop. With a pre-set stop_event the supervisor calls
    ``stop()`` → the gate opens → ``run()`` returns → clean shutdown (exit 0).
    """
    mock_consumer = MagicMock()
    run_gate = _REAL_ASYNCIO_EVENT()

    async def _run_until_stopped() -> None:
        await run_gate.wait()

    mock_consumer.run = _run_until_stopped
    mock_consumer.stop = MagicMock(side_effect=run_gate.set)
    return mock_consumer


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


@pytest.mark.asyncio()
async def test_enriched_consumer_uses_ollama_base_url() -> None:
    """OllamaEmbeddingAdapter is constructed with settings.ollama_base_url.

    Guards against BP-085 regression where the wrong URL was used.
    """
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
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
            "ml_clients.adapters.ollama_embedding.OllamaEmbeddingAdapter",
            return_value=MagicMock(),
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


@pytest.mark.asyncio()
async def test_enriched_consumer_graceful_stop() -> None:
    """valkey.close() and engine.dispose() called on graceful stop."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()

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


@pytest.mark.asyncio()
async def test_entity_consumer_graceful_stop() -> None:
    """valkey.close() and engine.dispose() called on entity consumer stop."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
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


@pytest.mark.asyncio()
async def test_fundamentals_consumer_group_id_from_settings() -> None:
    """Consumer group_id uses f\"{settings.kafka_consumer_group}-fundamentals\"."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
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
    # BP-704: run() is supervised; a clean shutdown calls stop() exactly once.
    mock_consumer.stop.assert_called_once()


# ---------------------------------------------------------------------------
# instrument_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_instrument_consumer_group_id_from_settings() -> None:
    """Consumer group_id uses f\"{settings.kafka_consumer_group}-instrument\"."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
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
    # BP-704: run() is supervised; a clean shutdown calls stop() exactly once.
    mock_consumer.stop.assert_called_once()


@pytest.mark.asyncio()
async def test_any_consumer_stop_pre_set() -> None:
    """With a pre-set stop event, entity consumer exits quickly after cleanup."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()

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


@pytest.mark.asyncio()
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


@pytest.mark.asyncio()
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


# ---------------------------------------------------------------------------
# F-005 / BP-704: stall-aware /healthz wiring on the metrics port
#
# Every standalone consumer main MUST call start_metrics_server (so /healthz
# exists on port 9100, which the Docker healthcheck hits) AND pass a liveness
# probe so /healthz flips to 503 when the poll loop wedges or run() dies.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_entity_consumer_wires_liveness_probe() -> None:
    """entity_consumer_main passes a liveness_probe to start_metrics_server.

    Guards F-005 (metrics server present) + BP-704 (stall-aware /healthz).
    """
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    mock_probe = MagicMock()
    module = "knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main"

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
        patch(f"{module}.make_liveness_probe", return_value=mock_probe) as mock_make_probe,
        patch(f"{module}.start_metrics_server", return_value=AsyncMock()) as mock_metrics,
        # Patch the supervisor so the test does not depend on real run() internals.
        patch("messaging.kafka.consumer.supervisor.run_consumer_supervised", new=AsyncMock()),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main import main

        await main()

    mock_make_probe.assert_called_once()
    mock_metrics.assert_called_once()
    assert mock_metrics.call_args.kwargs.get("liveness_probe") is mock_probe
    # The probe must be bound to the consumer so /healthz reflects poll progress.
    mock_probe.bind.assert_called_once_with(mock_consumer)


@pytest.mark.asyncio()
async def test_earnings_calendar_consumer_wires_liveness_probe() -> None:
    """earnings_calendar dataset consumer main wires a liveness probe (F-005)."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    mock_probe = MagicMock()
    module = "knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer_main"

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
            "knowledge_graph.infrastructure.messaging.consumers."
            "earnings_calendar_dataset_consumer.EarningsCalendarDatasetConsumer",
            return_value=mock_consumer,
        ),
        patch(f"{module}.make_liveness_probe", return_value=mock_probe) as mock_make_probe,
        patch(f"{module}.start_metrics_server", return_value=AsyncMock()) as mock_metrics,
        patch("messaging.kafka.consumer.supervisor.run_consumer_supervised", new=AsyncMock()),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer_main import (
            main,
        )

        await main()

    mock_make_probe.assert_called_once()
    mock_metrics.assert_called_once()
    assert mock_metrics.call_args.kwargs.get("liveness_probe") is mock_probe
    mock_probe.bind.assert_called_once_with(mock_consumer)


@pytest.mark.asyncio()
async def test_prediction_enriched_consumer_wires_liveness_probe() -> None:
    """PredictionEnrichedConsumer main wires a liveness probe (PLAN-0056 Wave C2)."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    mock_probe = MagicMock()
    module = "knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer_main"

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
            "knowledge_graph.infrastructure.messaging.consumers."
            "prediction_enriched_consumer.PredictionEnrichedConsumer",
            return_value=mock_consumer,
        ),
        patch(f"{module}.make_liveness_probe", return_value=mock_probe) as mock_make_probe,
        patch(f"{module}.start_metrics_server", return_value=AsyncMock()) as mock_metrics,
        patch("messaging.kafka.consumer.supervisor.run_consumer_supervised", new=AsyncMock()),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer_main import (
            main,
        )

        await main()

    mock_make_probe.assert_called_once()
    mock_metrics.assert_called_once()
    assert mock_metrics.call_args.kwargs.get("liveness_probe") is mock_probe
    mock_probe.bind.assert_called_once_with(mock_consumer)


@pytest.mark.asyncio()
async def test_narrative_refresh_consumer_starts_metrics_with_probe() -> None:
    """narrative_refresh consumer NOW exposes /healthz (was MISSING — F-005 fix).

    Before this fix the main never called start_metrics_server, so the Docker
    healthcheck on :9100/healthz refused connections and the container was
    permanently UNHEALTHY despite working.
    """
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    mock_probe = MagicMock()
    module = "knowledge_graph.infrastructure.messaging.consumers.narrative_refresh_consumer_main"

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
        patch(
            "knowledge_graph.infrastructure.llm.fallback_chain.FallbackChainClient",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.workers.narrative_refresh.NarrativeRefreshKafkaConsumer",
            return_value=mock_consumer,
        ),
        patch(f"{module}.make_liveness_probe", return_value=mock_probe) as mock_make_probe,
        patch(f"{module}.start_metrics_server", return_value=AsyncMock()) as mock_metrics,
        patch("messaging.kafka.consumer.supervisor.run_consumer_supervised", new=AsyncMock()),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.narrative_refresh_consumer_main import main

        await main()

    mock_make_probe.assert_called_once()
    mock_metrics.assert_called_once()
    assert mock_metrics.call_args.kwargs.get("liveness_probe") is mock_probe
    mock_probe.bind.assert_called_once_with(mock_consumer)


@pytest.mark.asyncio()
async def test_structured_enrichment_consumer_starts_metrics_with_probe() -> None:
    """structured_enrichment consumer NOW exposes /healthz (was MISSING — F-005)."""
    mock_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _make_supervised_consumer()
    mock_probe = MagicMock()
    # The structured enrichment main builds an entity.dirtied producer returned
    # as a (direct, raw) tuple; raw must support flush() in the finally block.
    mock_raw_producer = MagicMock()
    module = "knowledge_graph.infrastructure.messaging.consumers.structured_enrichment_consumer_main"

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
            "knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter.EntityEnrichmentAdapter",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.scheduler.scheduler.build_market_data_signer",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.http.market_data_client.MarketDataClient",
            return_value=AsyncMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.scheduler.scheduler._build_description_client",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.scheduler.scheduler._build_entity_dirtied_producer",
            return_value=(MagicMock(), mock_raw_producer),
        ),
        patch(
            "knowledge_graph.application.use_cases.structured_enrichment.StructuredEnrichmentUseCase",
            return_value=MagicMock(),
        ),
        patch(
            "knowledge_graph.infrastructure.messaging.consumers."
            "structured_enrichment_consumer.StructuredEnrichmentConsumer",
            return_value=mock_consumer,
        ),
        patch(f"{module}.make_liveness_probe", return_value=mock_probe) as mock_make_probe,
        patch(f"{module}.start_metrics_server", return_value=AsyncMock()) as mock_metrics,
        patch("messaging.kafka.consumer.supervisor.run_consumer_supervised", new=AsyncMock()),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from knowledge_graph.infrastructure.messaging.consumers.structured_enrichment_consumer_main import main

        await main()

    mock_make_probe.assert_called_once()
    mock_metrics.assert_called_once()
    assert mock_metrics.call_args.kwargs.get("liveness_probe") is mock_probe
    mock_probe.bind.assert_called_once_with(mock_consumer)
