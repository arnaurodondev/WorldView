"""Unit tests for shared contract enums."""

from __future__ import annotations

from enum import StrEnum

import pytest

from contracts.enums import ContentSourceType, IngestionTaskStatus

pytestmark = pytest.mark.unit


class TestContentSourceType:
    def test_is_str_enum(self) -> None:
        assert issubclass(ContentSourceType, StrEnum)

    def test_all_values(self) -> None:
        # PLAN-0106: EODHD_TICKER_NEWS added as a dedicated ticker-news adapter.
        # PLAN-0056: Polymarket deeper-stream sources (CLOB / data-api trades &
        # open-interest / gamma events) added for prediction-market ingestion.
        expected = {
            "eodhd",
            "eodhd_ticker_news",
            "sec_edgar",
            "finnhub",
            "newsapi",
            "manual",
            "polymarket",
            "polymarket_gamma_events",
            "polymarket_clob",
            "polymarket_data_trades",
            "polymarket_data_oi",
            "tenant_upload",
        }
        assert {v.value for v in ContentSourceType} == expected

    def test_member_count(self) -> None:
        assert len(ContentSourceType) == 12

    def test_string_comparison(self) -> None:
        assert ContentSourceType.EODHD == "eodhd"
        assert ContentSourceType.EODHD_TICKER_NEWS == "eodhd_ticker_news"
        assert ContentSourceType.SEC_EDGAR == "sec_edgar"
        assert ContentSourceType.FINNHUB == "finnhub"
        assert ContentSourceType.NEWSAPI == "newsapi"
        assert ContentSourceType.MANUAL == "manual"
        assert ContentSourceType.POLYMARKET == "polymarket"
        assert ContentSourceType.TENANT_UPLOAD == "tenant_upload"

    def test_content_source_type_polymarket(self) -> None:
        assert ContentSourceType.POLYMARKET == "polymarket"

    def test_polymarket_in_all_values(self) -> None:
        assert "polymarket" in [v.value for v in ContentSourceType]

    def test_importable_from_root(self) -> None:
        from contracts import ContentSourceType as RootType

        assert RootType is ContentSourceType


class TestIngestionTaskStatus:
    def test_is_str_enum(self) -> None:
        assert issubclass(IngestionTaskStatus, StrEnum)

    def test_all_six_values(self) -> None:
        expected = {"pending", "claimed", "running", "succeeded", "retry", "failed"}
        assert {v.value for v in IngestionTaskStatus} == expected

    def test_member_count(self) -> None:
        assert len(IngestionTaskStatus) == 6

    def test_string_comparison(self) -> None:
        assert IngestionTaskStatus.PENDING == "pending"
        assert IngestionTaskStatus.CLAIMED == "claimed"
        assert IngestionTaskStatus.RUNNING == "running"
        assert IngestionTaskStatus.SUCCEEDED == "succeeded"
        assert IngestionTaskStatus.RETRY == "retry"
        assert IngestionTaskStatus.FAILED == "failed"

    def test_from_string(self) -> None:
        assert IngestionTaskStatus("pending") is IngestionTaskStatus.PENDING
        assert IngestionTaskStatus("claimed") is IngestionTaskStatus.CLAIMED
        assert IngestionTaskStatus("failed") is IngestionTaskStatus.FAILED

    def test_claimable_states(self) -> None:
        """Only PENDING and RETRY are valid states from which a task can be claimed."""
        claimable = {IngestionTaskStatus.PENDING, IngestionTaskStatus.RETRY}
        non_claimable = {s for s in IngestionTaskStatus if s not in claimable}
        assert non_claimable == {
            IngestionTaskStatus.CLAIMED,
            IngestionTaskStatus.RUNNING,
            IngestionTaskStatus.SUCCEEDED,
            IngestionTaskStatus.FAILED,
        }

    def test_importable_from_root(self) -> None:
        from contracts import IngestionTaskStatus as RootType

        assert RootType is IngestionTaskStatus
