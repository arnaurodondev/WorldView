"""Unit tests for PredictionEnrichedConsumer (PLAN-0056 Wave C2).

Tests cover:
- EventType.PREDICTION enum value present + lowercase.
- Happy path: a polymarket enriched doc → 1 temporal event (PREDICTION/LOCAL) +
  N exposures (one per resolved entity), polarity NULL.
- Filter: source_type != 'polymarket' (e.g. 'eodhd') → no DB writes.
- Idempotency: re-delivery of the same doc issues the same natural-key upsert
  (idempotent on the repo side; here we assert the consumer commits both times
  and passes the same title/region).
- Zero resolved entities → temporal event created, 0 exposures.
- Explicit commit (R26 — no HTTP200-but-rollback).
- extract_event_id / is_duplicate plumbing.

PLAN-0056 Wave C2 (PRD-0033).
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_DB_EVENT_ID = UUID("01920000-0000-7000-8000-0000000000aa")
_EXPOSURE_ID = UUID("01920000-0000-7000-8000-0000000000bb")
_ENTITY_A = "01920000-0000-7000-8000-000000000001"
_ENTITY_B = "01920000-0000-7000-8000-000000000002"
_DOC_ID = "01920000-0000-7000-8000-0000000000cc"

# Patch paths for repositories lazily imported inside the consumer.
_TEMPORAL_EVENT_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.TemporalEventRepository"
)
_EXPOSURE_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.EntityEventExposureRepository"  # noqa: E501


def _make_consumer() -> tuple[Any, Any, Any, Any]:
    """Build a PredictionEnrichedConsumer with mocked session + repos.

    Returns (consumer, event_repo_mock, exposure_repo_mock, session_mock).
    """
    from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
        PredictionEnrichedConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-prediction-enriched-test",
        topics=["nlp.article.enriched.v1"],
    )

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    event_repo = AsyncMock()
    event_repo.upsert_by_natural_key = AsyncMock(return_value=_DB_EVENT_ID)

    exposure_repo = AsyncMock()
    exposure_repo.upsert = AsyncMock(return_value=_EXPOSURE_ID)

    consumer = PredictionEnrichedConsumer(config=config, session_factory=sf)
    return consumer, event_repo, exposure_repo, session


def _make_message(
    *,
    source_type: str = "polymarket",
    doc_id: str = _DOC_ID,
    resolved_entity_ids: list[str] | None = None,
    published_at: str | None = "2026-07-09T12:00:00+00:00",
) -> dict[str, Any]:
    """Build a decoded nlp.article.enriched.v1 dict."""
    return {
        "event_id": str(uuid4()),
        "doc_id": doc_id,
        "source_type": source_type,
        "resolved_entity_ids": resolved_entity_ids if resolved_entity_ids is not None else [_ENTITY_A, _ENTITY_B],
        "published_at": published_at,
        "occurred_at": "2026-07-09T12:00:01+00:00",
    }


# ── EventType.PREDICTION enum value ──────────────────────────────────────────


class TestEventTypePrediction:
    def test_prediction_enum_value_is_lowercase_string(self) -> None:
        """EventType.PREDICTION must be lowercase to match the DB CHECK constraint (0066)."""
        from knowledge_graph.domain.enums import EventType

        assert EventType.PREDICTION == "prediction"
        assert EventType.PREDICTION.value == "prediction"


# ── Happy path ───────────────────────────────────────────────────────────────


class TestPredictionEnrichedConsumerHappyPath:
    def test_polymarket_doc_creates_one_prediction_event(self) -> None:
        """polymarket enriched doc → 1 temporal event with PREDICTION/LOCAL, region='prediction'."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_awaited_once()
        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["event_type"].value == "prediction"
        assert kwargs["scope"].value == "LOCAL"
        assert kwargs["region"] == "prediction"
        assert kwargs["title"] == f"Prediction market {_DOC_ID}"
        assert kwargs["active_until"] is None
        assert kwargs["residual_impact_days"] == 30
        assert kwargs["confidence"] == 0.5

    def test_one_exposure_per_resolved_entity_with_null_polarity(self) -> None:
        """Each resolved entity → 1 DIRECTLY_AFFECTED exposure, polarity NULL (no C3 classifier)."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        assert exposure_repo.upsert.await_count == 2
        for call in exposure_repo.upsert.call_args_list:
            kwargs = call.kwargs
            assert kwargs["event_id"] == _DB_EVENT_ID
            assert kwargs["exposure_type"].value == "directly_affected"
            assert kwargs["polarity"] is None
            assert kwargs["polarity_confidence"] is None
        linked = {c.kwargs["entity_id"] for c in exposure_repo.upsert.call_args_list}
        assert linked == {UUID(_ENTITY_A), UUID(_ENTITY_B)}

    def test_commit_is_called_r26(self) -> None:
        """R26: the consumer must COMMIT its writes (no HTTP200-but-rollback)."""
        consumer, event_repo, exposure_repo, session = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        session.commit.assert_awaited_once()


# ── Filter: non-polymarket source types ──────────────────────────────────────


class TestPredictionEnrichedConsumerFilter:
    def test_eodhd_source_type_skipped(self) -> None:
        """source_type='eodhd' → no temporal event, no exposure, no commit."""
        consumer, event_repo, exposure_repo, session = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(source_type="eodhd"), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()
        exposure_repo.upsert.assert_not_awaited()
        session.commit.assert_not_awaited()

    def test_prediction_market_string_not_matched(self) -> None:
        """Guardrail: the stale 'prediction_market' value is NOT what B2 emits → skipped."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(source_type="prediction_market"), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()


# ── Idempotency ──────────────────────────────────────────────────────────────


class TestPredictionEnrichedConsumerIdempotency:
    def test_redelivery_uses_same_natural_key(self) -> None:
        """Re-delivering the same doc issues the same natural key (region+title) both times.

        The repo's ON CONFLICT makes the write a no-op; here we assert the
        consumer is deterministic (same title/region/active window) so the
        natural key matches on the second delivery.
        """
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        msg = _make_message()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))
            asyncio.run(consumer.process_message(None, msg, {}))

        assert event_repo.upsert_by_natural_key.await_count == 2
        first = event_repo.upsert_by_natural_key.call_args_list[0].kwargs
        second = event_repo.upsert_by_natural_key.call_args_list[1].kwargs
        assert first["title"] == second["title"]
        assert first["region"] == second["region"]
        assert first["active_from"] == second["active_from"]


# ── Zero resolved entities ───────────────────────────────────────────────────


class TestPredictionEnrichedConsumerNoEntities:
    def test_zero_entities_creates_event_but_no_exposures(self) -> None:
        """A market question resolving 0 entities → temporal event created, 0 exposures."""
        consumer, event_repo, exposure_repo, session = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(resolved_entity_ids=[]), {}))

        event_repo.upsert_by_natural_key.assert_awaited_once()
        exposure_repo.upsert.assert_not_awaited()
        session.commit.assert_awaited_once()

    def test_duplicate_entity_ids_deduped(self) -> None:
        """Repeated entity ids in one payload → a single exposure per distinct entity."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(None, _make_message(resolved_entity_ids=[_ENTITY_A, _ENTITY_A]), {}),
            )

        assert exposure_repo.upsert.await_count == 1


# ── Missing / malformed fields ───────────────────────────────────────────────


class TestPredictionEnrichedConsumerMalformed:
    def test_missing_doc_id_skipped(self) -> None:
        """No doc_id → skip (cannot form a stable natural key)."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        msg = _make_message()
        del msg["doc_id"]
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))
        event_repo.upsert_by_natural_key.assert_not_awaited()

    def test_bad_entity_id_skipped_others_linked(self) -> None:
        """A malformed entity id is skipped; valid ones still linked; event still created."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(None, _make_message(resolved_entity_ids=["not-a-uuid", _ENTITY_A]), {}),
            )
        event_repo.upsert_by_natural_key.assert_awaited_once()
        assert exposure_repo.upsert.await_count == 1


# ── Plumbing ─────────────────────────────────────────────────────────────────


class TestPredictionEnrichedConsumerPlumbing:
    def test_extract_event_id_returns_event_id_field(self) -> None:
        consumer, _, _, _ = _make_consumer()
        assert consumer.extract_event_id({"event_id": "abc-123"}) == "abc-123"

    def test_is_duplicate_returns_false_without_dedup_client(self) -> None:
        consumer, _, _, _ = _make_consumer()
        assert asyncio.run(consumer.is_duplicate("evt-123")) is False

    def test_get_schema_path_for_enriched_topic(self) -> None:
        consumer, _, _, _ = _make_consumer()
        assert consumer.get_schema_path("nlp.article.enriched.v1") is not None
        assert consumer.get_schema_path("some.other.topic") is None
