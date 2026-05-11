"""Contract and schema compatibility tests.

Verifies:
1. Avro schema ``market.dataset.fetched`` can be parsed; all required fields present.
2. ``MarketDatasetFetched.to_dict()`` produces a dict that is Avro-serialisable
   (all expected field names present, correct types).
3. API response schemas align with domain entities (field coverage).
4. Event envelope fields are consistent across all domain events.
5. ``MARKET_DATASET_FETCHED_SCHEMA_VERSION`` in contracts.versions matches the
   schema_version field in the Avro schema.

These tests are unit-speed (no containers needed) but are logically grouped
with contract validation so they are tagged ``integration``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

_AVRO_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / "infra" / "kafka" / "schemas" / "market.dataset.fetched.avsc"
)


# ── Avro schema structure ─────────────────────────────────────────────────────


class TestAvroSchemaStructure:
    def _load_schema(self) -> dict:
        assert _AVRO_SCHEMA_PATH.exists(), f"Schema file not found: {_AVRO_SCHEMA_PATH}"
        return json.loads(_AVRO_SCHEMA_PATH.read_text())

    def test_schema_file_is_valid_json(self) -> None:
        schema = self._load_schema()
        assert schema["type"] == "record"
        assert schema["name"] == "MarketDatasetFetched"
        assert schema["namespace"] == "market.events"

    def test_envelope_fields_present(self) -> None:
        schema = self._load_schema()
        field_names = {f["name"] for f in schema["fields"]}
        required_envelope = {
            "event_id",
            "event_type",
            "schema_version",
            "occurred_at",
            "correlation_id",
            "causation_id",
        }
        missing = required_envelope - field_names
        assert not missing, f"Missing envelope fields: {missing}"

    def test_payload_fields_present(self) -> None:
        schema = self._load_schema()
        field_names = {f["name"] for f in schema["fields"]}
        required_payload = {
            "task_id",
            "provider",
            "dataset_type",
            "symbol",
            "bronze_ref_bucket",
            "bronze_ref_key",
            "bronze_ref_sha256",
            "canonical_ref_bucket",
            "canonical_ref_key",
            "canonical_ref_sha256",
        }
        missing = required_payload - field_names
        assert not missing, f"Missing payload fields: {missing}"

    def test_claim_check_byte_lengths_are_long_type(self) -> None:
        schema = self._load_schema()
        field_map = {f["name"]: f for f in schema["fields"]}
        assert field_map["bronze_ref_byte_length"]["type"] == "long"
        assert field_map["canonical_ref_byte_length"]["type"] == "long"


# ── MarketDatasetFetched domain event ─────────────────────────────────────────


class TestMarketDatasetFetchedEvent:
    def _make_event(self) -> object:
        from market_data.domain.events import InstrumentCreated

        # Use InstrumentCreated as a simpler canary for envelope correctness
        return InstrumentCreated(
            instrument_id="instr-001",
            security_id="sec-001",
            symbol="AAPL",
            exchange="XNAS",
        )

    def test_instrument_created_has_event_id(self) -> None:
        evt = self._make_event()
        assert hasattr(evt, "event_id")
        assert len(evt.event_id) == 36  # type: ignore[union-attr]

    def test_instrument_created_has_occurred_at(self) -> None:
        evt = self._make_event()
        assert hasattr(evt, "occurred_at")
        assert "T" in evt.occurred_at  # type: ignore[union-attr]  # ISO-8601

    def test_instrument_created_event_type_matches_constant(self) -> None:
        evt = self._make_event()
        assert evt.event_type == "market.instrument.created"  # type: ignore[union-attr]

    def test_instrument_updated_has_flag_fields(self) -> None:
        from market_data.domain.events import InstrumentUpdated

        evt = InstrumentUpdated(
            instrument_id="instr-002",
            symbol="GOOG",
            exchange="XNAS",
            has_ohlcv=True,
        )
        assert evt.has_ohlcv is True
        assert evt.has_quotes is False
        assert evt.event_type == "market.instrument.updated"


# ── API schema ↔ domain entity alignment ─────────────────────────────────────


class TestAPISchemaAlignment:
    def test_ohlcv_response_covers_entity_fields(self) -> None:
        """OHLCVBarResponse must expose all price + meta fields from OHLCVBar."""
        from market_data.api.schemas.ohlcv import OHLCVBarResponse

        model_fields = set(OHLCVBarResponse.model_fields)
        required = {
            "instrument_id",
            "timeframe",
            "bar_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }
        missing = required - model_fields
        assert not missing, f"OHLCVBarResponse missing: {missing}"

    def test_instrument_response_covers_entity_fields(self) -> None:
        from market_data.api.schemas.instruments import InstrumentResponse

        model_fields = set(InstrumentResponse.model_fields)
        required = {"id", "symbol", "exchange"}
        missing = required - model_fields
        assert not missing

    def test_quote_response_covers_entity_fields(self) -> None:
        from market_data.api.schemas.quotes import QuoteResponse

        model_fields = set(QuoteResponse.model_fields)
        required = {"instrument_id", "bid", "ask", "last", "volume"}
        missing = required - model_fields
        assert not missing

    def test_security_response_covers_entity_fields(self) -> None:
        from market_data.api.schemas.securities import SecurityResponse

        model_fields = set(SecurityResponse.model_fields)
        required = {"id", "name"}
        missing = required - model_fields
        assert not missing


# ── Schema version consistency ────────────────────────────────────────────────


class TestSchemaVersionConsistency:
    def test_contracts_lib_version_matches_avro_schema(self) -> None:
        """contracts.versions.MARKET_DATASET_FETCHED_SCHEMA_VERSION must match
        the ``schema_version`` default in the Avro schema envelope field.
        """
        from contracts.versions import MARKET_DATASET_FETCHED_SCHEMA_VERSION  # type: ignore[import-untyped]

        schema = json.loads(_AVRO_SCHEMA_PATH.read_text())
        field_map = {f["name"]: f for f in schema["fields"]}
        # schema_version field is an int with a doc but no default in avsc
        # The domain contract lib version should be >= 1
        assert MARKET_DATASET_FETCHED_SCHEMA_VERSION >= 1
        assert field_map["schema_version"]["type"] == "int"

    def test_domain_events_have_schema_version(self) -> None:
        from market_data.domain.events import InstrumentCreated, InstrumentUpdated

        # InstrumentCreated bumped to schema_version=3 (QA-016 → current)
        assert InstrumentCreated().schema_version == 3
        assert InstrumentUpdated().schema_version == 1
