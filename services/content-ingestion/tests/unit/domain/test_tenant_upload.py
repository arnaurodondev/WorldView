"""Unit tests for TenantDocumentUpload entity and UploadStatus enum.

PLAN-0086 Wave D-1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID

import pytest
from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
USER_ID = UUID("00000000-0000-0000-0000-000000000002")
VALID_HASH = "a" * 64  # 64-char hex string (valid SHA-256 placeholder)
VALID_AT = datetime(2026, 1, 1, tzinfo=UTC)
DOC_ID = UUID("00000000-0000-0000-0000-000000000099")


def _make_upload(**overrides: object) -> TenantDocumentUpload:
    """Construct a minimal valid TenantDocumentUpload for testing."""
    defaults: dict[str, object] = {
        "id": DOC_ID,
        "tenant_id": TENANT_ID,
        "uploaded_by_user_id": USER_ID,
        "filename": "test.pdf",
        "title": "Test Document",
        "content_type": "application/pdf",
        "content_hash": VALID_HASH,
        "byte_size": 1024,
        "minio_bronze_key": "tenant-uploads/test/bronze/test.pdf",
        "status": UploadStatus.PROCESSING,
        "uploaded_at": VALID_AT,
    }
    defaults.update(overrides)
    return TenantDocumentUpload(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Factory method
# ---------------------------------------------------------------------------


class TestCreateFactory:
    def test_create_sets_status_processing(self) -> None:
        """New uploads must start in PROCESSING state."""
        with (
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=VALID_AT),
        ):
            doc = TenantDocumentUpload.create(
                tenant_id=TENANT_ID,
                uploaded_by_user_id=USER_ID,
                filename="test.pdf",
                title="Test",
                content_type="application/pdf",
                content_hash=VALID_HASH,
                byte_size=1024,
                minio_bronze_key="tenant-uploads/test/bronze/test.pdf",
            )
        assert doc.status == UploadStatus.PROCESSING

    def test_create_pipeline_fields_are_none(self) -> None:
        """Pipeline output fields must be None immediately after creation."""
        with (
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=VALID_AT),
        ):
            doc = TenantDocumentUpload.create(
                tenant_id=TENANT_ID,
                uploaded_by_user_id=USER_ID,
                filename="test.pdf",
                title="Test",
                content_type="application/pdf",
                content_hash=VALID_HASH,
                byte_size=1024,
                minio_bronze_key="key",
            )
        assert doc.word_count is None
        assert doc.chunk_count is None
        assert doc.minio_silver_key is None
        assert doc.error_message is None
        assert doc.ready_at is None
        assert doc.deleted_at is None

    def test_create_uses_provided_arguments(self) -> None:
        """Factory should pass through all caller-supplied values."""
        with (
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=VALID_AT),
        ):
            doc = TenantDocumentUpload.create(
                tenant_id=TENANT_ID,
                uploaded_by_user_id=USER_ID,
                filename="annual-report.pdf",
                title="Annual Report 2025",
                content_type="application/pdf",
                content_hash=VALID_HASH,
                byte_size=2048,
                minio_bronze_key="tenant-uploads/tenantA/bronze/report.pdf",
            )
        assert doc.tenant_id == TENANT_ID
        assert doc.uploaded_by_user_id == USER_ID
        assert doc.filename == "annual-report.pdf"
        assert doc.title == "Annual Report 2025"
        assert doc.byte_size == 2048


# ---------------------------------------------------------------------------
# Invariant enforcement
# ---------------------------------------------------------------------------


class TestInvariants:
    def test_byte_size_zero_raises(self) -> None:
        """byte_size=0 is not a valid upload — must raise."""
        with pytest.raises(ValueError, match="byte_size must be > 0"):
            _make_upload(byte_size=0)

    def test_byte_size_negative_raises(self) -> None:
        """Negative byte_size is also invalid."""
        with pytest.raises(ValueError, match="byte_size must be > 0"):
            _make_upload(byte_size=-1)

    def test_invalid_hash_length_short_raises(self) -> None:
        """A hash shorter than 64 chars is not a SHA-256 digest."""
        with pytest.raises(ValueError, match="content_hash must be 64-char"):
            _make_upload(content_hash="abc")

    def test_invalid_hash_length_long_raises(self) -> None:
        """A hash longer than 64 chars is equally invalid."""
        with pytest.raises(ValueError, match="content_hash must be 64-char"):
            _make_upload(content_hash="a" * 65)

    def test_valid_hash_exactly_64_chars_accepted(self) -> None:
        """Exactly 64 chars is the only valid hash length."""
        doc = _make_upload(content_hash="b" * 64)
        assert len(doc.content_hash) == 64

    def test_naive_datetime_raises(self) -> None:
        """A tz-naive uploaded_at is a programming error — must raise."""
        naive_dt = datetime(2026, 1, 1)  # noqa: DTZ001
        with pytest.raises(ValueError, match="UTC-aware"):
            _make_upload(uploaded_at=naive_dt)

    def test_utc_aware_datetime_accepted(self) -> None:
        """A UTC-aware datetime must not raise."""
        doc = _make_upload(uploaded_at=datetime(2026, 6, 1, tzinfo=UTC))
        assert doc.uploaded_at.tzinfo is not None


# ---------------------------------------------------------------------------
# UploadStatus enum
# ---------------------------------------------------------------------------


class TestUploadStatus:
    def test_processing_value(self) -> None:
        assert UploadStatus.PROCESSING == "processing"

    def test_ready_value(self) -> None:
        assert UploadStatus.READY == "ready"

    def test_failed_value(self) -> None:
        assert UploadStatus.FAILED == "failed"

    def test_deleted_value(self) -> None:
        assert UploadStatus.DELETED == "deleted"

    def test_is_str_subclass(self) -> None:
        """UploadStatus is a str enum — values must be usable as strings."""
        assert isinstance(UploadStatus.PROCESSING, str)

    def test_all_four_statuses_present(self) -> None:
        """Exactly 4 statuses must exist — regression guard."""
        assert len(UploadStatus) == 4


# ---------------------------------------------------------------------------
# Frozen dataclass immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_cannot_mutate_status(self) -> None:
        """frozen=True means direct attribute assignment raises FrozenInstanceError."""
        doc = _make_upload()
        with pytest.raises(Exception):  # noqa: B017  (FrozenInstanceError)
            doc.status = UploadStatus.READY  # type: ignore[misc]

    def test_optional_fields_default_none(self) -> None:
        """All optional pipeline fields must default to None."""
        doc = _make_upload()
        assert doc.word_count is None
        assert doc.chunk_count is None
        assert doc.minio_silver_key is None
        assert doc.error_message is None
        assert doc.ready_at is None
        assert doc.deleted_at is None
