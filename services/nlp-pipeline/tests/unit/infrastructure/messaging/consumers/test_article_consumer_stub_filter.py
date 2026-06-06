"""RC-1 regression tests: stub-article filter must skip articles with word_count < min_word_count.

Before the fix, Finnhub (~91% stub rate) and SEC Edgar (~52% stub rate) articles with
fewer than 50 words consumed NER, embedding, and LLM extraction budget without producing
any relational signal.

These tests drive ``_run_pipeline`` with a stubbed ``_download_article`` that returns
text of varying word counts. The filter runs BEFORE any ML block, so we assert that
all Block 4-10 calls are never made for stub articles.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    ArticleProcessingConsumer,
)

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(min_word_count: int = 50) -> MagicMock:
    """Build a minimal Settings mock with configurable min_word_count."""
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
    s.max_ollama_queue_depth = 20
    s.resume_ollama_queue_depth = 10
    s.min_word_count = min_word_count
    return s


def _make_session_factory() -> tuple[AsyncMock, MagicMock]:
    """Build (session, factory) pair where factory() is an async CM yielding the session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = cm
    return session, factory


def _make_consumer(min_word_count: int = 50) -> ArticleProcessingConsumer:
    """Build an ArticleProcessingConsumer with configurable min_word_count."""
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    _nlp_s, nlp_sf = _make_session_factory()
    _intel_s, intel_sf = _make_session_factory()

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["content.article.stored.v1"],
    )
    consumer = ArticleProcessingConsumer(
        config=config,
        settings=_make_settings(min_word_count=min_word_count),
        nlp_session_factory=nlp_sf,
        intelligence_session_factory=intel_sf,
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


def _make_text(word_count: int) -> str:
    """Generate a text string with exactly *word_count* words."""
    return " ".join(["word"] * word_count)


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestStubArticleFilter:
    """RC-1: _run_pipeline must return early for stub articles (word_count < min_word_count).

    All downstream ML blocks (NER, embeddings, extraction) must NOT be called.
    """

    @pytest.mark.asyncio
    async def test_stub_article_skips_ner(self) -> None:
        """An article with word_count < min_word_count must not invoke run_ner_block."""
        consumer = _make_consumer(min_word_count=50)
        stub_text = _make_text(10)  # 10 words — below the 50-word threshold

        ner_mock = AsyncMock(return_value=([], MagicMock()))
        with (
            patch.object(consumer, "_download_article", new=AsyncMock(return_value=stub_text)),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_ner_block",
                new=ner_mock,
            ),
        ):
            await consumer._run_pipeline(
                doc_id=uuid.uuid4(),
                minio_key="bucket/stub-key",
                source_type="finnhub",
                published_at=datetime.now(tz=UTC),
                extracted_at=datetime.now(tz=UTC),
                is_backfill=False,
                correlation_id=None,
            )

        # NER block must NOT have been called
        ner_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stub_article_skips_embeddings(self) -> None:
        """An article with word_count < min_word_count must not invoke run_embeddings_block."""
        consumer = _make_consumer(min_word_count=50)
        stub_text = _make_text(49)  # one word below the threshold

        embeddings_mock = AsyncMock(return_value=([], [], [], []))
        with (
            patch.object(consumer, "_download_article", new=AsyncMock(return_value=stub_text)),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.run_embeddings_block",
                new=embeddings_mock,
            ),
        ):
            await consumer._run_pipeline(
                doc_id=uuid.uuid4(),
                minio_key="bucket/stub-key",
                source_type="sec_edgar",
                published_at=datetime.now(tz=UTC),
                extracted_at=datetime.now(tz=UTC),
                is_backfill=False,
                correlation_id=None,
            )

        embeddings_mock.assert_not_awaited()

    def test_filter_boundary_strictly_less_than(self) -> None:
        """The stub filter uses strict less-than (<), not less-than-or-equal.

        RC-1 invariant: word_count=49 is filtered, word_count=50 is not filtered
        (with min_word_count=50). We verify this by checking the word count
        comparison formula directly in the source code rather than driving the
        full pipeline (which requires extensive mocking of Avro serialization).
        """
        import inspect

        from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
            ArticleProcessingConsumer,
        )

        source = inspect.getsource(ArticleProcessingConsumer._run_pipeline)
        # The guard must use strict less-than so word_count==min_word_count passes
        assert "word_count < self._settings.min_word_count" in source, (
            "RC-1: stub filter must use strict less-than (<) so that articles "
            "with exactly min_word_count words are NOT filtered out."
        )

    @pytest.mark.asyncio
    async def test_stub_article_does_not_call_section_document(self) -> None:
        """A stub article (word_count < min_word_count) must NOT call section_document.

        This is the complement of the positive test: if the stub filter triggers,
        no Block 3+ code runs at all.
        """
        consumer = _make_consumer(min_word_count=50)
        stub_text = _make_text(30)  # 30 words — below 50
        section_mock = MagicMock(return_value=[])

        with (
            patch.object(consumer, "_download_article", new=AsyncMock(return_value=stub_text)),
            patch(
                "nlp_pipeline.infrastructure.messaging.consumers.article_consumer.section_document",
                section_mock,
            ),
        ):
            await consumer._run_pipeline(
                doc_id=uuid.uuid4(),
                minio_key="bucket/stub-key",
                source_type="sec_edgar",
                published_at=datetime.now(tz=UTC),
                extracted_at=datetime.now(tz=UTC),
                is_backfill=False,
                correlation_id=None,
            )

        # section_document must NOT have been called for a stub article
        section_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_stub_filter_logs_structured_event(self) -> None:
        """Stub-filtered articles must emit a structured log event for observability."""
        from structlog.testing import capture_logs

        consumer = _make_consumer(min_word_count=50)
        stub_text = _make_text(5)  # well below threshold

        with (
            capture_logs() as log_output,
            patch.object(consumer, "_download_article", new=AsyncMock(return_value=stub_text)),
        ):
            await consumer._run_pipeline(
                doc_id=uuid.uuid4(),
                minio_key="bucket/tiny",
                source_type="finnhub",
                published_at=datetime.now(tz=UTC),
                extracted_at=datetime.now(tz=UTC),
                is_backfill=False,
                correlation_id=None,
            )

        # Must emit exactly one structured log event with the correct event name
        stub_events = [e for e in log_output if e.get("event") == "article_consumer.stub_filtered"]
        assert len(stub_events) == 1, f"Expected 1 stub_filtered log event, got: {log_output}"
        assert stub_events[0]["word_count"] == 5
        assert stub_events[0]["min_word_count"] == 50
