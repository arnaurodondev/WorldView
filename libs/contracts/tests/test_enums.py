"""Unit tests for shared contract enums."""

from __future__ import annotations

from enum import StrEnum

import pytest

from contracts.enums import ContentSourceType, IngestionTaskStatus

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
