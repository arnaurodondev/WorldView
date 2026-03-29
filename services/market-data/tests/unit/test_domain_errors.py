"""Unit tests for market_data domain error hierarchy."""

from __future__ import annotations

import pytest
from market_data.domain.errors import (
    DuplicateEventError,
    IngestionError,
    InstrumentNotFoundError,
    MarketDataError,
    ParseError,
    SecurityNotFoundError,
    StaleDataError,
)

pytestmark = pytest.mark.unit


class TestErrorHierarchy:
    def test_error_hierarchy(self) -> None:
        assert issubclass(InstrumentNotFoundError, MarketDataError)
        assert issubclass(SecurityNotFoundError, MarketDataError)
        assert issubclass(DuplicateEventError, MarketDataError)
        assert issubclass(IngestionError, MarketDataError)
        assert issubclass(ParseError, MarketDataError)
        assert issubclass(StaleDataError, MarketDataError)
        assert issubclass(MarketDataError, Exception)

    def test_market_data_error_is_base(self) -> None:
        for cls in (
            InstrumentNotFoundError,
            SecurityNotFoundError,
            DuplicateEventError,
            IngestionError,
            ParseError,
            StaleDataError,
        ):
            assert issubclass(cls, MarketDataError), f"{cls} is not a subclass of MarketDataError"

    def test_parse_error_is_pure_domain(self) -> None:
        # ParseError must NOT inherit from any infrastructure lib (R12).
        # Consumers that need dead-lettering must catch ParseError and re-raise as FatalError.

        mro_names = [c.__module__ for c in ParseError.__mro__]
        assert not any(
            "messaging" in m for m in mro_names
        ), "ParseError must not inherit from the messaging lib (R12 violation)"

    def test_parse_error_is_market_data_error(self) -> None:
        err = ParseError("bad payload")
        assert isinstance(err, MarketDataError)
        assert isinstance(err, Exception)
        assert str(err) == "bad payload"

    def test_errors_are_raiseable(self) -> None:
        for cls in (
            MarketDataError,
            InstrumentNotFoundError,
            SecurityNotFoundError,
            DuplicateEventError,
            IngestionError,
            ParseError,
            StaleDataError,
        ):
            with pytest.raises(cls):
                raise cls("test")

    def test_market_data_error_caught_as_exception(self) -> None:
        with pytest.raises(Exception):  # noqa: B017
            raise InstrumentNotFoundError("not found")

    def test_parse_error_caught_as_market_data_error(self) -> None:
        with pytest.raises(MarketDataError):
            raise ParseError("unparseable")

    def test_error_message_preserved(self) -> None:
        err = InstrumentNotFoundError("instrument-42 not found")
        assert str(err) == "instrument-42 not found"

    def test_duplicate_event_error_message(self) -> None:
        err = DuplicateEventError("event-id-123 already processed")
        assert "event-id-123" in str(err)
