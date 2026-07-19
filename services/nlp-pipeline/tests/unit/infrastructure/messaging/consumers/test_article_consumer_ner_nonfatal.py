"""BP-718 regression: a GLiNER (Block-4 NER) failure must be NON-FATAL.

ROOT CAUSE (SEC-filings corpus-coverage gap)
--------------------------------------------
``ArticleProcessingConsumer._run_pipeline`` persists the searchable artefacts
(chunk_text + chunk_embeddings) only at the END of the pipeline, AFTER NER and
the LLM deep-extraction ML phase. When GLiNER was unavailable during the
2026-07-05 bulk SEC backfill, ``run_ner_block`` raised, the whole message was
routed to the DLQ, and the filing's chunks/embeddings were never written — so
large 10-Q/10-K filings (NVIDIA, Microsoft, Amazon) never entered the chat
corpus even though content_store held them.

FIX — a NER failure is caught and downgraded to "zero mentions" so the pipeline
continues to chunk + embed + persist the document (chat retrieval needs no
entity mentions; they can be backfilled later). These tests prove the pipeline
proceeds PAST NER when ``run_ner_block`` raises, and that a structured warning is
emitted instead of the exception propagating (which would DLQ the message).
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.unit

_CONSUMER_MOD = "nlp_pipeline.infrastructure.messaging.consumers.article_consumer"


class _ReachedEmbeddingsError(Exception):
    """Sentinel raised by the patched embeddings block to prove the pipeline
    continued PAST the failing NER block."""


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.gliner_threshold = 0.35
    s.gliner_batch_size = 32
    s.gliner_section_token_limit = 450
    s.embedding_model_id = "bge-large-en-v1.5"
    s.embedding_instruction_prefix = "Represent: "
    s.ner_model_id = "gliner"
    s.extraction_model_id = "qwen2.5:7b-instruct"
    s.topic_article_enriched = "nlp.article.enriched.v1"
    s.topic_signal_detected = "nlp.signal.detected.v1"
    s.min_word_count = 50
    s.routing_tier_deep = 0.7
    s.routing_tier_medium = 0.4
    s.routing_tier_light = 0.1
    # VALUE-signal override (feat/value-signal-routing): the consumer now reads these
    # in the hot path; a bare MagicMock returns a MagicMock for event_value_min_hits and
    # breaks the ``len(matched) >= min_hits`` comparison. Mirror the real production
    # defaults (signal ON, all categories) so this NER-nonfatal test exercises the real path.
    s.event_value_override_enabled = True
    s.event_value_categories_set = None
    s.event_value_min_hits = 1
    s.event_value_scan_chars = 600
    return s


def _make_session_factory() -> MagicMock:
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
    consumer = ArticleProcessingConsumer(
        config=config,
        settings=_make_settings(),
        nlp_session_factory=_make_session_factory(),
        intelligence_session_factory=_make_session_factory(),
        storage=MagicMock(),
        watchlist_cache=MagicMock(),
        ner_client=MagicMock(),
        embedding_client=MagicMock(),
        extraction_client=MagicMock(),
        backpressure=MagicMock(),
    )
    consumer._watchlist = MagicMock()
    consumer._watchlist.get_all_watched = AsyncMock(return_value=frozenset())
    return consumer


def _real_text() -> str:
    """A non-stub body (>= min_word_count) so the stub filter does not short-circuit."""
    return " ".join(["revenue"] * 200)


class TestNerFailureNonFatal:
    @pytest.mark.asyncio
    async def test_ner_failure_does_not_abort_pipeline(self) -> None:
        """When run_ner_block raises, the pipeline must still reach the embeddings
        block (proving the document will be chunked/embedded/persisted)."""
        consumer = _make_consumer()

        ner_mock = AsyncMock(side_effect=RuntimeError("GLiNER server connection error"))
        embeddings_mock = AsyncMock(side_effect=_ReachedEmbeddingsError)

        with (
            patch.object(consumer, "_download_article", new=AsyncMock(return_value=_real_text())),
            patch(f"{_CONSUMER_MOD}.section_document", MagicMock(return_value=[MagicMock(text="Acme beats revenue")])),
            patch(f"{_CONSUMER_MOD}.run_ner_block", new=ner_mock),
            patch(f"{_CONSUMER_MOD}.run_embeddings_block", new=embeddings_mock),
        ):
            # The pipeline must swallow the NER error and continue to embeddings,
            # where our sentinel proves execution progressed past Block 4.
            with pytest.raises(_ReachedEmbeddingsError):
                await consumer._run_pipeline(
                    doc_id=uuid.uuid4(),
                    minio_key="bucket/nvda-10q",
                    source_type="sec_edgar",
                    published_at=datetime.now(tz=UTC),
                    extracted_at=datetime.now(tz=UTC),
                    is_backfill=False,
                    correlation_id=None,
                )

        ner_mock.assert_awaited_once()
        embeddings_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ner_failure_logs_nonfatal_warning(self) -> None:
        """A NER failure must emit the structured ``ner_block_failed_nonfatal`` event
        (not propagate), so the message is not DLQ'd for an enrichment-only failure."""
        from structlog.testing import capture_logs

        consumer = _make_consumer()
        ner_mock = AsyncMock(side_effect=RuntimeError("Server disconnected"))
        # Stop cleanly right after NER so we only exercise the guard.
        embeddings_mock = AsyncMock(side_effect=_ReachedEmbeddingsError)

        with (
            capture_logs() as logs,
            patch.object(consumer, "_download_article", new=AsyncMock(return_value=_real_text())),
            patch(f"{_CONSUMER_MOD}.section_document", MagicMock(return_value=[MagicMock(text="Acme beats revenue")])),
            patch(f"{_CONSUMER_MOD}.run_ner_block", new=ner_mock),
            patch(f"{_CONSUMER_MOD}.run_embeddings_block", new=embeddings_mock),
        ):
            with pytest.raises(_ReachedEmbeddingsError):
                await consumer._run_pipeline(
                    doc_id=uuid.uuid4(),
                    minio_key="bucket/nvda-10q",
                    source_type="sec_edgar",
                    published_at=datetime.now(tz=UTC),
                    extracted_at=datetime.now(tz=UTC),
                    is_backfill=False,
                    correlation_id=None,
                )

        events = [e for e in logs if e.get("event") == "article_consumer.ner_block_failed_nonfatal"]
        assert len(events) == 1, f"expected 1 non-fatal NER warning, got: {logs}"
        assert events[0]["source_type"] == "sec_edgar"

    def test_ner_call_is_wrapped_in_try_except(self) -> None:
        """Source-level guard: the run_ner_block call must be inside a try/except so a
        GLiNER outage cannot abort the message (defence against a future refactor
        that unwraps it)."""
        source = inspect.getsource(ArticleProcessingConsumer._run_pipeline)
        assert "run_ner_block" in source
        assert (
            "ner_block_failed_nonfatal" in source
        ), "BP-718: run_ner_block must be guarded so NER failures are non-fatal."
