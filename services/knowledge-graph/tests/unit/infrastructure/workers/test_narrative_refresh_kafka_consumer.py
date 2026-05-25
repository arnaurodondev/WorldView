"""Unit tests for NarrativeRefreshKafkaConsumer (PLAN-0074 T-C-05).

Covers:
  - test_narrative_kafka_consumer_skips_duplicate_version
      same (entity_id, version_id) already seen → ValkeyDedupMixin returns True → skipped
  - test_narrative_kafka_consumer_embeds_and_upserts
      successful path → narrative_text fetched, truncated, embedded, upserted
  - test_narrative_kafka_consumer_embed_failure_does_not_dead_letter
      embed() raises → logged but NOT re-raised, no upsert called
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

# Shared test data
_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000042")
_VERSION_ID = UUID("00000000-0000-0000-0000-000000000099")
_EVENT_ID = "event-id-001"
_EMBED_MODEL_ID = "nomic-embed-text"

# Path constants for patching
_EMB_REPO_PATH = (
    "knowledge_graph.infrastructure.intelligence_db.repositories"
    ".entity_embedding_state.EntityEmbeddingStateRepository"
)
# Patch the consumer's module-level logger to suppress log output in tests.
_LOGGER_PATH = "knowledge_graph.infrastructure.workers.narrative_refresh.logger"


def _make_event_payload(*, event_id: str = _EVENT_ID) -> dict:
    """Build a minimal entity.narrative.generated.v1 payload dict."""
    return {
        "event_id": event_id,
        "entity_id": str(_ENTITY_ID),
        "version_id": str(_VERSION_ID),
        "generation_reason": "INITIAL",
        "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "narrative_text_length": 200,
        "occurred_at": "2026-05-08T10:00:00Z",
        "schema_version": "1.0.0",
    }


def _make_session_factory(narrative_text: str | None = "Apple Inc. is a technology company.") -> MagicMock:
    """Return a mock async_sessionmaker.

    The session executes a SELECT and returns a row with narrative_text,
    or no row when narrative_text is None (simulates row-not-found).
    """
    session = AsyncMock()
    session.commit = AsyncMock()

    # Simulate SELECT result for entity_narrative_versions
    row = MagicMock()
    row.__getitem__ = lambda self, i: narrative_text  # row[0] = narrative_text

    result = MagicMock()
    if narrative_text is not None:
        result.fetchone.return_value = row
    else:
        result.fetchone.return_value = None

    session.execute = AsyncMock(return_value=result)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock(return_value=cm)
    return factory


def _make_consumer(
    *,
    session_factory: MagicMock | None = None,
    llm_client: AsyncMock | None = None,
    dedup_client: MagicMock | None = None,
) -> object:
    """Instantiate NarrativeRefreshKafkaConsumer with test doubles."""
    from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshKafkaConsumer

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="test-narrative-refresh",
        topics=["entity.narrative.generated.v1"],
        # Disable watchdog timeout in tests so asyncio.timeout() is not triggered.
        message_processing_timeout_s=0,
    )
    return NarrativeRefreshKafkaConsumer(
        config=config,
        session_factory=session_factory or _make_session_factory(),
        llm_client=llm_client or AsyncMock(),
        embed_model_id=_EMBED_MODEL_ID,
        dedup_client=dedup_client,
    )


def _make_embedding_output(dim: int = 10) -> list:
    """Return a minimal EmbeddingOutput list."""
    from ml_clients.dataclasses import EmbeddingOutput  # type: ignore[import-untyped]

    return [EmbeddingOutput(embedding=[0.1] * dim, model_id=_EMBED_MODEL_ID, dimension=dim)]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit()
class TestNarrativeRefreshKafkaConsumer:
    def test_narrative_kafka_consumer_skips_duplicate_version(self) -> None:
        """is_duplicate returns True → process_message is never called.

        The ValkeyDedupMixin.is_duplicate check happens inside _handle_message
        BEFORE get_unit_of_work and process_message are called (BP-064).  We
        simulate this by calling is_duplicate directly with a pre-set Valkey
        mock that returns True, then confirming process_message is a no-op path.
        """
        # Arrange: Valkey mock that reports the event as already seen.
        valkey = AsyncMock()
        valkey.exists = AsyncMock(return_value=True)  # is_duplicate → True

        session_factory = _make_session_factory()
        consumer = _make_consumer(session_factory=session_factory, dedup_client=valkey)

        # Act: call is_duplicate directly — simulates what _handle_message does
        # before dispatching to process_message.
        result = asyncio.run(consumer.is_duplicate(_EVENT_ID))  # type: ignore[attr-defined]

        # Assert: duplicate detected → True; no DB session opened.
        assert result is True, "is_duplicate should return True when Valkey key exists"
        session_factory.assert_not_called()

    def test_narrative_kafka_consumer_embeds_and_upserts(self) -> None:
        """Happy path: narrative_text fetched → truncated → embedded → upserted."""
        # Arrange: 2000-char text to exercise the BP-121 truncation path.
        long_text = "Apple Inc. is a technology company. " * 60  # ~2160 chars
        assert len(long_text) > 1500, "test precondition: text must exceed 1500 chars"

        session_factory = _make_session_factory(narrative_text=long_text)

        llm = AsyncMock()
        llm.embed = AsyncMock(return_value=_make_embedding_output())

        emb_repo = AsyncMock()
        emb_repo.upsert = AsyncMock()

        consumer = _make_consumer(session_factory=session_factory, llm_client=llm)
        payload = _make_event_payload()

        with patch(_EMB_REPO_PATH, return_value=emb_repo):
            asyncio.run(consumer.process_message(None, payload, {}))  # type: ignore[attr-defined]

        # embed() must have been called with text truncated to 1500 chars.
        llm.embed.assert_awaited_once()
        embed_call_args = llm.embed.call_args
        assert embed_call_args is not None
        inputs = embed_call_args.args[0]
        assert len(inputs) == 1, "expected exactly one EmbeddingInput"
        assert len(inputs[0].text) == 1500, f"BP-121: text must be truncated to 1500 chars, got {len(inputs[0].text)}"

        # upsert() must have been called once with a non-None embedding.
        emb_repo.upsert.assert_awaited_once()
        call_kwargs = emb_repo.upsert.call_args.kwargs
        assert call_kwargs.get("embedding") is not None, "embedding must not be None on success"
        assert call_kwargs.get("model_id") == _EMBED_MODEL_ID

    def test_narrative_kafka_consumer_embed_failure_does_not_dead_letter(self) -> None:
        """embed() raises an exception → logged as WARNING but NOT re-raised.

        The consumer must return cleanly (no exception propagation, no
        dead-lettering) so the hourly NarrativeRefreshWorker can catch up.
        """
        session_factory = _make_session_factory()

        llm = AsyncMock()
        llm.embed = AsyncMock(side_effect=RuntimeError("DeepInfra 503 Service Unavailable"))

        emb_repo = AsyncMock()
        emb_repo.upsert = AsyncMock()

        consumer = _make_consumer(session_factory=session_factory, llm_client=llm)
        payload = _make_event_payload()

        # Act: must NOT raise despite embed() raising.
        with patch(_EMB_REPO_PATH, return_value=emb_repo):
            # Should complete without raising.
            asyncio.run(consumer.process_message(None, payload, {}))  # type: ignore[attr-defined]

        # Embed was attempted.
        llm.embed.assert_awaited_once()

        # Upsert must NOT have been called — embed failed so there is nothing to store.
        emb_repo.upsert.assert_not_awaited()

    def test_narrative_kafka_consumer_version_not_found_returns_early(self) -> None:
        """When entity_narrative_versions row is missing, return early without embedding."""
        session_factory = _make_session_factory(narrative_text=None)

        llm = AsyncMock()
        llm.embed = AsyncMock()

        consumer = _make_consumer(session_factory=session_factory, llm_client=llm)
        payload = _make_event_payload()

        asyncio.run(consumer.process_message(None, payload, {}))  # type: ignore[attr-defined]

        # embed() must not have been called — no text to embed.
        llm.embed.assert_not_awaited()

    def test_narrative_kafka_consumer_json_deserialization(self) -> None:
        """deserialize_value falls back to JSON when magic byte is absent."""
        consumer = _make_consumer()
        payload = _make_event_payload()
        raw = json.dumps(payload).encode()

        # Should return the payload dict without raising.
        result = consumer.deserialize_value(raw)  # type: ignore[attr-defined]
        assert result["entity_id"] == str(_ENTITY_ID)
        assert result["version_id"] == str(_VERSION_ID)

    def test_narrative_kafka_consumer_extract_event_id(self) -> None:
        """extract_event_id returns the event_id field from the payload."""
        consumer = _make_consumer()
        payload = _make_event_payload()
        assert consumer.extract_event_id(payload) == _EVENT_ID  # type: ignore[attr-defined]

    def test_narrative_kafka_consumer_get_schema_path_known_topic(self) -> None:
        """get_schema_path returns a path for the narrative generated topic."""
        consumer = _make_consumer()
        path = consumer.get_schema_path("entity.narrative.generated.v1")  # type: ignore[attr-defined]
        assert path is not None
        assert "entity.narrative.generated.v1.avsc" in path

    def test_narrative_kafka_consumer_get_schema_path_unknown_topic(self) -> None:
        """get_schema_path returns None for unrecognised topics."""
        consumer = _make_consumer()
        assert consumer.get_schema_path("some.other.topic") is None  # type: ignore[attr-defined]
