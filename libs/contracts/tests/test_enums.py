"""Unit tests for shared contract enums."""

from __future__ import annotations

from enum import StrEnum

import pytest

from contracts.enums import ContentSourceType

pytestmark = pytest.mark.unit


class TestContentSourceType:
    def test_is_str_enum(self) -> None:
        assert issubclass(ContentSourceType, StrEnum)

    def test_all_five_values(self) -> None:
        expected = {"eodhd", "sec_edgar", "finnhub", "newsapi", "manual"}
        assert {v.value for v in ContentSourceType} == expected

    def test_member_count(self) -> None:
        assert len(ContentSourceType) == 5

    def test_string_comparison(self) -> None:
        assert ContentSourceType.EODHD == "eodhd"
        assert ContentSourceType.SEC_EDGAR == "sec_edgar"
        assert ContentSourceType.FINNHUB == "finnhub"
        assert ContentSourceType.NEWSAPI == "newsapi"
        assert ContentSourceType.MANUAL == "manual"

    def test_importable_from_root(self) -> None:
        from contracts import ContentSourceType as RootType

        assert RootType is ContentSourceType
