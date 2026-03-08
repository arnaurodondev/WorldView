"""Tests for storage.exceptions."""

from __future__ import annotations

import pytest

from storage.exceptions import (
    BucketNotFoundError,
    InvalidObjectKeyError,
    ObjectNotFoundError,
    StorageError,
    StoragePermissionError,
    StorageUnavailableError,
)


class TestExceptionHierarchy:
    def test_object_not_found_is_storage_error(self) -> None:
        assert issubclass(ObjectNotFoundError, StorageError)

    def test_bucket_not_found_is_storage_error(self) -> None:
        assert issubclass(BucketNotFoundError, StorageError)

    def test_permission_error_is_storage_error(self) -> None:
        assert issubclass(StoragePermissionError, StorageError)

    def test_unavailable_is_storage_error(self) -> None:
        assert issubclass(StorageUnavailableError, StorageError)

    def test_invalid_key_is_storage_error(self) -> None:
        assert issubclass(InvalidObjectKeyError, StorageError)

    def test_invalid_key_is_also_value_error(self) -> None:
        """InvalidObjectKeyError must also inherit ValueError for backwards compat."""
        assert issubclass(InvalidObjectKeyError, ValueError)

    def test_storage_error_is_exception(self) -> None:
        assert issubclass(StorageError, Exception)

    def test_can_catch_all_as_storage_error(self) -> None:
        errors = [
            ObjectNotFoundError("not found"),
            BucketNotFoundError("no bucket"),
            StoragePermissionError("denied"),
            StorageUnavailableError("down"),
            InvalidObjectKeyError("bad key"),
        ]
        for err in errors:
            with pytest.raises(StorageError):
                raise err

    def test_object_not_found_message(self) -> None:
        exc = ObjectNotFoundError("bucket=test, key=my/key")
        assert "bucket=test" in str(exc)

    def test_invalid_key_can_be_caught_as_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise InvalidObjectKeyError("bad-key")
