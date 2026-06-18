"""BUG #35 — title recovery wiring in ``ArticleProcessingConsumer.process_message``.

sec_edgar / newsapi events carry no ``title``.  When that happens the consumer
must call ``extract_title_from_silver`` and forward the recovered title to
``_run_pipeline`` (so it reaches ``chunks.title_denorm``) and to
``_write_source_metadata`` (so ``document_source_metadata.title`` is populated).
When the event already has a title, the silver lookup must NOT run.

These exercise ``process_message`` directly with ``_run_pipeline`` patched out,
mirroring ``test_article_consumer_legacy_tenant`` (no DB / Kafka / MinIO).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.unit

_CONSUMER_NS = "nlp_pipeline.infrastructure.messaging.consumers.article_consumer"


# ── Helpers (kept local; mirror test_article_consumer_legacy_tenant) ──────────


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.silver_bucket = "worldview-silver"
    s.min_word_count = 50
    return s


def _session_factory() -> MagicMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock()
    factory.return_value = cm
    return factory


def _make_consumer() -> ArticleProcessingConsumer:
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["content.article.stored.v1"],
    )
    return ArticleProcessingConsumer(
        config=config,
        settings=_make_settings(),
        nlp_session_factory=_session_factory(),
        intelligence_session_factory=_session_factory(),
        storage=MagicMock(),
        watchlist_cache=MagicMock(),
        ner_client=MagicMock(),
        embedding_client=MagicMock(),
        extraction_client=MagicMock(),
        backpressure=MagicMock(),
    )


def _titleless_payload(doc_id: uuid.UUID, source_type: str = "newsapi") -> dict[str, object]:
    """A sec_edgar/newsapi event shape with NO ``title`` field."""
    return {
        "doc_id": str(doc_id),
        "minio_silver_key": f"content-store/canonical/{doc_id}/body.json",
        "source_type": source_type,
        "is_backfill": False,
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_titleless_event_recovers_title_from_silver() -> None:
    """BUG #35: no event title → recovered title flows to pipeline + metadata."""
    consumer = _make_consumer()
    doc_id = uuid.uuid4()

    with (
        patch(f"{_CONSUMER_NS}.RoutingDecisionRepository") as routing_repo_cls,
        patch.object(consumer, "_run_pipeline", new=AsyncMock()) as run_pipeline_mock,
        patch.object(consumer, "_write_source_metadata", new=AsyncMock()) as write_meta_mock,
        patch(f"{_CONSUMER_NS}.extract_url_from_silver", new=AsyncMock(return_value=None)),
        patch(
            f"{_CONSUMER_NS}.extract_title_from_silver",
            new=AsyncMock(return_value="Recovered headline"),
        ) as title_mock,
    ):
        routing_repo_cls.return_value.get_by_doc = AsyncMock(return_value=None)

        await consumer.process_message(key=None, value=_titleless_payload(doc_id), headers={})

    title_mock.assert_awaited_once()
    assert run_pipeline_mock.await_args.kwargs["doc_title"] == "Recovered headline"
    assert write_meta_mock.await_args.kwargs["title"] == "Recovered headline"


@pytest.mark.asyncio
async def test_event_with_title_skips_silver_lookup() -> None:
    """Regression: an event that already has a title must NOT hit silver."""
    consumer = _make_consumer()
    doc_id = uuid.uuid4()
    payload = _titleless_payload(doc_id) | {"title": "Event headline"}

    with (
        patch(f"{_CONSUMER_NS}.RoutingDecisionRepository") as routing_repo_cls,
        patch.object(consumer, "_run_pipeline", new=AsyncMock()) as run_pipeline_mock,
        patch.object(consumer, "_write_source_metadata", new=AsyncMock()),
        patch(f"{_CONSUMER_NS}.extract_url_from_silver", new=AsyncMock(return_value=None)),
        patch(
            f"{_CONSUMER_NS}.extract_title_from_silver",
            new=AsyncMock(return_value="should not be used"),
        ) as title_mock,
    ):
        routing_repo_cls.return_value.get_by_doc = AsyncMock(return_value=None)

        await consumer.process_message(key=None, value=payload, headers={})

    title_mock.assert_not_awaited()
    assert run_pipeline_mock.await_args.kwargs["doc_title"] == "Event headline"


@pytest.mark.asyncio
async def test_titleless_event_unrecoverable_title_keeps_none() -> None:
    """sec_edgar with no recoverable title → doc_title stays None (C-8 fallback)."""
    consumer = _make_consumer()
    doc_id = uuid.uuid4()

    with (
        patch(f"{_CONSUMER_NS}.RoutingDecisionRepository") as routing_repo_cls,
        patch.object(consumer, "_run_pipeline", new=AsyncMock()) as run_pipeline_mock,
        patch.object(consumer, "_write_source_metadata", new=AsyncMock()),
        patch(f"{_CONSUMER_NS}.extract_url_from_silver", new=AsyncMock(return_value=None)),
        patch(f"{_CONSUMER_NS}.extract_title_from_silver", new=AsyncMock(return_value=None)),
    ):
        routing_repo_cls.return_value.get_by_doc = AsyncMock(return_value=None)

        await consumer.process_message(key=None, value=_titleless_payload(doc_id, source_type="sec_edgar"), headers={})

    assert run_pipeline_mock.await_args.kwargs["doc_title"] is None
