"""Unit tests for common.ids module."""

from __future__ import annotations

import time
import uuid

from common.ids import new_ulid, new_uuid, new_uuid_str


class TestNewUuid:
    def test_returns_uuid_type(self) -> None:
        result = new_uuid()
        assert isinstance(result, uuid.UUID)

    def test_is_version_4(self) -> None:
        result = new_uuid()
        assert result.version == 4

    def test_unique(self) -> None:
        a = new_uuid()
        b = new_uuid()
        assert a != b

    def test_multiple_unique(self) -> None:
        ids = [new_uuid() for _ in range(100)]
        assert len(set(ids)) == 100


class TestNewUuidStr:
    def test_returns_str(self) -> None:
        result = new_uuid_str()
        assert isinstance(result, str)

    def test_valid_uuid_format(self) -> None:
        result = new_uuid_str()
        # Should not raise ValueError
        parsed = uuid.UUID(result)
        assert parsed.version == 4

    def test_unique(self) -> None:
        a = new_uuid_str()
        b = new_uuid_str()
        assert a != b

    def test_standard_hyphenated_format(self) -> None:
        result = new_uuid_str()
        # UUIDv4 str has format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx (36 chars)
        assert len(result) == 36
        parts = result.split("-")
        assert len(parts) == 5


class TestNewUlid:
    def test_returns_str(self) -> None:
        result = new_ulid()
        assert isinstance(result, str)

    def test_length_is_26(self) -> None:
        result = new_ulid()
        assert len(result) == 26

    def test_unique(self) -> None:
        a = new_ulid()
        b = new_ulid()
        assert a != b

    def test_time_ordered(self) -> None:
        a = new_ulid()
        time.sleep(0.01)
        b = new_ulid()
        # ULIDs are lexicographically sortable by time
        assert b >= a

    def test_uppercase(self) -> None:
        result = new_ulid()
        assert result == result.upper()
