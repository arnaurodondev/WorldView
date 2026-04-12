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
        import json as _json

        st = MagicMock()
        st.get_bytes = AsyncMock(
            return_value=_json.dumps(
                {
                    "body": "Apple Inc. posted strong quarterly earnings. "
                    "Revenue grew 12% year-over-year driven by services.",
                    "source_type": "article",
                }
            ).encode()
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


def _make_routing_mock(get_by_doc_side_effect: list[Any] | None = None) -> AsyncMock:
    """Return a RoutingDecisionRepository mock.

    By default ``get_by_doc`` returns ``None`` (article not yet processed),
    so the idempotency guard in ``_run_pipeline`` lets the pipeline run.
    Pass ``get_by_doc_side_effect`` for tests that need different call-by-call
    return values (e.g. None on first delivery, a result on re-delivery).
    """
    rm = AsyncMock()
    if get_by_doc_side_effect is not None:
        rm.get_by_doc = AsyncMock(side_effect=get_by_doc_side_effect)
    else:
        rm.get_by_doc = AsyncMock(return_value=None)
    return rm


def _repo_patches(outbox_mock: Any = None, routing_mock: Any = None) -> list[Any]:
    """Return patch context managers for all repos used inside _run_pipeline."""
    om = outbox_mock or AsyncMock()
    # Default routing mock has get_by_doc → None so the idempotency guard passes.
    rm = routing_mock if routing_mock is not None else _make_routing_mock()
    return [
        patch(f"{_MOD}.SectionRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.ChunkRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.EntityMentionRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.DocumentEntityStatsRepository", return_value=AsyncMock()),
        patch(f"{_MOD}.RoutingDecisionRepository", return_value=rm),
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
    """T-C-4-05-D: Re-delivery is skipped when routing_decision already exists.

    Section/chunk IDs are generated with new_uuid7() (non-deterministic), so
    DB ON CONFLICT guards on the primary key do NOT prevent duplicate rows on
    re-delivery.  The consumer therefore performs an explicit pre-check: if a
    routing_decision row already exists for the doc_id the full pipeline is
    skipped — outbox.add is NOT called a second time.
    """

    @pytest.mark.asyncio
    async def test_second_delivery_skipped_when_already_processed(self) -> None:
        """Re-delivery is a no-op when the pipeline already committed for this doc_id."""
        consumer, _nlp_sess, _intel_sess = _make_consumer()

        outbox_add = AsyncMock()
        outbox_mock = AsyncMock()
        outbox_mock.add = outbox_add

        event = _make_event()  # same doc_id delivered twice

        # First call: no routing_decision → pipeline runs → outbox.add called.
        # Second call: routing_decision exists → idempotency guard fires → skip.
        routing_mock = _make_routing_mock(get_by_doc_side_effect=[None, MagicMock()])

        with contextlib.ExitStack() as stack:
            for p in _repo_patches(outbox_mock=outbox_mock, routing_mock=routing_mock):
                stack.enter_context(p)
            await consumer.process_message(key=None, value=event, headers={})
            await consumer.process_message(key=None, value=event, headers={})

        assert outbox_add.call_count == 1, "Second delivery must be skipped: routing_decision already exists for doc_id"
