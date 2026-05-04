"""Unit tests for EarningsCalendarDatasetConsumer (Consumer 13D-9).

Tests cover:
- Happy path: valid earnings_calendar message is processed end-to-end.
- Filter: non-earnings_calendar dataset_type is silently skipped.
- Skip: epsEstimate=None (tentative event) is skipped.
- Empty/missing payload: no DB calls made.
- Storage failure: transient errors propagate; malformed JSON is swallowed.
- Date parsing: valid and invalid date strings.
- Title building: BMO/AMC timing codes, missing name fallback.
- Missing entity: event still upserted; exposure skipped.
- Prometheus counter increment per ticker.
- is_duplicate / mark_processed dedup flow.
- EventType.CORPORATE enum value.

PLAN-0068 Wave A-1.
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

_COMPANY_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000001")
_DB_EVENT_ID = UUID("01910000-0000-7000-8000-000000000002")
_EXPOSURE_ID = UUID("01910000-0000-7000-8000-000000000003")

# Patch paths for repositories lazily imported inside the consumer
_TEMPORAL_EVENT_REPO = (
    "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.TemporalEventRepository"
)
_EXPOSURE_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository.EntityEventExposureRepository"  # noqa: E501
_ENTITY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository.EntityRepository"

# Minimal released earnings event dict (Finnhub earningsCalendar item)
_RELEASED_EVENT: dict[str, Any] = {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "reportDate": "2026-05-01",
    "epsEstimate": 1.52,
    "epsActual": None,  # Not yet released (but estimate is present — confirmed date)
    "hour": "amc",
    "year": 2026,
    "quarter": 1,
}

# Tentative event — no EPS estimate (reportDate not confirmed)
_TENTATIVE_EVENT: dict[str, Any] = {
    "symbol": "GOOGL",
    "name": "Alphabet Inc.",
    "reportDate": "2026-05-10",
    "epsEstimate": None,  # Tentative — skip
    "epsActual": None,
    "hour": "",
    "year": 2026,
    "quarter": 1,
}

# Released event with actual EPS (post-earnings)
_RELEASED_WITH_ACTUAL: dict[str, Any] = {
    "symbol": "MSFT",
    "name": "Microsoft Corporation",
    "reportDate": "2026-04-29",
    "epsEstimate": 2.94,
    "epsActual": 3.46,  # Beat estimate
    "hour": "amc",
    "year": 2026,
    "quarter": 2,
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_consumer(
    company_entity_id_for_ticker: UUID | None = _COMPANY_ENTITY_ID,
    storage_bytes: bytes | None = None,
    storage_error: Exception | None = None,
) -> tuple[Any, Any, Any, Any]:
    """Build EarningsCalendarDatasetConsumer with mocked dependencies.

    Returns:
        (consumer, event_repo_mock, exposure_repo_mock, entity_repo_mock)
    """
    from knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository import InstrumentRecord
    from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
        EarningsCalendarDatasetConsumer,
    )

    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    config = ConsumerConfig(
        bootstrap_servers="localhost:9092",
        group_id="kg-earnings-calendar-test",
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
    # find_instrument_by_ticker returns InstrumentRecord or None
    if company_entity_id_for_ticker is not None:
        instrument_record = InstrumentRecord(
            entity_id=company_entity_id_for_ticker,
            ticker="AAPL",
            canonical_name="Apple Inc.",
        )
        entity_repo.find_instrument_by_ticker = AsyncMock(return_value=instrument_record)
    else:
        entity_repo.find_instrument_by_ticker = AsyncMock(return_value=None)

    consumer = EarningsCalendarDatasetConsumer(
        config=config,
        session_factory=sf,
        storage_client=storage,
    )

    return consumer, event_repo, exposure_repo, entity_repo


def _make_envelope(
    events: list[dict[str, Any]],
    symbol: str = "CALENDAR",
    use_nested: bool = False,
) -> bytes:
    """Build the canonical NDJSON envelope bytes.

    If use_nested=True, wraps events under 'earningsCalendar' key inside 'payload'
    to simulate the Finnhub raw response passthrough shape.
    """
    if use_nested:
        # Simulates Finnhub raw response inside canonical envelope wrapper:
        # { "payload": { "earningsCalendar": [...] } }
        envelope = {
            "dataset_type": "earnings_calendar",
            "symbol": symbol,
            "source": "finnhub",
            "payload": {"earningsCalendar": events},
            "fetched_at": "2026-05-01T06:00:00+00:00",
        }
    else:
        # Flat list in payload (canonical normalised form)
        envelope = {
            "dataset_type": "earnings_calendar",
            "symbol": symbol,
            "source": "finnhub",
            "payload": events,
            "fetched_at": "2026-05-01T06:00:00+00:00",
        }
    return (json.dumps(envelope) + "\n").encode("utf-8")


def _make_message(
    symbol: str = "CALENDAR",
    dataset_type: str = "earnings_calendar",
    bucket: str = "canonical",
    key: str = "earnings_calendar/global/2026-05-01.ndjson",
) -> dict[str, Any]:
    """Build a decoded Avro dict for market.dataset.fetched."""
    return {
        "event_id": str(uuid4()),
        "dataset_type": dataset_type,
        "symbol": symbol,
        "canonical_ref_bucket": bucket,
        "canonical_ref_key": key,
    }


# ── Test: EventType.CORPORATE enum value ─────────────────────────────────────


class TestEventTypeCorporate:
    def test_corporate_enum_value_is_lowercase_string(self) -> None:
        """EventType.CORPORATE must be lowercase to match the DB CHECK constraint."""
        from knowledge_graph.domain.enums import EventType

        assert EventType.CORPORATE == "corporate"
        assert EventType.CORPORATE.value == "corporate"


# ── Test: filter by dataset_type ─────────────────────────────────────────────


class TestEarningsCalendarConsumerFilter:
    def test_non_earnings_type_skipped(self) -> None:
        """dataset_type != 'earnings_calendar' → process_message returns early, no storage call."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        msg = _make_message(dataset_type="ohlcv")
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, msg, {}))

        consumer._storage.get_bytes.assert_not_awaited()
        event_repo.upsert_by_natural_key.assert_not_awaited()

    def test_economic_events_type_skipped(self) -> None:
        """dataset_type='economic_events' is skipped by this consumer."""
        consumer, event_repo, _, entity_repo = _make_consumer()
        msg = _make_message(dataset_type="economic_events")
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(consumer.process_message(None, msg, {}))
        event_repo.upsert_by_natural_key.assert_not_awaited()


# ── Test: happy path ──────────────────────────────────────────────────────────


class TestEarningsCalendarConsumerHappyPath:
    def test_released_event_upserted_with_corporate_type(self) -> None:
        """Earnings event with epsEstimate → upsert with CORPORATE type, LOCAL scope, region=ticker."""
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
        assert kwargs["event_type"].value == "corporate"
        assert kwargs["scope"].value == "LOCAL"
        assert kwargs["region"] == "AAPL"  # ticker normalised to uppercase
        assert kwargs["confidence"] == 1.0
        assert kwargs["residual_impact_days"] == 7

    def test_title_includes_ticker_and_date(self) -> None:
        """Title format: '{TICKER} Earnings — {date} ({timing)}'."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        title = event_repo.upsert_by_natural_key.call_args.kwargs["title"]
        assert "AAPL" in title
        assert "2026-05-01" in title
        # 'amc' maps to 'AMC' in the timing map
        assert "AMC" in title

    def test_description_includes_eps_estimate(self) -> None:
        """Description must include the EPS estimate value."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        desc = event_repo.upsert_by_natural_key.call_args.kwargs["description"]
        assert "1.52" in desc

    def test_description_includes_beat_for_positive_surprise(self) -> None:
        """When actual > estimate, description includes 'beat'."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_WITH_ACTUAL]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        desc = event_repo.upsert_by_natural_key.call_args.kwargs["description"]
        assert "beat" in desc

    def test_exposure_linked_to_company_entity(self) -> None:
        """After upsert, exposure link created for company entity."""
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
        assert exp_kwargs["entity_id"] == _COMPANY_ENTITY_ID
        assert exp_kwargs["event_id"] == _DB_EVENT_ID
        assert exp_kwargs["exposure_type"].value == "directly_affected"
        assert exp_kwargs["confidence"] == 1.0

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

    def test_active_until_is_24h_after_active_from(self) -> None:
        """active_until = active_from + 24h (earnings event is point-in-time)."""
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

    def test_nested_earningscalendar_envelope_parsed(self) -> None:
        """Finnhub raw response shape {'earningsCalendar': [...]} inside payload is handled."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT], use_nested=True))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_awaited_once()


# ── Test: tentative events skipped ───────────────────────────────────────────


class TestEarningsCalendarConsumerTentative:
    def test_tentative_event_skipped(self) -> None:
        """epsEstimate=None → event skipped; upsert_by_natural_key not called."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_TENTATIVE_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()
        exposure_repo.upsert.assert_not_awaited()

    def test_mixed_tentative_and_released(self) -> None:
        """Mix of tentative and released → only released events upserted."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT, _TENTATIVE_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        # Only AAPL (released) is upserted; GOOGL (tentative) is skipped
        assert event_repo.upsert_by_natural_key.await_count == 1


# ── Test: empty / missing payload ─────────────────────────────────────────────


class TestEarningsCalendarConsumerEmptyPayload:
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


class TestEarningsCalendarConsumerStorageErrors:
    def test_transient_storage_exception_propagates(self) -> None:
        """Transient storage error re-raised so BaseKafkaConsumer does NOT commit offset."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer(
            storage_error=RuntimeError("minio connection refused")
        )

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
            pytest.raises(RuntimeError, match="minio connection refused"),
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


# ── Test: missing company entity ─────────────────────────────────────────────


class TestEarningsCalendarConsumerMissingEntity:
    def test_no_company_entity_still_upserts_event(self) -> None:
        """When company entity not found in KG, event is still upserted; exposure skipped."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer(company_entity_id_for_ticker=None)
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_awaited_once()
        exposure_repo.upsert.assert_not_awaited()


# ── Test: invalid report date skipped ────────────────────────────────────────


class TestEarningsCalendarConsumerInvalidDate:
    def test_invalid_date_event_skipped(self) -> None:
        """Event with unparseable reportDate → skipped; no upsert."""
        bad_date_event = {**_RELEASED_EVENT, "reportDate": "not-a-date"}
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


class TestEarningsCalendarConsumerPrometheus:
    def test_prometheus_counter_incremented_on_ingestion(self) -> None:
        """s7_earnings_calendar_events_ingested_total{ticker='AAPL'} incremented per event."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_earnings_calendar_events_ingested_total

        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_RELEASED_EVENT]))

        before = s7_earnings_calendar_events_ingested_total.labels(ticker="AAPL")._value.get()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))
        after = s7_earnings_calendar_events_ingested_total.labels(ticker="AAPL")._value.get()

        assert after - before == 1.0

    def test_prometheus_counter_not_incremented_for_tentative(self) -> None:
        """No increment when all events are tentative (epsEstimate=None)."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_earnings_calendar_events_ingested_total

        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_envelope([_TENTATIVE_EVENT]))

        before = s7_earnings_calendar_events_ingested_total.labels(ticker="GOOGL")._value.get()
        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))
        after = s7_earnings_calendar_events_ingested_total.labels(ticker="GOOGL")._value.get()

        assert after == before


# ── Test: title / description helpers ────────────────────────────────────────


class TestBuildTitle:
    def test_bmo_timing_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _build_title,
        )

        title = _build_title("AAPL", "Apple Inc.", "2026-05-01", "bmo")
        assert "BMO" in title
        assert "AAPL" in title

    def test_amc_timing_included(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _build_title,
        )

        title = _build_title("MSFT", "Microsoft", "2026-04-29", "amc")
        assert "AMC" in title

    def test_no_hour_excludes_timing_parens(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _build_title,
        )

        title = _build_title("TSLA", "Tesla", "2026-05-10", "")
        # Should not include empty parentheses
        assert "()" not in title

    def test_title_truncated_at_500_chars(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _build_title,
        )

        long_name = "A" * 600
        title = _build_title("AAPL", long_name, "2026-05-01", "bmo")
        assert len(title) <= 500


class TestParsReportDate:
    def test_date_only_string(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _parse_report_date,
        )

        result = _parse_report_date("2026-05-01")
        assert result is not None
        assert result.year == 2026
        assert result.month == 5
        assert result.day == 1

    def test_result_is_utc_aware(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _parse_report_date,
        )

        result = _parse_report_date("2026-05-01")
        assert result is not None
        assert result.tzinfo == UTC

    def test_empty_string_returns_none(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _parse_report_date,
        )

        assert _parse_report_date("") is None

    def test_garbage_string_returns_none(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            _parse_report_date,
        )

        assert _parse_report_date("not-a-date") is None


# ── Test: EODHD provider format (BP-348) ──────────────────────────────────────


# EODHD earnings event shape (from /calendar/earnings endpoint)
_EODHD_EVENT: dict[str, Any] = {
    "code": "AAPL.US",  # exchange suffix — must be stripped to "AAPL"
    "report_date": "2026-05-01",
    "before_after_market": "AfterMarket",
    "actual": None,
    "estimate": 1.52,
    # No "name" field in EODHD — consumer falls back to ticker
    # No "hour" field — mapped from before_after_market
}

_EODHD_TENTATIVE_EVENT: dict[str, Any] = {
    "code": "NVDA.US",
    "report_date": "2026-05-28",
    "before_after_market": None,
    "actual": None,
    "estimate": None,  # EODHD tentative — must be skipped
}

_EODHD_BEFORE_MARKET_EVENT: dict[str, Any] = {
    "code": "MSFT.PA",  # non-US exchange suffix
    "report_date": "2026-04-29",
    "before_after_market": "BeforeMarket",
    "actual": 3.46,
    "estimate": 2.94,
}


def _make_eodhd_envelope(events: list[dict[str, Any]]) -> bytes:
    """Build EODHD-style canonical envelope bytes with 'earnings' key."""
    envelope = {
        "dataset_type": "earnings_calendar",
        "symbol": "CALENDAR",
        "source": "eodhd",
        "payload": {"type": "Earnings", "earnings": events},
        "fetched_at": "2026-05-03T06:00:00+00:00",
    }
    return (json.dumps(envelope) + "\n").encode("utf-8")


class TestEohdEarningsFormat:
    def test_eodhd_earnings_key_parsed(self) -> None:
        """EODHD 'earnings' key in payload is parsed; event is upserted."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_awaited_once()

    def test_eodhd_ticker_exchange_suffix_stripped(self) -> None:
        """'AAPL.US' from EODHD is normalised to 'AAPL' as the KG region."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["region"] == "AAPL"

    def test_eodhd_estimate_field_used(self) -> None:
        """EODHD 'estimate' field is used when Finnhub 'epsEstimate' is absent."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        desc = event_repo.upsert_by_natural_key.call_args.kwargs["description"]
        assert "1.52" in desc

    def test_eodhd_null_estimate_skipped(self) -> None:
        """EODHD event with estimate=null is skipped (tentative date)."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_TENTATIVE_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        event_repo.upsert_by_natural_key.assert_not_awaited()

    def test_eodhd_before_market_maps_to_bmo(self) -> None:
        """'BeforeMarket' in before_after_market field maps to 'BMO' in title."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_BEFORE_MARKET_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        title = event_repo.upsert_by_natural_key.call_args.kwargs["title"]
        assert "BMO" in title
        assert "MSFT" in title

    def test_eodhd_after_market_maps_to_amc(self) -> None:
        """'AfterMarket' in before_after_market field maps to 'AMC' in title."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        title = event_repo.upsert_by_natural_key.call_args.kwargs["title"]
        assert "AMC" in title

    def test_eodhd_actual_field_used(self) -> None:
        """EODHD 'actual' field is reflected in description when non-None."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_BEFORE_MARKET_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        desc = event_repo.upsert_by_natural_key.call_args.kwargs["description"]
        # EPS Actual: 3.46 beat estimate 2.94
        assert "3.46" in desc
        assert "beat" in desc

    def test_eodhd_report_date_field_parsed(self) -> None:
        """EODHD 'report_date' field (snake_case) is correctly parsed as active_from."""
        consumer, event_repo, exposure_repo, entity_repo = _make_consumer()
        consumer._storage.get_bytes = AsyncMock(return_value=_make_eodhd_envelope([_EODHD_EVENT]))

        with (
            patch(_TEMPORAL_EVENT_REPO, return_value=event_repo),
            patch(_EXPOSURE_REPO, return_value=exposure_repo),
            patch(_ENTITY_REPO, return_value=entity_repo),
        ):
            asyncio.run(consumer.process_message(None, _make_message(), {}))

        kwargs = event_repo.upsert_by_natural_key.call_args.kwargs
        assert kwargs["active_from"].year == 2026
        assert kwargs["active_from"].month == 5
        assert kwargs["active_from"].day == 1

    def test_non_us_exchange_suffix_stripped(self) -> None:
        """Non-US exchange suffixes (e.g. 'MSFT.PA') are stripped to bare ticker."""
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            EarningsCalendarDatasetConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics=["market.dataset.fetched"],
        )
        sf = MagicMock()
        consumer = EarningsCalendarDatasetConsumer(config=config, session_factory=sf)
        assert consumer._upserted_ticker({"code": "MSFT.PA"}) == "MSFT"
        assert consumer._upserted_ticker({"code": "AIR.DE"}) == "AIR"
        assert consumer._upserted_ticker({"symbol": "AAPL"}) == "AAPL"


# ── Test: dedup infrastructure ────────────────────────────────────────────────


class TestEarningsCalendarConsumerDedup:
    def test_is_duplicate_returns_false_without_dedup_client(self) -> None:
        """is_duplicate always returns False when dedup_client is None."""
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            EarningsCalendarDatasetConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics=["market.dataset.fetched"],
        )
        sf = MagicMock()
        consumer = EarningsCalendarDatasetConsumer(config=config, session_factory=sf)
        result = asyncio.run(consumer.is_duplicate("evt-123"))
        assert result is False

    def test_extract_event_id_returns_event_id_field(self) -> None:
        from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
            EarningsCalendarDatasetConsumer,
        )

        from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

        config = ConsumerConfig(
            bootstrap_servers="localhost:9092",
            group_id="test",
            topics=["market.dataset.fetched"],
        )
        sf = MagicMock()
        consumer = EarningsCalendarDatasetConsumer(config=config, session_factory=sf)
        eid = consumer.extract_event_id({"event_id": "abc-123"})
        assert eid == "abc-123"
