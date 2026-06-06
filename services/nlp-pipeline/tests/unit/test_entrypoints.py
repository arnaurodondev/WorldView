"""Unit tests for nlp-pipeline standalone consumer and dispatcher entry points.

Covers: article_consumer_main (two engines), watchlist_consumer_main,
        dispatcher_main (NLPPipelineOutboxDispatcher).

All tests use ``unittest.mock.patch`` to isolate infrastructure.
The pre-set ``asyncio.Event`` pattern is used so ``stop_event.wait()``
returns immediately and the entire cleanup path executes within the test.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

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
    s.kafka_consumer_group = "nlp-pipeline"
    s.kafka_watchlist_consumer_group = "nlp-pipeline-watchlist"
    s.topic_article_stored = "content.article.stored.v1"
    s.topic_watchlist_updated = "portfolio.watchlist.updated.v1"
    s.valkey_url = "redis://localhost:6379/0"
    s.valkey_watchlist_key = "watchlist:symbols"
    s.ollama_base_url = "http://ollama:11434"
    s.embedding_model_id = "nomic-embed-text"
    s.extraction_model_id = "mistral:7b"
    s.embedding_max_concurrent = 4
    s.gliner_base_url = ""  # empty → local adapter
    s.ner_model_id = "gliner-base"
    s.max_ollama_queue_depth = 20
    s.resume_ollama_queue_depth = 10
    s.storage_endpoint = "http://localhost:9000"
    s.storage_access_key = "key"
    s.storage_secret_key = "secret"  # noqa: S105
    # Empty string → DeepInfra branch skipped (tests cover lifecycle, not adapter wiring)
    s.extraction_api_key = SecretStr("")
    s.extraction_api_base_url = "http://api.deepinfra.com/v1/openai"
    s.extraction_api_model_id = "deepseek-ai/DeepSeek-V4-Flash"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# article_consumer_main — two-engine consumer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_article_consumer_main_two_engines_disposed() -> None:
    """Both nlp_engine.dispose() and intel_engine.dispose() called on exit.

    Guards against regression where only one engine is cleaned up
    (critical for NLP pipeline which owns two databases).
    """
    mock_nlp_engine = AsyncMock()
    mock_intel_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.intelligence_db.session._build_intelligence_factories",
            return_value=(mock_intel_engine, mock_intel_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("nlp_pipeline.infrastructure.valkey.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch("ml_clients.adapters.ollama_embedding.OllamaEmbeddingAdapter", return_value=MagicMock()),
        patch("ml_clients.adapters.ollama_extraction.OllamaExtractionAdapter", return_value=MagicMock()),
        patch("ml_clients.adapters.gliner_local.GLiNERLocalAdapter", return_value=MagicMock()),
        patch("nlp_pipeline.infrastructure.backpressure.controller.BackpressureController", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.ArticleProcessingConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main import main

        await main()

    # Both engines must be disposed — not just one
    mock_nlp_engine.dispose.assert_called_once()
    mock_intel_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_article_consumer_main_graceful_stop() -> None:
    """wait_for(30s) is used and valkey.close() called on graceful stop."""
    mock_nlp_engine = AsyncMock()
    mock_intel_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.intelligence_db.session._build_intelligence_factories",
            return_value=(mock_intel_engine, mock_intel_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("nlp_pipeline.infrastructure.valkey.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch("ml_clients.adapters.ollama_embedding.OllamaEmbeddingAdapter", return_value=MagicMock()),
        patch("ml_clients.adapters.ollama_extraction.OllamaExtractionAdapter", return_value=MagicMock()),
        patch("ml_clients.adapters.gliner_local.GLiNERLocalAdapter", return_value=MagicMock()),
        patch("nlp_pipeline.infrastructure.backpressure.controller.BackpressureController", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.ArticleProcessingConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_valkey.close.assert_called_once()


@pytest.mark.asyncio
async def test_article_consumer_main_stop_pre_set() -> None:
    """Consumer is started (create_task called) even with a pre-set stop event."""
    mock_nlp_engine = AsyncMock()
    mock_intel_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.intelligence_db.session._build_intelligence_factories",
            return_value=(mock_intel_engine, mock_intel_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("nlp_pipeline.infrastructure.valkey.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch("ml_clients.adapters.ollama_embedding.OllamaEmbeddingAdapter", return_value=MagicMock()),
        patch("ml_clients.adapters.ollama_extraction.OllamaExtractionAdapter", return_value=MagicMock()),
        patch("ml_clients.adapters.gliner_local.GLiNERLocalAdapter", return_value=MagicMock()),
        patch("nlp_pipeline.infrastructure.backpressure.controller.BackpressureController", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.ArticleProcessingConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main import main

        await main()

    # Consumer.run() is called via asyncio.create_task — always happens before wait()
    mock_consumer.run.assert_called_once()


# ---------------------------------------------------------------------------
# watchlist_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchlist_consumer_main_graceful_stop() -> None:
    """valkey.close() called on stop signal; consumer.stop() invoked."""
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("nlp_pipeline.infrastructure.valkey.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer.WatchlistEventConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer_main import main

        await main()

    mock_consumer.stop.assert_called_once()
    mock_valkey.close.assert_called_once()


@pytest.mark.asyncio
async def test_watchlist_consumer_main_stop_pre_set() -> None:
    """Consumer is created and run() called even when stop_event pre-set."""
    mock_valkey = AsyncMock()
    mock_consumer = MagicMock()
    mock_consumer.run = AsyncMock()
    mock_consumer.stop = MagicMock()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch("nlp_pipeline.infrastructure.valkey.watchlist_cache.WatchlistCache", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer.WatchlistEventConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer_main import main

        await main()

    mock_consumer.run.assert_called_once()


# ---------------------------------------------------------------------------
# dispatcher_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_main_cleanup() -> None:
    """nlp_engine.dispose() called on exit from dispatcher main()."""
    mock_nlp_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.NLPPipelineOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_nlp_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_dispatcher_main_stop() -> None:
    """dispatcher.stop() called when stop_event fires in dispatcher main()."""
    mock_nlp_engine = AsyncMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock()
    mock_dispatcher.stop = MagicMock()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.outbox.dispatcher.NLPPipelineOutboxDispatcher",
            return_value=mock_dispatcher,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.outbox.dispatcher_main import main

        await main()

    mock_dispatcher.stop.assert_called_once()


# ---------------------------------------------------------------------------
# price_impact_labelling_worker (entry point) — T-B-2-01
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_price_impact_worker_entrypoint_importable() -> None:
    """``from nlp_pipeline.workers.price_impact_labelling_worker import main`` imports without error."""
    from nlp_pipeline.workers.price_impact_labelling_worker import main

    assert callable(main)


@pytest.mark.asyncio
async def test_price_impact_worker_entrypoint_runs_and_stops() -> None:
    """Entry point runs to completion and disposes nlp_engine when stop is pre-set."""
    mock_nlp_engine = AsyncMock()
    mock_worker = MagicMock()
    mock_worker.run_forever = AsyncMock()

    mock_settings = _mock_settings(
        impact_normalisation_cap_pct=5.0,
        price_impact_cycle_seconds=14400,
        price_impact_min_age_hours=25,
        market_data_internal_url="http://market-data:8003",
    )

    with (
        patch("nlp_pipeline.config.Settings", return_value=mock_settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.http.market_data_client.MarketDataClient",
            return_value=MagicMock(),
        ),
        patch(
            "nlp_pipeline.infrastructure.workers.price_impact_labelling_worker.PriceImpactLabellingWorker",
            return_value=mock_worker,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.workers.price_impact_labelling_worker import main

        await main()

    mock_nlp_engine.dispose.assert_called_once()
    mock_worker.run_forever.assert_called_once()


# ---------------------------------------------------------------------------
# article_relevance_scoring_worker (entry point) — PRD-0026 Wave 5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relevance_scoring_worker_entrypoint_importable() -> None:
    """``from nlp_pipeline.workers.article_relevance_scoring_worker import main`` imports without error."""
    from nlp_pipeline.workers.article_relevance_scoring_worker import main

    assert callable(main)


@pytest.mark.asyncio
async def test_relevance_scoring_worker_entrypoint_runs_and_stops() -> None:
    """Entry point runs to completion and disposes nlp_engine when stop is pre-set."""
    mock_nlp_engine = AsyncMock()
    mock_worker = MagicMock()
    mock_worker.run_forever = AsyncMock()

    mock_settings = _mock_settings(
        relevance_scoring_ollama_url="http://ollama:11434",
        relevance_scoring_model="qwen3:0.6b",
        relevance_scoring_batch_size=50,
        relevance_scoring_timeout_seconds=30,
        relevance_scoring_cycle_seconds=1800,
    )

    with (
        patch("nlp_pipeline.config.Settings", return_value=mock_settings),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        # Avoid binding to METRICS_PORT (9100) — multiple worker-main tests
        # in the suite each call start_metrics_server; without this patch the
        # second test in the same CI process hits OSError EADDRINUSE.
        patch("nlp_pipeline.workers.article_relevance_scoring_worker.start_metrics_server", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.workers.article_relevance_scoring_worker.ArticleRelevanceScoringWorker",
            return_value=mock_worker,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.workers.article_relevance_scoring_worker import main

        await main()

    mock_nlp_engine.dispose.assert_called_once()
    mock_worker.run_forever.assert_called_once()
