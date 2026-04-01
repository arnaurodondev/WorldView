"""Unit tests for shared messaging enums."""

from __future__ import annotations

from enum import StrEnum

import pytest

from messaging.enums import OutboxStatus

pytestmark = pytest.mark.unit


class TestOutboxStatus:
    def test_is_str_enum(self) -> None:
        assert issubclass(OutboxStatus, StrEnum)

    def test_all_five_values(self) -> None:
        expected = {"pending", "processing", "delivered", "failed", "dead_letter"}
        assert {v.value for v in OutboxStatus} == expected

    def test_member_count(self) -> None:
        assert len(OutboxStatus) == 5

    def test_string_comparison(self) -> None:
        assert OutboxStatus.PENDING == "pending"
        assert OutboxStatus.PROCESSING == "processing"
        assert OutboxStatus.DELIVERED == "delivered"
        assert OutboxStatus.FAILED == "failed"
        assert OutboxStatus.DEAD_LETTER == "dead_letter"

    def test_importable_from_root(self) -> None:
        from messaging import OutboxStatus as RootOutboxStatus

        assert RootOutboxStatus is OutboxStatus
