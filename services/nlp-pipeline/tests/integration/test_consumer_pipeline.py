"""Integration tests for ArticleProcessingConsumer pipeline orchestration.

These tests exercise the full orchestration path using mock ML clients but
real application logic (sectioning, routing, suppression, embeddings blocks).
They do NOT require a running database — all DB writes are intercepted via
mock session factories.

Test scenarios:
  T-C-4-05-A: Full pipeline — stored article → all blocks → enriched event enqueued.
  T-C-4-05-B: Zero NER — article with no entities → still processed (not suppressed).
  T-C-4-05-C: Backpressure — acquire slot before ML work, release after.
  T-C-4-05-D: Idempotency — same message twice → outbox.add called both times
               (DB constraint catches duplication; consumer does not deduplicate).
"""

from __future__ import annotations

import contextlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import ArticleProcessingConsumer

from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

# ── Mock ML adapters (inline — not imported from conftest) ────────────────────


class _MockNERClient:
    """Returns one organization mention per call, deterministically."""

    async def batch_extract_entities(self, inputs: list[Any]) -> list[Any]:
        from ml_clients.dataclasses import EntityMention as MLMention  # type: ignore[import-not-found]
        from ml_clients.dataclasses import NEROutput  # type: ignore[import-not-found]

        results = []
        for inp in inputs:
            if not inp.text.strip():
                results.append(NEROutput(mentions=[]))
            else:
                results.append(
                    NEROutput(mentions=[MLMention(text="TestCorp", label="organization", start=0, end=8, score=0.95)])
                )
        return results


class _MockZeroNERClient:
    """Returns no mentions — zero-NER scenario."""

    async def batch_extract_entities(self, inputs: list[Any]) -> list[Any]:
        from ml_clients.dataclasses import NEROutput  # type: ignore[import-not-found]

        return [NEROutput(mentions=[]) for _ in inputs]


class _MockEmbeddingClient:
    """Returns fixed-dimension zero vectors."""

    _DIM = 32

    async def embed(self, inputs: list[Any]) -> list[Any]:
        from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-not-found]

        return [
            EmbeddingOutput(embedding=[0.0] * self._DIM, model_id="bge-large-en-v1.5", dimension=self._DIM)
            for _ in inputs
        ]


class _MockExtractionClient:
    """Returns an empty extraction result."""

    async def extract(self, inp: Any) -> Any:
        from ml_clients.dataclasses import ExtractionOutput  # type: ignore[import-not-found]

        return ExtractionOutput(
            result={"events": [], "claims": [], "relations": []},
            raw_response="{}",
            model_id="qwen2.5:7b-instruct",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


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
    s.max_ollama_queue_depth = 20
    s.resume_ollama_queue_depth = 10
    return s


def _make_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _make_consumer(
    *,
    ner_client: Any = None,
    backpressure: Any = None,
    watchlist_cache: Any = None,
    storage: Any = None,
    nlp_session: AsyncMock | None = None,
    intel_session: AsyncMock | None = None,
) -> tuple[ArticleProcessingConsumer, AsyncMock, AsyncMock]:
    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["content.article.stored.v1"],
    )

    if ner_client is None:
        ner_client = _MockNERClient()

    if backpressure is None:
        bp = MagicMock()
        bp.__aenter__ = AsyncMock(return_value=None)
        bp.__aexit__ = AsyncMock(return_value=None)
        backpressure = bp

    if watchlist_cache is None:
        wc = MagicMock()
        wc.get_all_watched = AsyncMock(return_value=frozenset())
        wc._client = AsyncMock()
        watchlist_cache = wc

    if storage is None:
        st = MagicMock()
        st.get_object_bytes = MagicMock(
            return_value=b"Apple Inc. posted strong quarterly earnings. "
            b"Revenue grew 12% year-over-year driven by services."
        )
        storage = st

    nlp_sess = nlp_session or _make_mock_session()
    intel_sess = intel_session or _make_mock_session()

    nlp_sf = MagicMock(return_value=nlp_sess)
    intel_sf = MagicMock(return_value=intel_sess)

    consumer = ArticleProcessingConsumer(
        config=config,
        settings=_make_settings(),
        nlp_session_factory=nlp_sf,
        intelligence_session_factory=intel_sf,
        storage=storage,
        watchlist_cache=watchlist_cache,
        ner_client=ner_client,
        embedding_client=_MockEmbeddingClient(),
        extraction_client=_MockExtractionClient(),
        backpressure=backpressure,
    )
    return consumer, nlp_sess, intel_sess


def _make_event(doc_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "doc_id": str(doc_id or uuid.uuid4()),
        "minio_silver_key": "silver/articles/test.txt",
        "source_type": "eodhd",
        "published_at": datetime.now(tz=UTC).isoformat(),
        "is_backfill": False,
        "correlation_id": None,
    }


# Module path prefix for patching consumer-imported repositories
_MOD = "nlp_pipeline.infrastructure.messaging.consumers.article_consumer"


def _repo_patches(outbox_mock: Any = None) -> list[Any]:
    """Return patch context managers for all repos used inside _run_pipeline."""
    om = outbox_mock or AsyncMock()
    return [
        patch(f"{_MOD}.SectionRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.ChunkRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.EntityMentionRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.DocumentEntityStatsRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.RoutingDecisionRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.ChunkEntityMentionRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.OutboxRepository", return_value=om),
        patch(f"{_MOD}.MentionResolutionRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.DLQRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.EntityAliasRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.EntityProfileEmbeddingRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.CanonicalEntityRepository", return_value=AsyncMock()),
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestFullPipeline:
    """T-C-4-05-A: Full pipeline — enriched event written to outbox."""

    @pytest.mark.asyncio
    async def test_enriched_event_written_to_outbox(self) -> None:
        """process_message → outbox.add called with nlp.article.enriched.v1 topic."""
        consumer, _nlp_sess, _intel_sess = _make_consumer()

        outbox_add = AsyncMock()
        outbox_mock = AsyncMock()
        outbox_mock.add = outbox_add

        event = _make_event()

        with contextlib.ExitStack() as stack:
            for p in _repo_patches(outbox_mock=outbox_mock):
                stack.enter_context(p)
            await consumer.process_message(key=None, value=event, headers={})

        outbox_add.assert_called_once()
        call_kwargs = outbox_add.call_args.kwargs
        assert call_kwargs["topic"] == "nlp.article.enriched.v1"
        payload = json.loads(call_kwargs["payload_avro"])
        assert payload["doc_id"] == event["doc_id"]
        assert payload["event_type"] == "nlp.article.enriched"
        assert "routing_tier" in payload
        assert "section_count" in payload

    @pytest.mark.asyncio
    async def test_commit_called_after_all_writes(self) -> None:
        """DB commit must be called after all artifact writes."""
        consumer, _nlp_sess, _intel_sess = _make_consumer()

        with contextlib.ExitStack() as stack:
            for p in _repo_patches():
                stack.enter_context(p)
            await consumer.process_message(key=None, value=_make_event(), headers={})

        # Two commits on the nlp session factory: main pipeline + best-effort
        # source-metadata write (_write_source_metadata, added in Wave B-1)
        assert _nlp_sess.commit.await_count == 2


@pytest.mark.integration
class TestZeroNER:
    """T-C-4-05-B: Zero NER — article with no mentions still produces an enriched event."""

    @pytest.mark.asyncio
    async def test_zero_ner_article_still_enriched(self) -> None:
        """Even when NER finds nothing, the pipeline completes and writes to outbox."""
        consumer, _nlp_sess, _intel_sess = _make_consumer(ner_client=_MockZeroNERClient())

        outbox_add = AsyncMock()
        outbox_mock = AsyncMock()
        outbox_mock.add = outbox_add

        with contextlib.ExitStack() as stack:
            for p in _repo_patches(outbox_mock=outbox_mock):
                stack.enter_context(p)
            await consumer.process_message(key=None, value=_make_event(), headers={})

        # Enriched event must still be written
        outbox_add.assert_called_once()
        call_kwargs = outbox_add.call_args.kwargs
        payload = json.loads(call_kwargs["payload_avro"])
        assert payload["mention_count"] == 0


@pytest.mark.integration
class TestBackpressure:
    """T-C-4-05-C: Backpressure slot acquired before ML work."""

    @pytest.mark.asyncio
    async def test_backpressure_slot_acquired(self) -> None:
        """async with self._bp must be entered before ML work begins."""
        entered: list[bool] = []

        class _TrackingBP:
            async def __aenter__(self) -> _TrackingBP:
                entered.append(True)
                return self

            async def __aexit__(self, *args: Any) -> None:
                pass

        consumer, _nlp, _intel = _make_consumer(backpressure=_TrackingBP())

        with contextlib.ExitStack() as stack:
            for p in _repo_patches():
                stack.enter_context(p)
            await consumer.process_message(key=None, value=_make_event(), headers={})

        assert len(entered) == 1, "Backpressure slot must be acquired exactly once"


@pytest.mark.integration
class TestIdempotency:
    """T-C-4-05-D: Same message delivered twice → outbox.add called both times.

    The consumer uses at-least-once semantics; DB-level constraints (e.g., unique
    primary keys) are responsible for deduplication, not the consumer itself.
    """

    @pytest.mark.asyncio
    async def test_same_message_twice_calls_outbox_add_twice(self) -> None:
        """Re-delivery must not be silently dropped at the consumer level."""
        consumer, _nlp_sess, _intel_sess = _make_consumer()

        outbox_add = AsyncMock()
        outbox_mock = AsyncMock()
        outbox_mock.add = outbox_add

        event = _make_event()  # same event delivered twice

        with contextlib.ExitStack() as stack:
            for p in _repo_patches(outbox_mock=outbox_mock):
                stack.enter_context(p)
            await consumer.process_message(key=None, value=event, headers={})
            await consumer.process_message(key=None, value=event, headers={})

        assert outbox_add.call_count == 2, "outbox.add must be called for each delivery; DB constraint handles dedup"
