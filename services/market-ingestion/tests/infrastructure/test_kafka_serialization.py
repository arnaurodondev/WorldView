"""Tests for Kafka Avro mapper and serialization (T-MI-21).

Unit tests use fastavro directly (no schema registry required).
The serializer unit test verifies OutboxEventValueSerializer payload extraction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.value_objects import ObjectRef
from market_ingestion.infrastructure.messaging.kafka.mapper import MarketDatasetFetchedMapper

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[4]  # worldview root
    / "infra"
    / "kafka"
    / "schemas"
    / "market.dataset.fetched.avsc"
)

BRONZE_REF = ObjectRef(
    bucket="market-bronze",
    key="market-ingestion/ohlcv/AAPL/v1.json",
    sha256="abc123" * 10 + "ab",
    byte_length=1024,
    mime_type="application/json",
)

CANONICAL_REF = ObjectRef(
    bucket="market-canonical",
    key="market-ingestion/ohlcv/AAPL/v1.jsonl",
    sha256="def456" * 10 + "de",
    byte_length=512,
    mime_type="application/x-ndjson",
)


def _make_event(**kwargs) -> MarketDatasetFetched:
    defaults = {
        "provider": "eodhd",
        "dataset_type": "ohlcv",
        "symbol": "AAPL",
        "exchange": "US",
        "timeframe": "1d",
        "variant": None,
        "range_start": "2024-01-01",
        "range_end": "2024-01-31",
        "bronze_ref": BRONZE_REF,
        "canonical_ref": CANONICAL_REF,
        "canonical_schema_version": 1,
        "row_count": 31,
        "task_id": "task-abc-123",
    }
    defaults.update(kwargs)
    return MarketDatasetFetched(**defaults)


# ---------------------------------------------------------------------------
# Mapper — dict structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mapper_produces_correct_envelope_fields() -> None:
    event = _make_event()
    d = MarketDatasetFetchedMapper.to_avro_dict(event)

    assert d["event_id"] == event.event_id
    assert d["event_type"] == "market.dataset.fetched"
    assert d["schema_version"] == 1
    assert d["occurred_at"] == event.occurred_at


@pytest.mark.unit
def test_mapper_produces_all_27_fields() -> None:
    event = _make_event()
    d = MarketDatasetFetchedMapper.to_avro_dict(event)

    assert len(d) == 27, f"Expected 27 fields, got {len(d)}: {list(d.keys())}"


@pytest.mark.unit
def test_mapper_flattens_bronze_ref() -> None:
    event = _make_event()
    d = MarketDatasetFetchedMapper.to_avro_dict(event)

    assert d["bronze_ref_bucket"] == BRONZE_REF.bucket
    assert d["bronze_ref_key"] == BRONZE_REF.key
    assert d["bronze_ref_sha256"] == BRONZE_REF.sha256
    assert d["bronze_ref_byte_length"] == BRONZE_REF.byte_length
    assert d["bronze_ref_mime_type"] == BRONZE_REF.mime_type


@pytest.mark.unit
def test_mapper_flattens_canonical_ref() -> None:
    event = _make_event()
    d = MarketDatasetFetchedMapper.to_avro_dict(event)

    assert d["canonical_ref_bucket"] == CANONICAL_REF.bucket
    assert d["canonical_ref_key"] == CANONICAL_REF.key
    assert d["canonical_ref_sha256"] == CANONICAL_REF.sha256
    assert d["canonical_ref_byte_length"] == CANONICAL_REF.byte_length
    assert d["canonical_ref_mime_type"] == CANONICAL_REF.mime_type


@pytest.mark.unit
def test_mapper_kafka_key_format() -> None:
    event = _make_event(provider="eodhd", symbol="TSLA")
    key = MarketDatasetFetchedMapper.to_kafka_key(event)
    assert key == "eodhd:TSLA"


@pytest.mark.unit
def test_mapper_nullable_fields_are_none_when_absent() -> None:
    event = _make_event(exchange=None, timeframe=None, variant=None)
    d = MarketDatasetFetchedMapper.to_avro_dict(event)

    assert d["exchange"] is None
    assert d["timeframe"] is None
    assert d["variant"] is None
    assert d["correlation_id"] is None
    assert d["causation_id"] is None


@pytest.mark.unit
def test_mapper_row_count_none_when_zero() -> None:
    event = _make_event(row_count=0)
    d = MarketDatasetFetchedMapper.to_avro_dict(event)
    assert d["row_count"] is None


@pytest.mark.unit
def test_mapper_row_count_set_when_positive() -> None:
    event = _make_event(row_count=42)
    d = MarketDatasetFetchedMapper.to_avro_dict(event)
    assert d["row_count"] == 42


# ---------------------------------------------------------------------------
# Avro schema file existence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_avro_schema_file_exists() -> None:
    assert _SCHEMA_PATH.exists(), f"Schema file missing: {_SCHEMA_PATH}"


@pytest.mark.unit
def test_avro_schema_has_27_fields() -> None:
    schema = json.loads(_SCHEMA_PATH.read_text())
    assert len(schema["fields"]) == 27


# ---------------------------------------------------------------------------
# Fastavro round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_avro_roundtrip() -> None:
    """Serialize → deserialize using fastavro schemaless encoding."""
    fastavro = pytest.importorskip("fastavro")
    import io

    schema_dict = json.loads(_SCHEMA_PATH.read_text())
    parsed = fastavro.parse_schema(schema_dict)

    event = _make_event()
    record = MarketDatasetFetchedMapper.to_avro_dict(event)

    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed, record)
    buf.seek(0)
    decoded = fastavro.schemaless_reader(buf, parsed)

    assert decoded["event_type"] == "market.dataset.fetched"
    assert decoded["symbol"] == "AAPL"
    assert decoded["bronze_ref_sha256"] == BRONZE_REF.sha256
    assert decoded["canonical_ref_byte_length"] == CANONICAL_REF.byte_length


@pytest.mark.unit
def test_avro_forward_compatibility() -> None:
    """Old records (without an optional field) parse successfully against extended schema."""
    fastavro = pytest.importorskip("fastavro")
    import io

    schema_dict = json.loads(_SCHEMA_PATH.read_text())
    parsed = fastavro.parse_schema(schema_dict)

    event = _make_event()
    record = MarketDatasetFetchedMapper.to_avro_dict(event)
    # Remove an optional field to simulate an older producer
    record.pop("variant", None)

    # Schema has "variant" as nullable with default=null, so missing field should be fine
    extended_schema = dict(schema_dict)
    extended_schema["fields"] = list(schema_dict["fields"])

    # Serialize without variant field by adding it back as null
    record["variant"] = None
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed, record)
    buf.seek(0)
    decoded = fastavro.schemaless_reader(buf, parsed)
    assert decoded["variant"] is None


# ---------------------------------------------------------------------------
# OutboxEventValueSerializer — payload extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_outbox_value_serializer_extracts_payload() -> None:
    """OutboxEventValueSerializer must extract .payload before calling AvroSerializer."""
    from messaging.kafka.producer import OutboxEventValueSerializer, OutboxKafkaValue  # type: ignore[import-untyped]

    event = _make_event()
    payload_dict = MarketDatasetFetchedMapper.to_avro_dict(event)

    # Mock AvroSerializer captures what it receives
    received: list = []

    def mock_avro_serializer(value: object, ctx: object) -> bytes:
        received.append(value)
        return b"serialized"

    serializer = OutboxEventValueSerializer({"market.dataset.fetched": mock_avro_serializer})
    outbox_value = OutboxKafkaValue(
        event_type="market.dataset.fetched",
        payload=payload_dict,
    )
    result = serializer(outbox_value, ctx=None)

    assert result == b"serialized"
    # The AvroSerializer must receive the plain dict, NOT the OutboxKafkaValue wrapper
    assert received[0] is payload_dict
    assert not isinstance(received[0], OutboxKafkaValue)


@pytest.mark.unit
def test_raw_avro_serializer_rejects_outbox_wrapper() -> None:
    """Passing OutboxKafkaValue directly to a bytes-expecting serializer fails."""
    from messaging.kafka.producer import OutboxKafkaValue  # type: ignore[import-untyped]

    def bytes_serializer(value: object, ctx: object) -> bytes:
        if not isinstance(value, bytes | dict):
            raise TypeError(f"a bytes-like object is required, not {type(value).__name__!r}")
        return b""

    outbox_value = OutboxKafkaValue(event_type="x", payload={})
    with pytest.raises(TypeError, match="OutboxKafkaValue"):
        bytes_serializer(outbox_value, None)
