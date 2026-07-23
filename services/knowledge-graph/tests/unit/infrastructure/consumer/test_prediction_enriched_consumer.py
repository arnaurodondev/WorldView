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
    external_id: str | None = None,
    source_title: str | None = None,
) -> dict[str, Any]:
    """Build a decoded nlp.article.enriched.v1 dict.

    ``external_id`` (PLAN-0056 Wave C2b) and ``source_title`` (Wave C3) are omitted
    from the payload when None so the default fixtures exercise the legacy path
    (anonymous title, no question → no polarity classification).
    """
    msg: dict[str, Any] = {
        "event_id": str(uuid4()),
        "doc_id": doc_id,
        "source_type": source_type,
        "resolved_entity_ids": resolved_entity_ids if resolved_entity_ids is not None else [_ENTITY_A, _ENTITY_B],
        "published_at": published_at,
        "occurred_at": "2026-07-09T12:00:01+00:00",
    }
    if external_id is not None:
        msg["external_id"] = external_id
    if source_title is not None:
        msg["source_title"] = source_title
    return msg


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
        """Legacy fallback (no external_id): 1 temporal event PREDICTION/LOCAL, region='prediction'.

        PLAN-0056 Wave C2b: this fixture omits external_id, so it deliberately
        exercises the backward-compatible anonymous path (region='prediction',
        doc_id in the title). The condition_id path is covered by
        ``TestPredictionEnrichedConsumerExternalId``.
        """
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


# ── PLAN-0056 Wave C2b: external_id → condition_id market identity ────────────


_CONDITION_ID = "0xabc123def456"


class TestParseConditionId:
    """Unit tests for the ``_parse_condition_id`` helper (C2b)."""

    def test_parses_polymarket_prefix(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
            _parse_condition_id,
        )

        assert _parse_condition_id(f"polymarket:{_CONDITION_ID}") == _CONDITION_ID

    def test_none_when_absent(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
            _parse_condition_id,
        )

        assert _parse_condition_id(None) is None

    def test_none_when_wrong_prefix(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
            _parse_condition_id,
        )

        # Malformed: not the polymarket: prefix → fall back to anonymous behaviour.
        assert _parse_condition_id("kalshi:XYZ") is None
        assert _parse_condition_id(_CONDITION_ID) is None

    def test_none_when_empty_after_prefix(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
            _parse_condition_id,
        )

        assert _parse_condition_id("polymarket:") is None
        assert _parse_condition_id("polymarket:   ") is None

    def test_none_when_non_string(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
            _parse_condition_id,
        )

        assert _parse_condition_id(12345) is None


class TestPredictionEnrichedConsumerExternalId:
    """C2b: a polymarket doc carrying external_id resolves to the real market."""

    def test_condition_id_becomes_region_and_title(self) -> None:
        """external_id='polymarket:<cid>' → region==condition_id, title keyed on condition_id."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}"),
                    {},
                ),
            )

        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["region"] == _CONDITION_ID
        assert kwargs["title"] == f"Prediction market {_CONDITION_ID}"

    def test_condition_id_sets_dedup_by_region_only(self) -> None:
        """PLAN-0056 QA (FIX 1): a recovered condition_id → dedup_by_region_only=True.

        This is what makes a market with NO close_time collapse onto one temporal
        row: region==condition_id is globally unique, so the active_from::day
        component of the natural key is dropped for prediction events.
        """
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}"),
                    {},
                ),
            )
        assert event_repo.upsert_by_natural_key.call_args.kwargs["dedup_by_region_only"] is True

    def test_null_close_time_distinct_days_still_one_market_key(self) -> None:
        """No close_time (published_at absent) + two docs on different days → same region-only key.

        Reproduces the FIX 1 bug scenario: with published_at None each doc falls back
        to its OWN occurred_at (different wall-clock days), but because the recovered
        condition_id sets dedup_by_region_only=True and region is identical, both docs
        target the SAME market row (the repo ignores the differing active_from day).
        """
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        ext = f"polymarket:{_CONDITION_ID}"
        # First-sight doc: no close_time (published_at None), occurred_at on day 1.
        first = _make_message(doc_id=_DOC_ID, external_id=ext, published_at=None)
        first["occurred_at"] = "2026-07-01T09:00:00+00:00"
        # Resolution doc: still no close_time, occurred_at on a LATER day.
        second = _make_message(
            doc_id="01920000-0000-7000-8000-0000000000dd",
            external_id=f"polymarket:{_CONDITION_ID}:resolved",
            published_at=None,
        )
        second["occurred_at"] = "2026-07-08T17:00:00+00:00"
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, first, {}))
            asyncio.run(consumer.process_message(None, second, {}))

        k1 = event_repo.upsert_by_natural_key.call_args_list[0].kwargs
        k2 = event_repo.upsert_by_natural_key.call_args_list[1].kwargs
        # active_from differs (different occurred_at days) …
        assert k1["active_from"] != k2["active_from"]
        # … but both use the region-only key on the SAME condition_id → one market row.
        assert k1["dedup_by_region_only"] is True
        assert k2["dedup_by_region_only"] is True
        assert k1["region"] == k2["region"] == _CONDITION_ID

    def test_legacy_no_condition_id_keeps_date_based_key(self) -> None:
        """No external_id → dedup_by_region_only=False (legacy anonymous docs stay distinct)."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))
        assert event_repo.upsert_by_natural_key.call_args.kwargs["dedup_by_region_only"] is False

    def test_malformed_external_id_falls_back_to_anonymous(self) -> None:
        """A malformed external_id → old anonymous behaviour (region='prediction', doc_id title)."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(None, _make_message(external_id="not-a-polymarket-id"), {}),
            )

        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["region"] == "prediction"
        assert kwargs["title"] == f"Prediction market {_DOC_ID}"

    def test_idempotent_per_condition_id_across_distinct_docs(self) -> None:
        """First-sight + resolution docs (distinct doc_ids, same market) collapse to ONE key.

        The two synthetic docs of a market have DIFFERENT doc_ids but the SAME
        condition_id; keying region+title on the condition_id makes the natural
        key identical, so the repo upsert is idempotent per market.
        """
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        ext = f"polymarket:{_CONDITION_ID}"
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(None, _make_message(doc_id=_DOC_ID, external_id=ext), {}),
            )
            other_doc = "01920000-0000-7000-8000-0000000000dd"
            asyncio.run(
                consumer.process_message(None, _make_message(doc_id=other_doc, external_id=ext), {}),
            )

        first = event_repo.upsert_by_natural_key.call_args_list[0].kwargs
        second = event_repo.upsert_by_natural_key.call_args_list[1].kwargs
        # Same market → identical natural-key components despite different doc_ids.
        assert first["region"] == second["region"] == _CONDITION_ID
        assert first["title"] == second["title"] == f"Prediction market {_CONDITION_ID}"


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


class _FakeKafkaMessage:
    """Minimal confluent-Kafka message stand-in for ``_handle_message`` tests."""

    def __init__(self, raw_value: bytes, *, offset: int = 42, partition: int = 0) -> None:
        self._value = raw_value
        self._offset = offset
        self._partition = partition

    def topic(self) -> str:
        return "nlp.article.enriched.v1"

    def value(self) -> bytes:
        return self._value

    def key(self) -> bytes | None:
        return None

    def headers(self) -> list[tuple[str, bytes]]:
        return []

    def offset(self) -> int:
        return self._offset

    def partition(self) -> int:
        return self._partition


class TestPredictionEnrichedConsumerResilientDeserialize:
    """PLAN-0056 deploy-fix: an un-decodable record must be SKIPPED, not crash-loop.

    The base ``_handle_message`` raises ``MalformedDataError`` (a ``FatalError``) on a
    deserialize failure — e.g. an old-schema record on the shared
    ``nlp.article.enriched.v1`` topic misaligning under the new no-registry reader
    schema. A burst of those trips ``dead_letter_cap`` → forced restart forever. The
    override swallows the deserialize failure so the poison record is skipped (offset
    advances in the run loop).
    """

    def test_undecodable_record_is_skipped_not_raised(self) -> None:
        consumer, _, _, _ = _make_consumer()
        # Confluent magic byte (0x00) + garbage that no Avro reader can decode →
        # deserialize_confluent_avro raises → base wraps in MalformedDataError.
        msg = _FakeKafkaMessage(b"\x00\x00\x00\x00\x01garbage-not-avro")
        # Must NOT raise (a single poison message can never wedge the consumer).
        asyncio.run(consumer._handle_message(msg))

    def test_malformed_data_error_from_deserialize_is_swallowed(self) -> None:
        from messaging.kafka.consumer.errors import MalformedDataError  # type: ignore[import-untyped]

        consumer, _, _, _ = _make_consumer()
        msg = _FakeKafkaMessage(b"\x00bad")
        # Recurrence-1 structural fix (2026-07-23 bottleneck audit / BP-736):
        # the skip-and-advance behaviour now lives in
        # ``BaseKafkaConsumer._handle_message`` itself and is DELIBERATELY
        # SCOPED to decode-poison exception shapes only —
        # ``(MalformedDataError, EOFError, struct.error)`` — not to
        # ``Exception`` at large. Previously this consumer's own
        # ``_handle_message`` override caught the base's WRAPPED
        # ``MalformedDataError`` regardless of the original exception type,
        # so ANY bug inside ``deserialize_value`` (including a genuine
        # business-logic ``ValueError`` unrelated to decode-poison) was
        # silently swallowed — too broad. The base class intentionally
        # tightens this: only a genuine decode-poison shape is skipped;
        # other exceptions still propagate (wrapped as ``MalformedDataError``)
        # so a real bug is not masked. Use ``EOFError`` here (the canonical
        # decode-poison shape, matching a truncated/misaligned Avro read) to
        # exercise the swallow path this test's name promises.
        with patch.object(consumer, "deserialize_value", side_effect=EOFError("short read")):
            asyncio.run(consumer._handle_message(msg))
        # Sanity: the base really does classify a raw decode failure as MalformedDataError.
        assert issubclass(MalformedDataError, Exception)

    def test_json_fallback_logs_warning_r28(self) -> None:
        """R28 (FIX 4): the non-Avro (plain JSON) decode path logs a warning."""
        import knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer as mod

        consumer, _, _, _ = _make_consumer()
        raw = b'{"event_id": "x", "source_type": "eodhd"}'  # no 0x00 magic byte → JSON path
        with patch.object(mod.logger, "warning") as warn:
            decoded = consumer.deserialize_value(raw)
        assert decoded["source_type"] == "eodhd"
        warn.assert_called_once()
        assert warn.call_args.args[0] == "prediction_enriched_consumer_json_fallback"

    def test_non_deserialize_exception_still_propagates(self) -> None:
        """Only deserialize failures are swallowed — genuine processing errors bubble up."""
        consumer, _event_repo, _exposure_repo, _ = _make_consumer()
        good_value = _make_message()
        msg = _FakeKafkaMessage(b"\x00whatever")
        # deserialize_value succeeds, but process_message blows up with a non-Malformed
        # error → must propagate (so the retry/DLQ path still handles real failures).
        with (
            patch.object(consumer, "deserialize_value", return_value=good_value),
            patch.object(consumer, "process_message", side_effect=RuntimeError("db down")),
        ):
            with pytest.raises(RuntimeError, match="db down"):
                asyncio.run(consumer._handle_message(msg))


# ── PLAN-0056 Wave C3: source_title question + polarity classification ────────

_CANONICAL_ENTITY_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity.CanonicalEntityRepository"
)
_QUESTION = "Will Company X miss Q3 earnings?"


class _FakeClassifier:
    """Async stand-in for MarketPolarityClassifier (no LLM)."""

    def __init__(self, verdict: tuple[str, float] = ("bullish", 0.9)) -> None:
        self._verdict = verdict
        self.calls: list[dict[str, Any]] = []

    async def classify(
        self,
        question: str,
        entity_name: str,
        outcomes: list[str] | None = None,
        *,
        condition_id: str | None = None,
        entity_id: Any = None,
    ) -> tuple[str, float]:
        self.calls.append(
            {"question": question, "entity_name": entity_name, "condition_id": condition_id, "entity_id": entity_id},
        )
        return self._verdict


def _make_consumer_with_classifier(
    classifier: Any,
) -> tuple[Any, Any, Any, Any]:
    """Build a consumer wired with a polarity classifier (else identical to _make_consumer)."""
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

    consumer = PredictionEnrichedConsumer(config=config, session_factory=sf, polarity_classifier=classifier)
    return consumer, event_repo, exposure_repo, session


def _canonical_repo_returning(name: str | None) -> Any:
    """A CanonicalEntityRepository mock whose .get() returns a row with canonical_name."""
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=({"canonical_name": name} if name is not None else None))
    return repo


class TestPredictionEnrichedConsumerSourceTitle:
    def test_source_title_becomes_event_title(self) -> None:
        """When source_title (the question) is present it titles the temporal event."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}", source_title=_QUESTION),
                    {},
                ),
            )
        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["title"] == _QUESTION
        assert kwargs["region"] == _CONDITION_ID

    def test_blank_source_title_falls_back_to_placeholder(self) -> None:
        """A whitespace-only source_title → the anonymous placeholder title."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}", source_title="   "),
                    {},
                ),
            )
        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["title"] == f"Prediction market {_CONDITION_ID}"

    def test_no_classifier_keeps_null_polarity_even_with_question(self) -> None:
        """source_title present but NO classifier wired → title=question, polarity NULL."""
        consumer, event_repo, exposure_repo, _ = _make_consumer()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(source_title=_QUESTION), {}))
        for call in exposure_repo.upsert.call_args_list:
            assert call.kwargs["polarity"] is None
            assert call.kwargs["polarity_confidence"] is None


class TestPredictionEnrichedConsumerPolarity:
    def test_classifier_polarity_written_to_exposure(self) -> None:
        """Classifier verdict is written onto each exposure (polarity + confidence)."""
        classifier = _FakeClassifier(("bearish", 0.77))
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_classifier(classifier)
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_CANONICAL_ENTITY_REPO, return_value=_canonical_repo_returning("Company X")),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}", source_title=_QUESTION),
                    {},
                ),
            )
        assert exposure_repo.upsert.await_count == 2
        for call in exposure_repo.upsert.call_args_list:
            assert call.kwargs["polarity"] == "bearish"
            assert call.kwargs["polarity_confidence"] == pytest.approx(0.77)
        # The classifier was called with the question + the resolved entity name.
        assert classifier.calls
        assert classifier.calls[0]["question"] == _QUESTION
        assert classifier.calls[0]["entity_name"] == "Company X"
        assert classifier.calls[0]["condition_id"] == _CONDITION_ID

    def test_no_question_skips_classification(self) -> None:
        """Classifier wired but NO source_title → classifier never called, polarity NULL."""
        classifier = _FakeClassifier(("bullish", 0.9))
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_classifier(classifier)
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_CANONICAL_ENTITY_REPO, return_value=_canonical_repo_returning("Company X")),
        ):
            asyncio.run(consumer.process_message(None, _make_message(external_id=f"polymarket:{_CONDITION_ID}"), {}))
        assert classifier.calls == []
        for call in exposure_repo.upsert.call_args_list:
            assert call.kwargs["polarity"] is None

    def test_unresolvable_entity_name_leaves_null_polarity(self) -> None:
        """Entity whose canonical name cannot be resolved → exposure keeps NULL polarity."""
        classifier = _FakeClassifier(("bullish", 0.9))
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_classifier(classifier)
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_CANONICAL_ENTITY_REPO, return_value=_canonical_repo_returning(None)),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(
                        external_id=f"polymarket:{_CONDITION_ID}",
                        source_title=_QUESTION,
                        resolved_entity_ids=[_ENTITY_A],
                    ),
                    {},
                ),
            )
        assert classifier.calls == []  # no name → never classified
        assert exposure_repo.upsert.call_args.kwargs["polarity"] is None

    def test_classifier_exception_does_not_block_ingestion(self) -> None:
        """A classifier that raises must not stop the exposure write (polarity NULL)."""

        class _BoomClassifier:
            async def classify(self, *args: Any, **kwargs: Any) -> tuple[str, float]:
                raise RuntimeError("llm down")

        consumer, event_repo, exposure_repo, session = _make_consumer_with_classifier(_BoomClassifier())
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_CANONICAL_ENTITY_REPO, return_value=_canonical_repo_returning("Company X")),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(
                        external_id=f"polymarket:{_CONDITION_ID}",
                        source_title=_QUESTION,
                        resolved_entity_ids=[_ENTITY_A],
                    ),
                    {},
                ),
            )
        # Event + exposure still written and committed; polarity fell back to NULL.
        event_repo.upsert_by_natural_key.assert_awaited_once()
        assert exposure_repo.upsert.call_args.kwargs["polarity"] is None
        session.commit.assert_awaited_once()


# ── PLAN-0056 Wave D2: new_market + resolution signal wiring ──────────────────

_OUTBOX_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.outbox.OutboxRepository"


def _make_consumer_with_emitter(
    *,
    emit_new_market: bool = True,
) -> tuple[Any, Any, Any, Any]:
    """Build a consumer wired with a REAL PredictionSignalEmitter (Wave D2).

    Returns (consumer, event_repo, exposure_repo, session). The OutboxRepository is
    patched by the caller so ``emit`` writes to a mock outbox.
    """
    from knowledge_graph.application.services.prediction_signal_emitter import (
        PredictionSignalEmitter,
    )
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

    emitter = PredictionSignalEmitter(emit_new_market=emit_new_market)
    consumer = PredictionEnrichedConsumer(config=config, session_factory=sf, signal_emitter=emitter)
    return consumer, event_repo, exposure_repo, session


class TestPredictionEnrichedConsumerSignalWiring:
    def test_first_sight_doc_emits_new_market_signals(self) -> None:
        """A first-sight polymarket doc → one new_market signal per exposure."""
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_emitter()
        outbox = AsyncMock(append=AsyncMock())
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=outbox),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}"),
                    {},
                ),
            )
        # Two resolved entities → two new_market signals.
        assert outbox.append.await_count == 2

    def test_new_market_gate_off_emits_no_signals(self) -> None:
        """With the new_market gate off, a first-sight doc emits no signals."""
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_emitter(emit_new_market=False)
        outbox = AsyncMock(append=AsyncMock())
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=outbox),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}"),
                    {},
                ),
            )
        outbox.append.assert_not_awaited()

    def test_resolution_doc_emits_resolution_signals(self) -> None:
        """A ':resolved' external_id → resolution-trigger signals (gate is new_market-only)."""
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_emitter(emit_new_market=False)
        outbox = AsyncMock(append=AsyncMock())
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=outbox),
        ):
            asyncio.run(
                consumer.process_message(
                    None,
                    _make_message(external_id=f"polymarket:{_CONDITION_ID}:resolved"),
                    {},
                ),
            )
        # Resolution is NOT gated by the new_market flag → still emits 2.
        assert outbox.append.await_count == 2
        # region still keys on the bare condition_id (suffix stripped).
        assert event_repo.upsert_by_natural_key.call_args.kwargs["region"] == _CONDITION_ID

    def test_legacy_doc_without_condition_id_emits_no_signals(self) -> None:
        """No external_id (anonymous market) → no market_id → no signals."""
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_emitter()
        outbox = AsyncMock(append=AsyncMock())
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=outbox),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))
        outbox.append.assert_not_awaited()

    def test_signal_emission_idempotent_across_redelivery(self) -> None:
        """Re-delivering the same first-sight doc uses the SAME outbox event_id per entity."""
        consumer, event_repo, exposure_repo, _ = _make_consumer_with_emitter()
        outbox = AsyncMock(append=AsyncMock())
        msg = _make_message(external_id=f"polymarket:{_CONDITION_ID}", resolved_entity_ids=[_ENTITY_A])
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_OUTBOX_REPO, return_value=outbox),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))
            asyncio.run(consumer.process_message(None, msg, {}))
        assert outbox.append.await_count == 2
        first_id = outbox.append.call_args_list[0].kwargs["event_id"]
        second_id = outbox.append.call_args_list[1].kwargs["event_id"]
        assert first_id == second_id

    def test_resolution_external_id_detected(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.prediction_enriched_consumer import (
            _is_resolution_external_id,
            _parse_condition_id,
        )

        assert _is_resolution_external_id(f"polymarket:{_CONDITION_ID}:resolved") is True
        assert _is_resolution_external_id(f"polymarket:{_CONDITION_ID}") is False
        assert _is_resolution_external_id(None) is False
        # The bare condition_id is recovered (suffix stripped) for BOTH docs.
        assert _parse_condition_id(f"polymarket:{_CONDITION_ID}:resolved") == _CONDITION_ID
