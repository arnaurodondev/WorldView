"""Unit tests for nlp-pipeline standalone consumer and dispatcher entry points.

Covers: article_consumer_main (two engines), watchlist_consumer_main,
        dispatcher_main (NLPPipelineOutboxDispatcher).

All tests use ``unittest.mock.patch`` to isolate infrastructure.
The pre-set ``asyncio.Event`` pattern is used so ``stop_event.wait()``
returns immediately and the entire cleanup path executes within the test.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

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


def _gated_consumer() -> MagicMock:
    """Build a consumer mock whose run() blocks until stop() is called.

    BP-704: the consumer mains now drive run() through ``run_consumer_supervised``,
    which RACES run() against the stop event (``asyncio.wait(FIRST_COMPLETED)``).
    A naive instantly-returning ``AsyncMock`` run() would non-deterministically
    win that race and be treated as an *unexpected* run() exit → ``ConsumerExited``
    → ``sys.exit(1)``.  A healthy consumer's run() only returns AFTER stop() is
    signalled, so we model that contract here: run() awaits an internal event that
    stop() sets.  The supervised-shutdown invariant we then assert is
    ``consumer.stop()`` was called (NOT ``run`` returned instantly).
    """
    consumer = MagicMock()
    _stopped = asyncio.Event()

    async def _run() -> None:
        await _stopped.wait()

    def _stop() -> None:
        _stopped.set()

    consumer.run = MagicMock(side_effect=_run)
    consumer.stop = MagicMock(side_effect=_stop)
    return consumer


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
    # Task #14: per-replica article concurrency (sizes the extraction semaphore).
    s.article_consumer_concurrency = 16
    s.deepinfra_max_connections = 64
    s.deepinfra_max_keepalive = 32
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
    mock_consumer = _gated_consumer()

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
    """valkey.close() called on graceful (supervised) stop."""
    mock_nlp_engine = AsyncMock()
    mock_intel_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

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
    """Supervised shutdown invokes consumer.stop() when stop event is pre-set."""
    mock_nlp_engine = AsyncMock()
    mock_intel_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

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

    # BP-704 supervised-shutdown invariant: run() is driven by the supervisor and
    # a pre-set stop event drains it via consumer.stop() (the correct shutdown path).
    mock_consumer.stop.assert_called_once()


# ---------------------------------------------------------------------------
# watchlist_consumer_main
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_watchlist_consumer_main_graceful_stop() -> None:
    """valkey.close() called on stop signal; consumer.stop() invoked."""
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

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
    """Supervised shutdown invokes consumer.stop() when stop_event is pre-set."""
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

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

    # BP-704 supervised-shutdown invariant: a pre-set stop event drains run()
    # via consumer.stop() rather than being treated as an unexpected exit.
    mock_consumer.stop.assert_called_once()


# ---------------------------------------------------------------------------
# BP-704 / F-005: stall-aware /healthz — every Kafka consumer main must pass a
# liveness_probe to start_metrics_server so /healthz turns 503 when the poll
# loop wedges or run() dies.  We patch each module's bound ``start_metrics_server``
# name and assert it was called with a non-None ``liveness_probe`` kwarg.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_article_consumer_main_wires_liveness_probe() -> None:
    """article_consumer_main passes a liveness_probe to start_metrics_server."""
    mock_nlp_engine = AsyncMock()
    mock_intel_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main.start_metrics_server",
        ) as mock_start,
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

    mock_start.assert_called_once()
    assert mock_start.call_args.kwargs["liveness_probe"] is not None


@pytest.mark.asyncio
async def test_watchlist_consumer_main_wires_liveness_probe() -> None:
    """watchlist_consumer_main passes a liveness_probe to start_metrics_server."""
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer_main.start_metrics_server",
        ) as mock_start,
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

    mock_start.assert_called_once()
    assert mock_start.call_args.kwargs["liveness_probe"] is not None


@pytest.mark.asyncio
async def test_document_deletion_consumer_main_wires_liveness_probe() -> None:
    """document_deletion_consumer_main passes a liveness_probe to start_metrics_server."""
    mock_nlp_engine = AsyncMock()
    mock_valkey = AsyncMock()
    mock_consumer = _gated_consumer()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.document_deletion_consumer_main.start_metrics_server",
        ) as mock_start,
        patch(
            "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
            return_value=(mock_nlp_engine, mock_nlp_engine, MagicMock(), MagicMock()),
        ),
        patch("messaging.valkey.create_valkey_client_from_url", return_value=mock_valkey),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.document_deletion_consumer.DocumentDeletionConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.consumers.document_deletion_consumer_main import main

        await main()

    mock_start.assert_called_once()
    assert mock_start.call_args.kwargs["liveness_probe"] is not None


@pytest.mark.asyncio
async def test_entity_refresh_consumer_main_wires_liveness_probe() -> None:
    """entity_refresh_consumer_main passes a liveness_probe to start_metrics_server."""
    mock_intel_engine = AsyncMock()
    mock_consumer = _gated_consumer()

    with (
        patch("nlp_pipeline.config.Settings", return_value=_mock_settings()),
        patch("observability.configure_logging"),
        patch("observability.get_logger", return_value=MagicMock()),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.entity_refresh_consumer_main.start_metrics_server",
        ) as mock_start,
        patch(
            "nlp_pipeline.infrastructure.intelligence_db.session._build_intelligence_factories",
            return_value=(mock_intel_engine, mock_intel_engine, MagicMock(), MagicMock()),
        ),
        patch(
            "nlp_pipeline.infrastructure.messaging.consumers.entity_refresh_consumer.EntityRefreshConsumer",
            return_value=mock_consumer,
        ),
        patch("asyncio.Event", side_effect=_preset_event),
    ):
        from nlp_pipeline.infrastructure.messaging.consumers.entity_refresh_consumer_main import main

        await main()

    mock_start.assert_called_once()
    assert mock_start.call_args.kwargs["liveness_probe"] is not None


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


# ---------------------------------------------------------------------------
# Settings completeness — BP-590 regression guard
# ---------------------------------------------------------------------------
#
# entity_refresh_consumer_main reads ``settings.kafka_entity_refresh_consumer_group``
# and ``settings.topic_entity_refresh``.  Both fields were silently removed from
# the real ``Settings`` class in a config.py merge resolution, crash-looping the
# entity-refresh consumer on ``AttributeError`` at startup.  The mock-based
# entrypoint tests above could not catch this because a ``MagicMock`` settings
# fabricates any attribute on access.  This test instantiates the REAL Settings
# class so a future merge that drops these fields fails here instead of in prod.


def test_entity_refresh_consumer_settings_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Settings class exposes the fields entity_refresh_consumer_main reads."""
    # Only database_url + intelligence_database_url have no defaults (DEF-027);
    # supply them so Settings() validates, then assert the consumer fields exist.
    monkeypatch.setenv("NLP_PIPELINE_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/nlp_db")
    monkeypatch.setenv(
        "NLP_PIPELINE_INTELLIGENCE_DATABASE_URL",
        "postgresql+asyncpg://u:p@localhost/intelligence_db",
    )

    from nlp_pipeline.config import Settings

    settings = Settings()  # type: ignore[call-arg]

    assert settings.kafka_entity_refresh_consumer_group == "nlp-entity-refresh-group"
    assert settings.topic_entity_refresh == "entity.refresh.v1"


def test_message_processing_timeout_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-message watchdog defaults to 900s and is env-overridable.

    Raised 300 -> 450 -> 700, then 700 -> 900 for Task #5 (2026-06-16): the 235B
    deep tier is latency-bound (p95=179s), so the extraction per-attempt cap is
    raised 90 -> 300s.  Worst case a window spends primary(320) + fallback(320),
    plus NER(~160) and writes, so 900s keeps the resilience from itself tripping
    the watchdog (see config.py budget arithmetic).
    """
    monkeypatch.setenv("NLP_PIPELINE_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/nlp_db")
    monkeypatch.setenv(
        "NLP_PIPELINE_INTELLIGENCE_DATABASE_URL",
        "postgresql+asyncpg://u:p@localhost/intelligence_db",
    )
    # Defend against env leakage from sibling tests sharing the os.environ (the full
    # suite runs in one process): ensure the override is unset before the default check.
    monkeypatch.delenv("NLP_PIPELINE_MESSAGE_PROCESSING_TIMEOUT_S", raising=False)

    from nlp_pipeline.config import Settings

    assert Settings().message_processing_timeout_s == 900  # type: ignore[call-arg]

    monkeypatch.setenv("NLP_PIPELINE_MESSAGE_PROCESSING_TIMEOUT_S", "600")
    assert Settings().message_processing_timeout_s == 600  # type: ignore[call-arg]


def test_extraction_timeout_budget_defaults_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task #5: extraction per-attempt cap / attempts / budget are config-driven.

    The 90s "wall-clock timeout" came from the ml-clients module-level ML_CLIENTS_*
    env default, which the NLP container never set.  These NLP_PIPELINE_* knobs are
    now the authoritative source and are passed explicitly to the adapter, so the
    effective cap is 300s (p95=179s completes on attempt 1) regardless of ML_CLIENTS_*.
    """
    monkeypatch.setenv("NLP_PIPELINE_DATABASE_URL", "postgresql+asyncpg://u:p@localhost/nlp_db")
    monkeypatch.setenv(
        "NLP_PIPELINE_INTELLIGENCE_DATABASE_URL",
        "postgresql+asyncpg://u:p@localhost/intelligence_db",
    )
    for var in (
        "NLP_PIPELINE_EXTRACTION_TIMEOUT_S",
        "NLP_PIPELINE_EXTRACTION_MAX_ATTEMPTS",
        "NLP_PIPELINE_EXTRACTION_TOTAL_BUDGET_S",
    ):
        monkeypatch.delenv(var, raising=False)

    from nlp_pipeline.config import Settings

    s = Settings()  # type: ignore[call-arg]
    assert s.extraction_timeout_s == 300.0
    assert s.extraction_max_attempts == 2
    assert s.extraction_total_budget_s == 320.0

    monkeypatch.setenv("NLP_PIPELINE_EXTRACTION_TIMEOUT_S", "250")
    monkeypatch.setenv("NLP_PIPELINE_EXTRACTION_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("NLP_PIPELINE_EXTRACTION_TOTAL_BUDGET_S", "500")
    s2 = Settings()  # type: ignore[call-arg]
    assert s2.extraction_timeout_s == 250.0
    assert s2.extraction_max_attempts == 3
    assert s2.extraction_total_budget_s == 500.0


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
