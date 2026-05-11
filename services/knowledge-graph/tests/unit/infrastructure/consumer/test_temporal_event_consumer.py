"""Unit tests for TemporalEventConsumer (Wave C-2 — PRD-0018 §6.5).

Covers:
- Avro message fields correctly mapped to TemporalEventRepository.upsert_by_natural_key
- region="" → None conversion (PRD §6.5 Avro contract)
- active_until="" → None conversion
- source_url="" → None conversion
- description="" → None conversion
- GLOBAL scope: sector/industry entities are linked; company entities are skipped
- Non-GLOBAL scope: all exposed_entities are linked without entity_type check
- Empty exposed_entities: no entity_event_exposure rows created
- Valkey dedup: is_duplicate returns True → process_message not called by caller
- DLQ: dead_letter / store_failure / update_failure log correctly
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_EVENT_ID = str(uuid4())
_SECTOR_ENTITY_ID = str(uuid4())
_COMPANY_ENTITY_ID = str(uuid4())
_INDUSTRY_ENTITY_ID = str(uuid4())

_BASE_ACTIVE_FROM = "2024-01-15T00:00:00+00:00"


def _make_message(
    *,
    event_id: str = _EVENT_ID,
    temporal_event_type: str = "geopolitical",
    scope: str = "NATIONAL",
    region: str = "US",
    title: str = "US Tariffs on Chinese Goods",
    description: str = "Escalating trade tensions between US and China",
    source_article_ids: list[str] | None = None,
    source_url: str = "https://reuters.com/article/tariffs",
    active_from: str = _BASE_ACTIVE_FROM,
    active_until: str = "",
    residual_impact_days: int = 90,
    confidence: float = 0.85,
    exposed_entities: list[dict] | None = None,
) -> dict:
    """Build a decoded Avro message dict (post-deserialisation)."""
    return {
        "event_id": event_id,
        "event_type": "intelligence.temporal_event",
        "schema_version": 1,
        "occurred_at": "2024-01-15T08:22:10+00:00",
        "temporal_event_type": temporal_event_type,
        "scope": scope,
        "region": region,
        "title": title,
        "description": description,
        "source_article_ids": source_article_ids or [],
        "source_url": source_url,
        "active_from": active_from,
        "active_until": active_until,
        "residual_impact_days": residual_impact_days,
        "confidence": confidence,
        "exposed_entities": exposed_entities or [],
    }


def _make_consumer(dedup_client: object | None = None):
    """Build TemporalEventConsumer with mocked session factory."""
    from knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer import TemporalEventConsumer

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-temporal-event-test",
        topics=["intelligence.temporal_event.v1"],
    )

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    sf = MagicMock()
    sf.return_value = session

    consumer = TemporalEventConsumer(config=config, session_factory=sf, dedup_client=dedup_client)
    return consumer, sf, session


# ---------------------------------------------------------------------------
# Tests: core Avro field mapping
# ---------------------------------------------------------------------------


class TestTemporalEventConsumerMessageMapping:
    """Verify Avro field values flow correctly to TemporalEventRepository."""

    def test_basic_message_upserts_temporal_event(self) -> None:
        """Happy path: decoded Avro message → upsert_by_natural_key called with correct args."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message()
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_te.upsert_by_natural_key.assert_awaited_once()
        call_kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        assert call_kwargs["event_id"] == UUID(msg["event_id"])
        assert call_kwargs["event_type"] == "geopolitical"
        assert call_kwargs["scope"] == "NATIONAL"
        assert call_kwargs["region"] == "US"
        assert call_kwargs["title"] == msg["title"]
        assert call_kwargs["confidence"] == pytest.approx(0.85)

    def test_active_from_parsed_as_utc_datetime(self) -> None:
        """active_from ISO-8601 string is correctly parsed to a timezone-aware datetime."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message(active_from="2024-06-01T12:00:00+00:00")
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            asyncio.run(consumer.process_message(None, msg, {}))

        kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        af = kwargs["active_from"]
        assert af.year == 2024
        assert af.month == 6
        assert af.day == 1
        assert af.tzinfo is not None
        assert af.tzinfo == UTC or af.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    def test_source_article_ids_passed_as_list(self) -> None:
        """source_article_ids list of UUID strings is forwarded to the repository."""
        consumer, _sf, _session = _make_consumer()
        article_ids = [str(uuid4()), str(uuid4())]
        msg = _make_message(source_article_ids=article_ids)
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            asyncio.run(consumer.process_message(None, msg, {}))

        kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        assert kwargs["source_article_ids"] == article_ids


# ---------------------------------------------------------------------------
# Tests: empty-string → None conversions (PRD §6.5 Avro contract)
# ---------------------------------------------------------------------------


class TestTemporalEventConsumerEmptyStringConversions:
    """Verify Avro empty-string sentinels are converted to None before DB write."""

    def test_region_empty_string_becomes_none(self) -> None:
        """region='' → repository called with region=None."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message(region="")
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            asyncio.run(consumer.process_message(None, msg, {}))

        kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        assert kwargs["region"] is None

    def test_active_until_empty_string_becomes_none(self) -> None:
        """active_until='' → repository called with active_until=None (ongoing event)."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message(active_until="")
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            asyncio.run(consumer.process_message(None, msg, {}))

        kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        assert kwargs["active_until"] is None

    def test_active_until_non_empty_is_parsed(self) -> None:
        """active_until with a valid timestamp is parsed to a datetime."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message(active_until="2024-12-31T23:59:59+00:00")
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            asyncio.run(consumer.process_message(None, msg, {}))

        kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        assert kwargs["active_until"] is not None
        assert kwargs["active_until"].year == 2024

    def test_description_empty_string_becomes_none(self) -> None:
        """description='' → repository called with description=None."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message(description="")
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            asyncio.run(consumer.process_message(None, msg, {}))

        kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        assert kwargs["description"] is None

    def test_source_url_empty_string_becomes_none(self) -> None:
        """source_url='' → repository called with source_url=None."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message(source_url="")
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            asyncio.run(consumer.process_message(None, msg, {}))

        kwargs = mock_te.upsert_by_natural_key.call_args.kwargs
        assert kwargs["source_url"] is None


# ---------------------------------------------------------------------------
# Tests: exposure creation (non-GLOBAL scope)
# ---------------------------------------------------------------------------


class TestTemporalEventConsumerExposures:
    """Verify entity_event_exposures rows are correctly created."""

    def test_national_scope_creates_exposures_for_all_entities(self) -> None:
        """NATIONAL scope: every entity in exposed_entities gets an exposure row."""
        consumer, _sf, _session = _make_consumer()
        entities = [
            {"entity_id": str(uuid4()), "exposure_type": "revenue_geography", "confidence": 0.8},
            {"entity_id": str(uuid4()), "exposure_type": "directly_affected", "confidence": 0.9},
        ]
        msg = _make_message(scope="NATIONAL", exposed_entities=entities)
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        assert mock_ee.upsert.await_count == 2

    def test_local_scope_creates_all_exposures_without_type_check(self) -> None:
        """LOCAL scope: no entity_type DB query; all entities are linked."""
        consumer, _sf, _session = _make_consumer()
        entities = [
            {"entity_id": str(uuid4()), "exposure_type": "directly_affected", "confidence": 0.95},
        ]
        msg = _make_message(scope="LOCAL", region="", exposed_entities=entities)
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer._get_entity_type"
            ) as mock_get_type,
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        # No entity type lookup for non-GLOBAL scopes
        mock_get_type.assert_not_called()
        mock_ee.upsert.assert_awaited_once()

    def test_empty_exposed_entities_no_exposures_created(self) -> None:
        """Empty exposed_entities[] → no entity_event_exposures rows."""
        consumer, _sf, _session = _make_consumer()
        msg = _make_message(exposed_entities=[])
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_ee.upsert.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: GLOBAL scope sector-only linking (PRD-0018 §6.2)
# ---------------------------------------------------------------------------


class TestTemporalEventConsumerGlobalScope:
    """GLOBAL-scope events must only link sector/industry canonical entities."""

    def test_global_scope_sector_entity_is_linked(self) -> None:
        """GLOBAL + entity_type='sector' → exposure row created."""
        consumer, _sf, _session = _make_consumer()
        sector_id = str(uuid4())
        entities = [{"entity_id": sector_id, "exposure_type": "sector_exposure", "confidence": 1.0}]
        msg = _make_message(scope="GLOBAL", region="GLOBAL", exposed_entities=entities)
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer._get_entity_type",
                new=AsyncMock(return_value="sector"),
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_ee.upsert.assert_awaited_once()
        upsert_kwargs = mock_ee.upsert.call_args.kwargs
        assert upsert_kwargs["entity_id"] == UUID(sector_id)

    def test_global_scope_industry_entity_is_linked(self) -> None:
        """GLOBAL + entity_type='industry_group' → exposure row created.

        Seeded GICS entities use entity_type='industry_group' (not 'industry').
        _GLOBAL_ALLOWED_ENTITY_TYPES must include 'industry_group'.
        """
        consumer, _sf, _session = _make_consumer()
        industry_id = str(uuid4())
        entities = [{"entity_id": industry_id, "exposure_type": "sector_exposure", "confidence": 0.9}]
        msg = _make_message(scope="GLOBAL", region="GLOBAL", exposed_entities=entities)
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer._get_entity_type",
                new=AsyncMock(return_value="industry_group"),
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_ee.upsert.assert_awaited_once()

    def test_global_scope_company_entity_is_skipped(self) -> None:
        """GLOBAL + entity_type='company' → exposure row NOT created."""
        consumer, _sf, _session = _make_consumer()
        company_id = str(uuid4())
        entities = [{"entity_id": company_id, "exposure_type": "directly_affected", "confidence": 0.7}]
        msg = _make_message(scope="GLOBAL", region="GLOBAL", exposed_entities=entities)
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer._get_entity_type",
                new=AsyncMock(return_value="company"),
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_ee.upsert.assert_not_awaited()

    def test_global_scope_unknown_entity_is_skipped(self) -> None:
        """GLOBAL + entity not found (entity_type=None) → exposure NOT created."""
        consumer, _sf, _session = _make_consumer()
        unknown_id = str(uuid4())
        entities = [{"entity_id": unknown_id, "exposure_type": "sector_exposure", "confidence": 0.5}]
        msg = _make_message(scope="GLOBAL", region="GLOBAL", exposed_entities=entities)
        returned_event_id = UUID(str(uuid4()))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer._get_entity_type",
                new=AsyncMock(return_value=None),
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        mock_ee.upsert.assert_not_awaited()

    def test_global_scope_mixed_entities_only_sector_linked(self) -> None:
        """GLOBAL + mixed entity types → only sector/industry get exposures."""
        consumer, _sf, _session = _make_consumer()
        sector_id = str(uuid4())
        company_id = str(uuid4())
        industry_id = str(uuid4())
        entities = [
            {"entity_id": sector_id, "exposure_type": "sector_exposure", "confidence": 1.0},
            {"entity_id": company_id, "exposure_type": "directly_affected", "confidence": 0.8},
            {"entity_id": industry_id, "exposure_type": "sector_exposure", "confidence": 0.9},
        ]
        msg = _make_message(scope="GLOBAL", region="GLOBAL", exposed_entities=entities)
        returned_event_id = UUID(str(uuid4()))

        # Seeded GICS entities use 'industry_group', not 'industry'
        entity_types: dict[str, str] = {
            sector_id: "sector",
            company_id: "company",
            industry_id: "industry_group",
        }

        async def _mock_get_entity_type(_session: object, entity_id: UUID) -> str | None:
            return entity_types.get(str(entity_id))

        with (
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.TemporalEventRepository"
            ) as MockTE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer.EntityEventExposureRepository"
            ) as MockEE,
            patch(
                "knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer._get_entity_type",
                new=_mock_get_entity_type,
            ),
        ):
            mock_te = AsyncMock()
            mock_te.upsert_by_natural_key = AsyncMock(return_value=returned_event_id)
            MockTE.return_value = mock_te

            mock_ee = AsyncMock()
            MockEE.return_value = mock_ee

            asyncio.run(consumer.process_message(None, msg, {}))

        # Only sector + industry_group (2) — company is rejected
        assert mock_ee.upsert.await_count == 2
        linked_ids = {call.kwargs["entity_id"] for call in mock_ee.upsert.call_args_list}
        assert UUID(sector_id) in linked_ids
        assert UUID(industry_id) in linked_ids
        assert UUID(company_id) not in linked_ids


# ---------------------------------------------------------------------------
# Tests: idempotency via Valkey dedup
# ---------------------------------------------------------------------------


class TestTemporalEventConsumerIdempotency:
    """Valkey dedup prevents duplicate processing (BP-124)."""

    def test_is_duplicate_false_when_no_dedup_client(self) -> None:
        """Without Valkey, is_duplicate always returns False."""
        consumer, _sf, _session = _make_consumer(dedup_client=None)
        result = asyncio.run(consumer.is_duplicate("test-id"))
        assert result is False

    def test_is_duplicate_checks_valkey_key(self) -> None:
        """With Valkey, is_duplicate calls exists() with the correct prefixed key."""
        dedup_client = AsyncMock()
        dedup_client.exists = AsyncMock(return_value=True)
        consumer, _sf, _session = _make_consumer(dedup_client=dedup_client)

        result = asyncio.run(consumer.is_duplicate("abc123"))
        assert result is True
        dedup_client.exists.assert_awaited_once_with("kg:dedup:temporal:kg-temporal-event-test:abc123")

    def test_mark_processed_sets_valkey_key_with_ttl(self) -> None:
        """mark_processed sets a 24h TTL key in Valkey."""
        dedup_client = AsyncMock()
        dedup_client.set = AsyncMock()
        consumer, _sf, _session = _make_consumer(dedup_client=dedup_client)

        asyncio.run(consumer.mark_processed("evt-xyz"))
        dedup_client.set.assert_awaited_once_with("kg:dedup:temporal:kg-temporal-event-test:evt-xyz", "1", ex=86400)

    def test_mark_processed_noop_without_dedup_client(self) -> None:
        """mark_processed is a no-op when dedup_client is None."""
        consumer, _sf, _session = _make_consumer(dedup_client=None)
        # Must not raise
        asyncio.run(consumer.mark_processed("evt-abc"))


# ---------------------------------------------------------------------------
# Tests: DLQ / failure tracking
# ---------------------------------------------------------------------------


class TestTemporalEventConsumerDLQ:
    """Verify DLQ / failure lifecycle hooks log correctly and return expected values."""

    def test_store_failure_returns_none(self) -> None:
        """store_failure logs error and returns None (DLQ record type is None)."""
        from messaging.kafka.consumer.base import FailureInfo  # type: ignore[import-untyped]

        consumer, _sf, _session = _make_consumer()
        failure = FailureInfo(
            event_id="evt-fail",
            topic="intelligence.temporal_event.v1",
            partition=0,
            offset=10,
            attempt=1,
            last_error=RuntimeError("db down"),
        )
        result = asyncio.run(consumer.store_failure(failure))
        assert result is None

    def test_dead_letter_does_not_raise(self) -> None:
        """dead_letter logs the final failure without raising."""
        from messaging.kafka.consumer.base import FailureInfo  # type: ignore[import-untyped]

        consumer, _sf, _session = _make_consumer()
        failure = FailureInfo(
            event_id="evt-dlq",
            topic="intelligence.temporal_event.v1",
            partition=0,
            offset=99,
            attempt=5,
            last_error=ValueError("permanent error"),
        )
        asyncio.run(consumer.dead_letter(failure))

    def test_get_pending_retries_returns_empty(self) -> None:
        """get_pending_retries returns [] — no retry state persisted."""
        consumer, _sf, _session = _make_consumer()
        result = asyncio.run(consumer.get_pending_retries())
        assert result == []


# ---------------------------------------------------------------------------
# Tests: serialization helpers
# ---------------------------------------------------------------------------


class TestTemporalEventConsumerSerialization:
    """Verify deserialize_value and get_schema_path."""

    def test_get_schema_path_returns_path_for_topic(self) -> None:
        """get_schema_path returns a path string for the temporal event topic."""
        consumer, _sf, _session = _make_consumer()
        path = consumer.get_schema_path("intelligence.temporal_event.v1")
        assert path is not None
        assert "intelligence.temporal_event.v1.avsc" in path

    def test_get_schema_path_returns_none_for_unknown_topic(self) -> None:
        """get_schema_path returns None for unrecognised topics."""
        consumer, _sf, _session = _make_consumer()
        assert consumer.get_schema_path("some.other.topic") is None

    def test_extract_event_id_returns_event_id_field(self) -> None:
        """extract_event_id reads the event_id field from the decoded message."""
        consumer, _sf, _session = _make_consumer()
        value = {"event_id": "test-uuid-value", "other": "data"}
        assert consumer.extract_event_id(value) == "test-uuid-value"

    def test_deserialize_value_falls_back_to_json_for_non_avro(self) -> None:
        """Non-Avro bytes (no magic 0x00) are parsed as JSON."""
        consumer, _sf, _session = _make_consumer()
        raw = b'{"event_id": "abc", "confidence": 0.9}'
        result = consumer.deserialize_value(raw, schema_path=None)
        assert result["event_id"] == "abc"
