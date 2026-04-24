"""Unit tests for EconomicEventsDatasetConsumer (Consumer 13D-6).

Replaces the former test_economic_events_worker.py.
Tests cover:
- Happy path: valid economic_events message is processed end-to-end.
- Filter: non-economic_events dataset_type is silently skipped.
- Empty/missing payload: no DB calls made.
- Storage failure: handled gracefully, no crash.
- Date parsing: valid and invalid date strings.
- Business logic: unreleased events (actual=None) skipped; surprise magnitude computed.
- Country extraction from symbol.
- Missing country entity: event still upserted; exposure skipped.
- Prometheus counter increment.
- is_duplicate / mark_processed dedup flow.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.unit

_COUNTRY_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000001")
_DB_EVENT_ID = UUID("01910000-0000-7000-8000-000000000002")
_EXPOSURE_ID = UUID("01910000-0000-7000-8000-000000000003")

# Patch paths for repositories lazily imported inside the consumer
_TEMPORAL_EVENT_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.TemporalEventRepository"
)
_EXPOSURE_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.EntityEventExposureRepository"  # noqa: E501
_ENTITY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository.EntityRepository"

# Minimal released economic event dict (from EODHD)
_RELEASED_EVENT: dict[str, Any] = {
    "date": "2026-04-07T00:00:00",
    "type": "CPI m/m",
    "period": "Mar 2026",
    "actual": 0.3,
    "estimate": 0.2,
    "previous": 0.4,
    "change_percentage": 50.0,
    "country": "US",
}

# Unreleased event (actual=None — not yet published)
_UNRELEASED_EVENT: dict[str, Any] = {
    "date": "2026-04-08",
    "type": "PPI m/m",
    "period": "Mar 2026",
    "actual": None,
    "estimate": 0.2,
    "previous": 0.1,
    "country": "US",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_consumer(
    country_entity_id: UUID | None = _COUNTRY_ENTITY_ID,
    storage_bytes: bytes | None = None,
    storage_error: Exception | None = None,
) -> tuple[Any, Any, Any, Any]:
    """Build EconomicEventsDatasetConsumer with mocked dependencies.

    Returns:
        (consumer, event_repo_mock, exposure_repo_mock, entity_repo_mock)
    """
    from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
        EconomicEventsDatasetConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-economic-events-test",
        topics=["market.dataset.fetched"],
    )

    # Session factory mock
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session

    # Storage client mock
    storage = AsyncMock()
    if storage_error is not None:
        storage.get_bytes = AsyncMock(side_effect=storage_error)
    elif storage_bytes is not None:
        storage.get_bytes = AsyncMock(return_value=storage_bytes)

    # Repository mocks
    event_repo = AsyncMock()
    event_repo.upsert_by_natural_key = AsyncMock(return_value=_DB_EVENT_ID)

    exposure_repo = AsyncMock()
    exposure_repo.upsert = AsyncMock(return_value=_EXPOSURE_ID)

    entity_repo = AsyncMock()
    entity_repo.find_country_entity = AsyncMock(return_value=country_entity_id)

    consumer = EconomicEventsDatasetConsumer(
        config=config,
        session_factory=sf,
        storage_client=storage,
    )

    return consumer, event_repo, exposure_repo, entity_repo


def _make_envelope(events: list[dict[str, Any]], symbol: str = "EVENTS.US") -> bytes:
    """Build the canonical NDJSON envelope bytes that MinIO would return."""
    envelope = {
        "dataset_type": "economic_events",
        "symbol": symbol,
        "source": "eodhd",
        "payload": events,
        "fetched_at": "2026-04-07T06:00:00+00:00",
    }
    return (json.dumps(envelope) + "\n").encode("utf-8")


def _make_message(
    symbol: str = "EVENTS.US",
    dataset_type: str = "economic_events",
    bucket: str = "canonical",
    key: str = "economic_events/us/2026-04-07.ndjson",
) -> dict[str, Any]:
    """Build a decoded Avro dict for market.dataset.fetched."""
    return {
        "event_id": str(uuid4()),
        "dataset_type": dataset_type,
        "symbol": symbol,
        "canonical_ref_bucket": bucket,
        "canonical_ref_key": key,
    }


# ── Test: filter by dataset_type ─────────────────────────────────────────────


class TestEconomicEventsConsumerFilter:
    def test_non_economic_events_type_skipped(self) -> None:
        """dataset_type != 'economic_events' → process_message returns early, no storage call."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        storage_bytes = _make_envelope([_RELEASED_EVENT])
        consumer._storage.get_bytes = AsyncMock(return_value=storage_bytes)

        msg = _make_message(dataset_type="ohlcv")
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        consumer._storage.get_bytes.assert_not_awaited()
        event_repo.upsert_by_natural_key.assert_not_awaited()

    def test_fundamentals_type_skipped(self) -> None:
        """dataset_type='fundamentals' → skipped."""
        consumer, event_repo, _, entity_repo = _make_consumer()
        msg = _make_message(dataset_type="fundamentals")
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, msg, {}))
        event_repo.upsert_by_natural_key.assert_not_awaited()


# ── Test: happy path ──────────────────────────────────────────────────────────


class TestEconomicEventsConsumerHappyPath:
    def test_released_event_upserted_with_correct_fields(self) -> None:
        """Released event → upsert_by_natural_key with MACRO type, NATIONAL scope, region=US."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_awaited_once()
        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["event_type"].value == "macro"
        assert kwargs["scope"].value == "NATIONAL"
        assert kwargs["region"] == "US"
        assert kwargs["title"] == "CPI m/m (US) — Mar 2026"
        assert kwargs["confidence"] == 1.0
        assert kwargs["residual_impact_days"] == 30

    def test_exposure_linked_to_country_entity(self) -> None:
        """After upsert, exposure link created for country entity."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        exposure_repo.upsert.assert_awaited_once()
        exp_kwargs = exposure_repo.upsert.call_args.kwargs
        assert exp_kwargs["entity_id"] == _COUNTRY_ENTITY_ID
        assert exp_kwargs["event_id"] == _DB_EVENT_ID
        assert exp_kwargs["exposure_type"].value == "directly_affected"
        assert exp_kwargs["confidence"] == 1.0

    def test_description_includes_beat_and_surprise_magnitude(self) -> None:
        """actual > estimate → description contains 'beat' and surprise value."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        desc = event_repo.upsert_by_natural_key.call_args.kwargs["description"]
        assert "beat" in desc
        assert "0.10" in desc  # surprise = 0.3 - 0.2 = 0.10

    def test_description_includes_missed_direction(self) -> None:
        """actual < estimate → description contains 'missed'."""
        missed_event = {**_RELEASED_EVENT, "actual": 0.1, "estimate": 0.3}
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([missed_event]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        desc = event_repo.upsert_by_natural_key.call_args.kwargs["description"]
        assert "missed" in desc

    def test_active_until_is_24h_after_active_from(self) -> None:
        """active_until = active_from + 24h (economic events are point-in-time)."""
        from datetime import timedelta

        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        delta = kwargs["active_until"] - kwargs["active_from"]
        assert delta == timedelta(hours=24)

    def test_session_committed_after_processing(self) -> None:
        """session.commit() is called after all events are upserted."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        session = consumer._sf.return_value
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        session.commit.assert_awaited_once()


# ── Test: unreleased events skipped ──────────────────────────────────────────


class TestEconomicEventsConsumerUnreleased:
    def test_unreleased_event_skipped(self) -> None:
        """actual=None → event skipped; upsert_by_natural_key not called."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_UNRELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()
        exposure_repo.upsert.assert_not_awaited()

    def test_mixed_released_and_unreleased(self) -> None:
        """Mix of released and unreleased → only released events upserted."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT, _UNRELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        assert event_repo.upsert_by_natural_key.await_count == 1


# ── Test: empty / missing payload ─────────────────────────────────────────────


class TestEconomicEventsConsumerEmptyPayload:
    def test_empty_payload_list_no_db_calls(self) -> None:
        """Empty payload list → no DB calls, no crash."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()

    def test_missing_bucket_no_storage_call(self) -> None:
        """Missing canonical_ref_bucket → storage not called."""
        consumer, event_repo, _, entity_repo = _make_consumer()
        msg = _make_message()
        del msg["canonical_ref_bucket"]

        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, msg, {}))

        consumer._storage.get_bytes.assert_not_awaited()
        event_repo.upsert_by_natural_key.assert_not_awaited()


# ── Test: storage errors ─────────────────────────────────────────────────────


class TestEconomicEventsConsumerStorageErrors:
    def test_storage_exception_does_not_crash(self) -> None:
        """Storage failure → process_message returns cleanly, no DB calls."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer(
            storage_error=RuntimeError("minio connection refused")
        )

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()

    def test_malformed_json_does_not_crash(self) -> None:
        """Malformed NDJSON bytes → process_message returns cleanly."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=b"not valid json {{{")

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()


# ── Test: country extraction from symbol ──────────────────────────────────────


class TestExtractCountryFromSymbol:
    def test_alpha2_symbol(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _extract_country_from_symbol,
        )

        assert _extract_country_from_symbol("EVENTS.US") == "US"

    def test_alpha3_symbol(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _extract_country_from_symbol,
        )

        assert _extract_country_from_symbol("EVENTS.USA") == "USA"

    def test_eu_symbol(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _extract_country_from_symbol,
        )

        assert _extract_country_from_symbol("EVENTS.EU") == "EU"

    def test_no_dot_returns_symbol_unchanged(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _extract_country_from_symbol,
        )

        assert _extract_country_from_symbol("EVENTS") == "EVENTS"


# ── Test: date parsing ────────────────────────────────────────────────────────


class TestParsEventDate:
    def test_iso_datetime_string(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _parse_event_date,
        )

        result = _parse_event_date("2026-04-07T00:00:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 7

    def test_date_only_string(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _parse_event_date,
        )

        result = _parse_event_date("2026-04-07")
        assert result is not None
        assert result.year == 2026

    def test_empty_string_returns_none(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _parse_event_date,
        )

        assert _parse_event_date("") is None

    def test_garbage_string_returns_none(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _parse_event_date,
        )

        assert _parse_event_date("not-a-date") is None

    def test_result_is_utc_aware(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            _parse_event_date,
        )

        result = _parse_event_date("2026-04-07T12:00:00")
        assert result is not None
        assert result.tzinfo == UTC


# ── Test: missing country entity ──────────────────────────────────────────────


class TestEconomicEventsConsumerMissingCountryEntity:
    def test_no_country_entity_still_upserts_event(self) -> None:
        """When country entity not found, event is still upserted; exposure skipped."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer(country_entity_id=None)
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_awaited_once()
        exposure_repo.upsert.assert_not_awaited()


# ── Test: invalid event date skipped ──────────────────────────────────────────


class TestEconomicEventsConsumerInvalidDate:
    def test_invalid_date_event_skipped(self) -> None:
        """Event with unparseable date → skipped; no upsert."""
        bad_date_event = {**_RELEASED_EVENT, "date": "not-a-date"}
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([bad_date_event]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()


# ── Test: Prometheus counter ──────────────────────────────────────────────────


class TestEconomicEventsConsumerPrometheus:
    def test_prometheus_counter_incremented_on_ingestion(self) -> None:
        """s7_economic_events_ingested_total{country='US'} incremented for each upserted event."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_economic_events_ingested_total

        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        before = s7_economic_events_ingested_total.labels(country="US")._value.get()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(symbol="EVENTS.US"), {}))
        after = s7_economic_events_ingested_total.labels(country="US")._value.get()

        assert after - before == 1.0

    def test_prometheus_counter_not_incremented_for_unreleased(self) -> None:
        """No increment when all events are unreleased."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_economic_events_ingested_total

        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_UNRELEASED_EVENT]))

        before = s7_economic_events_ingested_total.labels(country="US")._value.get()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))
        after = s7_economic_events_ingested_total.labels(country="US")._value.get()

        assert after == before


# ── Test: dedup infrastructure ────────────────────────────────────────────────


class TestEconomicEventsConsumerDedup:
    def test_is_duplicate_returns_false_without_dedup_client(self) -> None:
        """is_duplicate always returns False when dedup_client is None."""
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            EconomicEventsDatasetConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics=["market.dataset.fetched"],
        )
        sf = MagicMock()
        consumer = EconomicEventsDatasetConsumer(config=config, session_factory=sf)
        result = asyncio.run(consumer.is_duplicate("evt-123"))
        assert result is False

    def test_extract_event_id_returns_event_id_field(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer import (
            EconomicEventsDatasetConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics=["market.dataset.fetched"],
        )
        sf = MagicMock()
        consumer = EconomicEventsDatasetConsumer(config=config, session_factory=sf)
        eid = consumer.extract_event_id({"event_id": "abc-123"})
        assert eid == "abc-123"
