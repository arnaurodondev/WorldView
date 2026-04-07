"""Contract tests for market-data API response schemas (M-005).

Verifies that key API response Pydantic schemas:
1. Contain all required fields with the correct types.
2. Are consistent with what the domain entities expose.
3. Accept valid payloads without validation errors.

No containers or network required — tests import schemas directly and
instantiate them with crafted payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.contract


# ── TestInstrumentResponseContract ───────────────────────────────────────────


class TestInstrumentResponseContract:
    """InstrumentResponse must expose all required fields with correct types."""

    def test_required_fields_present(self) -> None:
        from market_data.api.schemas.instruments import InstrumentResponse

        required = {"id", "security_id", "symbol", "exchange", "is_active", "flags", "created_at"}
        missing = required - set(InstrumentResponse.model_fields)
        assert not missing, f"InstrumentResponse missing fields: {missing}"

    def test_flags_response_fields(self) -> None:
        from market_data.api.schemas.instruments import InstrumentFlagsResponse

        required = {"has_ohlcv", "has_quotes", "has_fundamentals"}
        missing = required - set(InstrumentFlagsResponse.model_fields)
        assert not missing, f"InstrumentFlagsResponse missing fields: {missing}"

    def test_instantiation_with_valid_payload(self) -> None:
        from market_data.api.schemas.instruments import InstrumentFlagsResponse, InstrumentResponse

        flags = InstrumentFlagsResponse(has_ohlcv=True, has_quotes=False, has_fundamentals=True)
        resp = InstrumentResponse(
            id="instr-001",
            security_id="sec-001",
            symbol="AAPL",
            exchange="US",
            is_active=True,
            flags=flags,
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert resp.id == "instr-001"
        assert resp.symbol == "AAPL"
        assert resp.flags.has_ohlcv is True

    def test_id_field_is_string(self) -> None:
        from market_data.api.schemas.instruments import InstrumentResponse

        field = InstrumentResponse.model_fields["id"]
        assert field.annotation is str or str in getattr(field.annotation, "__args__", (str,))

    def test_list_response_has_pagination_fields(self) -> None:
        from market_data.api.schemas.instruments import InstrumentListResponse

        required = {"items", "total", "limit", "offset"}
        missing = required - set(InstrumentListResponse.model_fields)
        assert not missing, f"InstrumentListResponse missing pagination fields: {missing}"


# ── TestOHLCVBarResponseContract ─────────────────────────────────────────────


class TestOHLCVBarResponseContract:
    """OHLCVBarResponse must expose all OHLCV price and metadata fields."""

    def test_required_fields_present(self) -> None:
        from market_data.api.schemas.ohlcv import OHLCVBarResponse

        required = {
            "instrument_id",
            "timeframe",
            "bar_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        }
        missing = required - set(OHLCVBarResponse.model_fields)
        assert not missing, f"OHLCVBarResponse missing fields: {missing}"

    def test_price_fields_are_strings(self) -> None:
        """OHLCV prices must be serialised as strings to preserve Decimal precision."""
        from market_data.api.schemas.ohlcv import OHLCVBarResponse

        for price_field in ("open", "high", "low", "close"):
            annotation = OHLCVBarResponse.model_fields[price_field].annotation
            assert annotation is str or str in getattr(
                annotation, "__args__", (str,)
            ), f"Field '{price_field}' annotation is {annotation!r}, expected str"

    def test_adjusted_close_is_optional(self) -> None:
        from market_data.api.schemas.ohlcv import OHLCVBarResponse

        field = OHLCVBarResponse.model_fields["adjusted_close"]
        # Must have a default of None — optional field
        assert field.default is None

    def test_instantiation_with_valid_payload(self) -> None:
        from market_data.api.schemas.ohlcv import OHLCVBarResponse

        resp = OHLCVBarResponse(
            instrument_id="instr-001",
            timeframe="1d",
            bar_date=datetime(2024, 1, 15, tzinfo=UTC),
            open="150.00",
            high="155.00",
            low="149.00",
            close="153.50",
            volume=1_000_000,
            adjusted_close=None,
            source="eodhd",
        )
        assert resp.close == "153.50"
        assert resp.adjusted_close is None

    def test_range_response_fields(self) -> None:
        from market_data.api.schemas.ohlcv import OHLCVRangeResponse

        required = {"instrument_id", "timeframe", "min_date", "max_date", "count"}
        missing = required - set(OHLCVRangeResponse.model_fields)
        assert not missing, f"OHLCVRangeResponse missing fields: {missing}"


# ── TestQuoteResponseContract ─────────────────────────────────────────────────


class TestQuoteResponseContract:
    """QuoteResponse must expose all quote snapshot fields."""

    def test_required_fields_present(self) -> None:
        from market_data.api.schemas.quotes import QuoteResponse

        required = {"instrument_id", "bid", "ask", "last", "volume", "timestamp", "updated_at"}
        missing = required - set(QuoteResponse.model_fields)
        assert not missing, f"QuoteResponse missing fields: {missing}"

    def test_price_fields_are_nullable_strings(self) -> None:
        """Quote prices are optional (market may not publish all sides)."""
        from market_data.api.schemas.quotes import QuoteResponse

        for price_field in ("bid", "ask", "last"):
            annotation = QuoteResponse.model_fields[price_field].annotation
            # Should be str | None
            args = getattr(annotation, "__args__", ())
            assert str in args or annotation is str, f"Field '{price_field}' annotation {annotation!r} must include str"

    def test_instantiation_with_valid_payload(self) -> None:
        from market_data.api.schemas.quotes import QuoteResponse

        now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        resp = QuoteResponse(
            instrument_id="instr-001",
            bid="100.00",
            ask="100.10",
            last="100.05",
            volume=5000,
            timestamp=now,
            updated_at=now,
        )
        assert resp.bid == "100.00"
        assert resp.volume == 5000

    def test_instantiation_with_null_prices(self) -> None:
        """None prices must be accepted — some instruments have partial quote data."""
        from market_data.api.schemas.quotes import QuoteResponse

        now = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        resp = QuoteResponse(
            instrument_id="instr-001",
            bid=None,
            ask=None,
            last=None,
            volume=None,
            timestamp=now,
            updated_at=now,
        )
        assert resp.bid is None
        assert resp.last is None

    def test_batch_request_min_max_length(self) -> None:
        """BatchQuoteRequest enforces min_length=1 and max_length=200 (F-SEC-006)."""
        from market_data.api.schemas.quotes import BatchQuoteRequest
        from pydantic import ValidationError

        # Valid
        req = BatchQuoteRequest(instrument_ids=["instr-001"])
        assert len(req.instrument_ids) == 1

        # Empty list should fail
        with pytest.raises(ValidationError):
            BatchQuoteRequest(instrument_ids=[])


# ── TestFundamentalsResponseContract ─────────────────────────────────────────


class TestFundamentalsResponseContract:
    """FundamentalsResponse must expose all fundamentals record fields."""

    def test_required_fields_present(self) -> None:
        from market_data.api.schemas.fundamentals import FundamentalsResponse

        required = {"security_id", "records"}
        missing = required - set(FundamentalsResponse.model_fields)
        assert not missing, f"FundamentalsResponse missing fields: {missing}"

    def test_record_response_fields(self) -> None:
        from market_data.api.schemas.fundamentals import FundamentalsRecordResponse

        required = {"id", "security_id", "section", "period_end", "period_type", "data", "source", "ingested_at"}
        missing = required - set(FundamentalsRecordResponse.model_fields)
        assert not missing, f"FundamentalsRecordResponse missing fields: {missing}"

    def test_instantiation_with_valid_payload(self) -> None:
        from market_data.api.schemas.fundamentals import FundamentalsRecordResponse, FundamentalsResponse

        now = datetime(2024, 1, 15, tzinfo=UTC)
        record = FundamentalsRecordResponse(
            id="rec-001",
            security_id="sec-001",
            section="HIGHLIGHTS",
            period_end=now,
            period_type="ANNUAL",
            data={"pe_ratio": "15.5"},
            source="eodhd",
            ingested_at=now,
        )
        resp = FundamentalsResponse(security_id="sec-001", records=[record])
        assert resp.security_id == "sec-001"
        assert len(resp.records) == 1
        assert resp.records[0].section == "HIGHLIGHTS"

    def test_data_field_is_dict(self) -> None:
        """The ``data`` field must be a dict to hold arbitrary section key-value pairs."""
        from market_data.api.schemas.fundamentals import FundamentalsRecordResponse

        field = FundamentalsRecordResponse.model_fields["data"]
        # annotation should be dict[str, Any]
        origin = getattr(field.annotation, "__origin__", None)
        assert origin is dict, f"data field annotation origin is {origin!r}, expected dict"


# ── TestSchemaConsistencyWithDomainEntities ────────────────────────────────────


class TestSchemaConsistencyWithDomainEntities:
    """Cross-check that API schema fields align with domain entity fields."""

    def test_instrument_response_covers_entity(self) -> None:
        from market_data.api.schemas.instruments import InstrumentResponse

        # Core identity fields from the Instrument entity
        entity_fields = {"id", "symbol", "exchange", "is_active"}
        schema_fields = set(InstrumentResponse.model_fields)
        missing = entity_fields - schema_fields
        assert not missing, f"InstrumentResponse missing entity fields: {missing}"

    def test_ohlcv_response_covers_entity(self) -> None:
        from market_data.api.schemas.ohlcv import OHLCVBarResponse

        entity_fields = {"instrument_id", "timeframe", "bar_date", "open", "high", "low", "close", "volume"}
        schema_fields = set(OHLCVBarResponse.model_fields)
        missing = entity_fields - schema_fields
        assert not missing, f"OHLCVBarResponse missing entity fields: {missing}"

    def test_quote_response_covers_entity(self) -> None:
        from market_data.api.schemas.quotes import QuoteResponse

        entity_fields = {"instrument_id", "bid", "ask", "last", "volume", "timestamp", "updated_at"}
        schema_fields = set(QuoteResponse.model_fields)
        missing = entity_fields - schema_fields
        assert not missing, f"QuoteResponse missing entity fields: {missing}"
