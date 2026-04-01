"""Tests for Market Ingestion domain events — envelope, to_dict, from_dict, AvroDictable."""

from __future__ import annotations

import pytest
from market_ingestion.domain.events import (
    DomainEvent,
    IngestionTaskCompleted,
    IngestionTaskScheduled,
    MarketDatasetFetched,
)
from market_ingestion.domain.value_objects import ObjectRef

_ULID_LEN = 26

_BRONZE_REF = ObjectRef(
    bucket="bronze-data",
    key="market-ingestion/ohlcv/AAPL/2024-01-01_2024-12-31/raw.json",
    sha256="deadbeef",
    byte_length=2048,
    mime_type="application/json",
)
_CANONICAL_REF = ObjectRef(
    bucket="canonical-data",
    key="market-ingestion/ohlcv/AAPL/2024-01-01_2024-12-31/canonical/v1.parquet",
    sha256="cafebabe",
    byte_length=1024,
    mime_type="application/octet-stream",
)


def _make_event(**kwargs: object) -> MarketDatasetFetched:
    return MarketDatasetFetched(
        provider="eodhd",
        dataset_type="ohlcv",
        symbol="AAPL",
        bronze_ref=_BRONZE_REF,
        canonical_ref=_CANONICAL_REF,
        **kwargs,  # type: ignore[arg-type]
    )


# ── DomainEvent base ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_domain_event_auto_populated_event_id() -> None:
    evt = _make_event()
    assert isinstance(evt.event_id, str)
    assert len(evt.event_id) == _ULID_LEN


@pytest.mark.unit
def test_domain_event_auto_populated_occurred_at() -> None:
    evt = _make_event()
    assert isinstance(evt.occurred_at, str)
    assert "T" in evt.occurred_at  # ISO-8601 format contains 'T'


@pytest.mark.unit
def test_domain_event_is_frozen() -> None:
    evt = _make_event()
    with pytest.raises(AttributeError):
        evt.event_id = "modified"  # type: ignore[misc]


@pytest.mark.unit
def test_domain_event_correlation_id_defaults_none() -> None:
    evt = _make_event()
    assert evt.correlation_id is None


@pytest.mark.unit
def test_domain_event_accepts_correlation_id() -> None:
    evt = _make_event(correlation_id="corr-123")
    assert evt.correlation_id == "corr-123"


# ── MarketDatasetFetched — class vars ─────────────────────────────────────────


@pytest.mark.unit
def test_market_dataset_fetched_event_type() -> None:
    assert MarketDatasetFetched.EVENT_TYPE == "market.dataset.fetched"


@pytest.mark.unit
def test_market_dataset_fetched_schema_version() -> None:
    assert MarketDatasetFetched.SCHEMA_VERSION == 1


# ── to_dict() produces all 27 keys ───────────────────────────────────────────


@pytest.mark.unit
def test_to_dict_produces_27_keys() -> None:
    evt = _make_event(
        exchange="NASDAQ",
        timeframe="1d",
        variant=None,
        range_start="2024-01-01",
        range_end="2024-12-31",
        row_count=252,
        task_id="task-abc",
    )
    d = evt.to_dict()
    assert len(d) == 27


@pytest.mark.unit
def test_to_dict_envelope_keys() -> None:
    evt = _make_event()
    d = evt.to_dict()
    for key in ("event_id", "event_type", "schema_version", "occurred_at", "correlation_id", "causation_id"):
        assert key in d


@pytest.mark.unit
def test_to_dict_metadata_keys() -> None:
    evt = _make_event(exchange="NASDAQ", timeframe="1d", variant="annual")
    d = evt.to_dict()
    assert d["provider"] == "eodhd"
    assert d["dataset_type"] == "ohlcv"
    assert d["symbol"] == "AAPL"
    assert d["exchange"] == "NASDAQ"
    assert d["timeframe"] == "1d"
    assert d["variant"] == "annual"


@pytest.mark.unit
def test_to_dict_bronze_ref_flattened() -> None:
    evt = _make_event()
    d = evt.to_dict()
    assert d["bronze_ref_bucket"] == "bronze-data"
    assert d["bronze_ref_key"] == "market-ingestion/ohlcv/AAPL/2024-01-01_2024-12-31/raw.json"
    assert d["bronze_ref_sha256"] == "deadbeef"
    assert d["bronze_ref_byte_length"] == 2048
    assert d["bronze_ref_mime_type"] == "application/json"


@pytest.mark.unit
def test_to_dict_canonical_ref_flattened() -> None:
    evt = _make_event()
    d = evt.to_dict()
    assert d["canonical_ref_bucket"] == "canonical-data"
    assert d["canonical_ref_key"] == "market-ingestion/ohlcv/AAPL/2024-01-01_2024-12-31/canonical/v1.parquet"
    assert d["canonical_ref_sha256"] == "cafebabe"
    assert d["canonical_ref_byte_length"] == 1024
    assert d["canonical_ref_mime_type"] == "application/octet-stream"
    assert d["canonical_schema_version"] == 1


@pytest.mark.unit
def test_to_dict_stats_keys() -> None:
    evt = _make_event(row_count=100, task_id="t-001")
    d = evt.to_dict()
    assert d["row_count"] == 100
    assert d["task_id"] == "t-001"


# ── from_dict() roundtrip ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_from_dict_roundtrip() -> None:
    original = _make_event(
        exchange="NASDAQ",
        timeframe="1d",
        range_start="2024-01-01",
        range_end="2024-12-31",
        row_count=252,
        task_id="task-xyz",
    )
    d = original.to_dict()
    restored = MarketDatasetFetched.from_dict(d)

    assert restored.event_id == original.event_id
    assert restored.occurred_at == original.occurred_at
    assert restored.provider == original.provider
    assert restored.dataset_type == original.dataset_type
    assert restored.symbol == original.symbol
    assert restored.exchange == original.exchange
    assert restored.timeframe == original.timeframe
    assert restored.bronze_ref == original.bronze_ref
    assert restored.canonical_ref == original.canonical_ref
    assert restored.row_count == original.row_count
    assert restored.task_id == original.task_id


# ── AvroDictable duck-type check ──────────────────────────────────────────────


@pytest.mark.unit
def test_avro_dictable_protocol_satisfied() -> None:
    evt = _make_event()
    assert hasattr(evt, "to_dict") and callable(evt.to_dict)
    assert hasattr(MarketDatasetFetched, "from_dict") and callable(MarketDatasetFetched.from_dict)


# ── Internal events ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_ingestion_task_completed_event_type() -> None:
    assert IngestionTaskCompleted.EVENT_TYPE == "market.task.completed"


@pytest.mark.unit
def test_ingestion_task_scheduled_event_type() -> None:
    assert IngestionTaskScheduled.EVENT_TYPE == "market.task.scheduled"


@pytest.mark.unit
def test_internal_events_auto_populate_envelope() -> None:
    completed = IngestionTaskCompleted(task_id="t1", provider="eodhd", dataset_type="ohlcv", symbol="AAPL")
    assert len(completed.event_id) == _ULID_LEN
    assert completed.occurred_at != ""

    scheduled = IngestionTaskScheduled(task_id="t2", provider="polygon", dataset_type="quotes", symbol="MSFT")
    assert len(scheduled.event_id) == _ULID_LEN


@pytest.mark.unit
def test_internal_events_are_domain_events() -> None:
    assert issubclass(IngestionTaskCompleted, DomainEvent)
    assert issubclass(IngestionTaskScheduled, DomainEvent)
    assert issubclass(MarketDatasetFetched, DomainEvent)


# ── T-E1-3-03: row_count 0-vs-None serialization fix (M-024) ─────────────────


@pytest.mark.unit
def test_market_dataset_fetched_row_count_zero_serializes_as_zero() -> None:
    """row_count=0 must serialize as 0, not None (falsy coercion bug fix)."""
    evt = _make_event(row_count=0)
    d = evt.to_dict()
    assert d["row_count"] == 0, f"Expected 0, got {d['row_count']!r}"


@pytest.mark.unit
def test_market_dataset_fetched_row_count_none_serializes_as_none() -> None:
    """row_count=None (default) must serialize as None — 'not counted'."""
    evt = _make_event()  # row_count defaults to None
    d = evt.to_dict()
    assert d["row_count"] is None


@pytest.mark.unit
def test_market_dataset_fetched_row_count_roundtrip_zero() -> None:
    """from_dict with row_count=0 must restore 0, not coerce to default."""
    evt = _make_event(row_count=0)
    d = evt.to_dict()
    restored = MarketDatasetFetched.from_dict(d)
    assert restored.row_count == 0


@pytest.mark.unit
def test_market_dataset_fetched_row_count_roundtrip_none() -> None:
    """from_dict with row_count=None must restore None."""
    evt = _make_event()  # row_count=None
    d = evt.to_dict()
    assert d["row_count"] is None
    restored = MarketDatasetFetched.from_dict(d)
    assert restored.row_count is None
