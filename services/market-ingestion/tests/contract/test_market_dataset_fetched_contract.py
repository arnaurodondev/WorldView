"""Contract tests for market.dataset.fetched event payload compatibility."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from market_ingestion.domain.events import MarketDatasetFetched
from market_ingestion.domain.value_objects import ObjectRef
from market_ingestion.infrastructure.messaging.mapper import MarketDatasetFetchedMapper
from market_ingestion.infrastructure.messaging.serialization import MARKET_INGESTION_TOPIC

pytestmark = pytest.mark.contract


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for base in here.parents:
        candidate = base / "infra" / "kafka" / "schemas" / "market.dataset.fetched.avsc"
        if candidate.exists():
            return base
    raise FileNotFoundError("Could not resolve repository root from test path")


def _schema_fields() -> list[str]:
    schema_path = _repo_root() / "infra" / "kafka" / "schemas" / "market.dataset.fetched.avsc"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return [field["name"] for field in schema["fields"]]


def _sample_event() -> MarketDatasetFetched:
    return MarketDatasetFetched(
        event_id="01JTESTEVENT00000000000001",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        correlation_id="01JTESTCORREL0000000000001",
        causation_id="01JTESTCAUSE00000000000001",
        task_id="01JTESTTASK000000000000001",
        provider="eodhd",
        dataset_type="ohlcv",
        symbol="AAPL",
        exchange="US",
        timeframe="1d",
        variant=None,
        range_start="2026-01-01",
        range_end="2026-01-31",
        bronze_ref=ObjectRef(
            bucket="market-bronze",
            key="market-ingestion/ohlcv/AAPL/2026-01-31/raw.json",
            sha256="a" * 64,
            byte_length=1024,
            mime_type="application/json",
        ),
        canonical_ref=ObjectRef(
            bucket="market-canonical",
            key="market-ingestion/ohlcv/AAPL/2026-01-31/canonical.parquet",
            sha256="b" * 64,
            byte_length=2048,
            mime_type="application/octet-stream",
        ),
        canonical_schema_version=1,
        row_count=31,
    )


def test_market_dataset_topic_constant_is_stable() -> None:
    assert MARKET_INGESTION_TOPIC == "market.dataset.fetched"


def test_market_dataset_payload_fields_match_avro_schema() -> None:
    event = _sample_event()
    payload = MarketDatasetFetchedMapper.to_avro_dict(event)

    schema_fields = _schema_fields()
    assert set(payload.keys()) == set(schema_fields)


def test_market_dataset_envelope_contract_values() -> None:
    event = _sample_event()
    payload = MarketDatasetFetchedMapper.to_avro_dict(event)

    assert payload["event_type"] == "market.dataset.fetched"
    assert payload["schema_version"] == 1
    assert payload["event_id"]
    assert payload["occurred_at"]
    assert payload["task_id"]


# ── BUG-009 / BP-492: forward-compat for the new `is_backfill` field ─────────


def test_avro_schema_declares_is_backfill_field_with_default_false() -> None:
    """The Avro schema must declare is_backfill with a literal `false` default.

    R11 requires the field to be appended with a default — any consumer that
    has not yet upgraded must keep decoding old payloads.
    """
    schema_path = _repo_root() / "infra" / "kafka" / "schemas" / "market.dataset.fetched.avsc"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    is_backfill_field = next((f for f in schema["fields"] if f["name"] == "is_backfill"), None)
    assert is_backfill_field is not None, "is_backfill field missing from Avro schema"
    assert is_backfill_field["type"] == "boolean"
    assert is_backfill_field["default"] is False


def test_market_dataset_payload_contains_is_backfill_flag() -> None:
    """Mapper output carries is_backfill so the Avro wire bytes include the flag."""
    event = _sample_event()
    payload = MarketDatasetFetchedMapper.to_avro_dict(event)
    assert "is_backfill" in payload
    assert payload["is_backfill"] is False  # _sample_event() does not pass is_backfill
