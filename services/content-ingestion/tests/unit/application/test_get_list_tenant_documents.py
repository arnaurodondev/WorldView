"""Unit tests for GetTenantDocumentUseCase and ListTenantDocumentsUseCase.

PLAN-0086 Wave E-1.

Tests:
  1. Get — happy path returns domain entity
  2. Get — wrong tenant returns None (no exception)
  3. List — happy path with no cursor
  4. List — full page sets next_cursor
  5. List — cursor encode/decode roundtrip
  6. List — partial page → next_cursor is None
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from content_ingestion.application.use_cases.get_tenant_document import GetTenantDocumentUseCase
from content_ingestion.application.use_cases.list_tenant_documents import (
    ListResult,
    ListTenantDocumentsUseCase,
    _decode_cursor,
    _encode_cursor,
)
from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus

pytestmark = pytest.mark.unit

# ── Shared fixtures ───────────────────────────────────────────────────────────

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DOC_ID = UUID("00000000-0000-0000-0000-000000000099")
DOC_ID_2 = UUID("00000000-0000-0000-0000-000000000098")
USER_ID = UUID("00000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)
VALID_HASH = "a" * 64


def _make_read_uow() -> AsyncMock:
    """Return a mock read-only UoW that works as an async context manager."""
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return uow


def _make_doc(doc_id: UUID = DOC_ID, uploaded_at: datetime = NOW) -> TenantDocumentUpload:
    """Construct a minimal valid TenantDocumentUpload for tests."""
    return TenantDocumentUpload(
        id=doc_id,
        tenant_id=TENANT_ID,
        uploaded_by_user_id=USER_ID,
        filename="test.pdf",
        title="Test Doc",
        content_type="application/pdf",
        content_hash=VALID_HASH,
        byte_size=1024,
        minio_bronze_key=f"tenant-uploads/{TENANT_ID}/{doc_id}/bronze/test.pdf",
        status=UploadStatus.PROCESSING,
        uploaded_at=uploaded_at,
    )


# ── GetTenantDocumentUseCase tests ────────────────────────────────────────────


class TestGetTenantDocumentUseCase:
    async def test_happy_path_returns_entity(self) -> None:
        """Existing document is returned when tenant matches."""
        doc = _make_doc()
        repo = AsyncMock()
        repo.get = AsyncMock(return_value=doc)
        uow = _make_read_uow()

        result = await GetTenantDocumentUseCase(repo=repo, uow=uow).execute(DOC_ID, TENANT_ID)

        assert result is doc
        repo.get.assert_awaited_once_with(DOC_ID, TENANT_ID)

    async def test_wrong_tenant_returns_none(self) -> None:
        """Repository returns None for wrong tenant — use case propagates that."""
        repo = AsyncMock()
        repo.get = AsyncMock(return_value=None)
        uow = _make_read_uow()

        result = await GetTenantDocumentUseCase(repo=repo, uow=uow).execute(
            DOC_ID, UUID("00000000-0000-0000-0000-000000000099")
        )

        assert result is None


# ── ListTenantDocumentsUseCase tests ──────────────────────────────────────────


class TestCursorEncoding:
    def test_encode_decode_roundtrip(self) -> None:
        """A cursor encoded from (uploaded_at, doc_id) must decode back to the same values."""
        cursor = _encode_cursor(NOW, DOC_ID)
        decoded_dt, decoded_id = _decode_cursor(cursor)

        assert decoded_dt == NOW
        assert decoded_id == DOC_ID

    def test_malformed_cursor_raises_value_error(self) -> None:
        """A cursor that is not valid base64 must raise ValueError."""
        with pytest.raises(ValueError, match="Invalid pagination cursor"):
            _decode_cursor("not!!valid!!base64!!")


class TestListTenantDocumentsUseCase:
    async def test_happy_path_no_cursor(self) -> None:
        """First page with no cursor returns items and total."""
        doc = _make_doc()
        repo = AsyncMock()
        repo.list_by_tenant = AsyncMock(return_value=([doc], 1))
        uow = _make_read_uow()

        result = await ListTenantDocumentsUseCase(repo=repo, uow=uow).execute(tenant_id=TENANT_ID, limit=20)

        assert isinstance(result, ListResult)
        assert result.items == [doc]
        assert result.total == 1
        # Only one item returned (< limit=20) → no next page.
        assert result.next_cursor is None

    async def test_full_page_sets_next_cursor(self) -> None:
        """When len(items) == limit a next_cursor must be returned."""
        docs = [_make_doc(DOC_ID, NOW), _make_doc(DOC_ID_2, NOW)]
        repo = AsyncMock()
        repo.list_by_tenant = AsyncMock(return_value=(docs, 10))
        uow = _make_read_uow()

        result = await ListTenantDocumentsUseCase(repo=repo, uow=uow).execute(tenant_id=TENANT_ID, limit=2)

        assert result.next_cursor is not None
        # Cursor must decode to the last item's (uploaded_at, id).
        decoded_dt, decoded_id = _decode_cursor(result.next_cursor)
        last = docs[-1]
        assert decoded_dt == last.uploaded_at
        assert decoded_id == last.id

    async def test_partial_page_has_no_next_cursor(self) -> None:
        """When fewer items than limit are returned, next_cursor must be None."""
        docs = [_make_doc()]
        repo = AsyncMock()
        repo.list_by_tenant = AsyncMock(return_value=(docs, 1))
        uow = _make_read_uow()

        result = await ListTenantDocumentsUseCase(repo=repo, uow=uow).execute(tenant_id=TENANT_ID, limit=20)

        assert result.next_cursor is None

    async def test_cursor_is_decoded_and_passed_to_repo(self) -> None:
        """When a cursor is supplied it must be decoded and forwarded to the repo."""
        cursor = _encode_cursor(NOW, DOC_ID)
        repo = AsyncMock()
        repo.list_by_tenant = AsyncMock(return_value=([], 0))
        uow = _make_read_uow()

        await ListTenantDocumentsUseCase(repo=repo, uow=uow).execute(tenant_id=TENANT_ID, limit=20, cursor=cursor)

        call_kwargs = repo.list_by_tenant.call_args.kwargs
        # The cursor passed to the repo must be the decoded tuple.
        assert call_kwargs["cursor"] == (NOW, DOC_ID)
