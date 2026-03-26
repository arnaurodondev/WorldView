"""Unit tests for domain error hierarchy."""

from __future__ import annotations

import pytest
from content_store.domain.errors import (
    BronzeObjectNotFoundError,
    ConfigurationError,
    DeduplicationError,
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    DomainError,
    HashComputationError,
    LSHLookupError,
    StorageError,
)

pytestmark = pytest.mark.unit


class TestErrorHierarchy:
    def test_domain_error_is_base(self) -> None:
        assert issubclass(DocumentNotFoundError, DomainError)
        assert issubclass(DeduplicationError, DomainError)
        assert issubclass(StorageError, DomainError)
        assert issubclass(ConfigurationError, DomainError)

    def test_dedup_subclasses(self) -> None:
        assert issubclass(HashComputationError, DeduplicationError)
        assert issubclass(LSHLookupError, DeduplicationError)

    def test_storage_subclasses(self) -> None:
        assert issubclass(BronzeObjectNotFoundError, StorageError)

    def test_document_errors(self) -> None:
        assert issubclass(DocumentAlreadyExistsError, DomainError)

    def test_error_messages(self) -> None:
        err = DocumentNotFoundError("doc-123 not found")
        assert str(err) == "doc-123 not found"
