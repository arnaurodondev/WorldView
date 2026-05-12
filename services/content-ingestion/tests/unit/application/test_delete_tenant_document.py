"""Unit tests for DeleteTenantDocumentUseCase.

PLAN-0086 Wave E-1.

Tests:
  1. Happy path — status set to DELETED, outbox event appended, commit called.
  2. Document not found → NotFoundError.
  3. Document already deleted → AlreadyDeletedError.
  4. Outbox append called with correct topic and payload fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from content_ingestion.application.use_cases.delete_tenant_document import DeleteTenantDocumentUseCase
from content_ingestion.domain.exceptions import AlreadyDeletedError, NotFoundError
from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus

pytestmark = pytest.mark.unit

# ── Shared fixtures ───────────────────────────────────────────────────────────

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DOC_ID = UUID("00000000-0000-0000-0000-000000000099")
USER_ID = UUID("00000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000077")
NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
VALID_HASH = "a" * 64


def _make_write_uow() -> AsyncMock:
    """Return a mock write UoW that works as an async context manager."""
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    return uow


def _make_doc(status: UploadStatus = UploadStatus.PROCESSING) -> TenantDocumentUpload:
    return TenantDocumentUpload(
        id=DOC_ID,
        tenant_id=TENANT_ID,
        uploaded_by_user_id=USER_ID,
        filename="report.pdf",
        title="Annual Report",
        content_type="application/pdf",
        content_hash=VALID_HASH,
        byte_size=2048,
        minio_bronze_key=f"tenant-uploads/{TENANT_ID}/{DOC_ID}/bronze/report.pdf",
        status=status,
        uploaded_at=NOW,
    )


def _make_use_case(
    doc: TenantDocumentUpload | None = None,
) -> tuple[DeleteTenantDocumentUseCase, AsyncMock, AsyncMock, AsyncMock]:
    """Build the use case with mocked dependencies.

    Returns:
        (use_case, upload_repo, outbox, uow)
    """
    upload_repo = AsyncMock()
    upload_repo.get_for_update = AsyncMock(return_value=doc)
    upload_repo.set_deleted = AsyncMock()

    outbox = AsyncMock()
    outbox.append = AsyncMock()

    uow = _make_write_uow()

    uc = DeleteTenantDocumentUseCase(
        upload_repo=upload_repo,
        outbox=outbox,
        uow=uow,
    )
    return uc, upload_repo, outbox, uow


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestDeleteTenantDocumentUseCase:
    async def test_happy_path_deletes_and_commits(self) -> None:
        """A PROCESSING document should be soft-deleted and the UoW committed."""
        doc = _make_doc(UploadStatus.PROCESSING)
        uc, upload_repo, _outbox, uow = _make_use_case(doc=doc)

        with (
            patch("common.ids.new_uuid7", return_value=EVENT_ID),
            patch("common.time.utc_now", return_value=NOW),
        ):
            await uc.execute(DOC_ID, TENANT_ID)

        upload_repo.set_deleted.assert_awaited_once_with(DOC_ID, TENANT_ID)
        uow.commit.assert_awaited_once()

    async def test_outbox_event_appended_with_correct_topic(self) -> None:
        """The outbox append call must use the correct topic and payload fields."""
        doc = _make_doc(UploadStatus.PROCESSING)
        uc, _, outbox, _ = _make_use_case(doc=doc)

        with (
            patch("common.ids.new_uuid7", return_value=EVENT_ID),
            patch("common.time.utc_now", return_value=NOW),
        ):
            await uc.execute(DOC_ID, TENANT_ID)

        outbox.append.assert_awaited_once()
        call_kwargs = outbox.append.call_args.kwargs
        assert call_kwargs["topic"] == "content.document.deleted.v1"
        assert call_kwargs["aggregate_type"] == "content_document"
        assert call_kwargs["aggregate_id"] == DOC_ID
        payload = call_kwargs["payload"]
        assert payload["doc_id"] == str(DOC_ID)
        assert payload["tenant_id"] == str(TENANT_ID)
        assert payload["schema_version"] == 1

    async def test_not_found_raises(self) -> None:
        """When get_for_update returns None, NotFoundError must be raised."""
        uc, _, _, _ = _make_use_case(doc=None)

        with pytest.raises(NotFoundError):
            await uc.execute(DOC_ID, TENANT_ID)

    async def test_already_deleted_raises(self) -> None:
        """When the document is already DELETED, AlreadyDeletedError must be raised."""
        doc = _make_doc(UploadStatus.DELETED)
        uc, upload_repo, _, _ = _make_use_case(doc=doc)

        with pytest.raises(AlreadyDeletedError):
            await uc.execute(DOC_ID, TENANT_ID)

        # set_deleted must NOT be called if the document is already deleted.
        upload_repo.set_deleted.assert_not_awaited()

    async def test_ready_doc_can_be_deleted(self) -> None:
        """A READY document (pipeline complete) should also be deletable."""
        doc = _make_doc(UploadStatus.READY)
        uc, upload_repo, _, uow = _make_use_case(doc=doc)

        with (
            patch("common.ids.new_uuid7", return_value=EVENT_ID),
            patch("common.time.utc_now", return_value=NOW),
        ):
            await uc.execute(DOC_ID, TENANT_ID)

        upload_repo.set_deleted.assert_awaited_once_with(DOC_ID, TENANT_ID)
        uow.commit.assert_awaited_once()
