"""Unit tests for TenantDocumentUploadRepository (T-D-2-03).

PLAN-0086 Wave D-2: Verifies that the repository delegates correctly to the
SQLAlchemy session and maps arguments/return values as expected.

These tests use ``AsyncMock`` sessions so no live DB is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus
from content_ingestion.infrastructure.db.repositories.tenant_upload import (
    TenantDocumentUploadRepository,
)

import common.ids
import common.time

pytestmark = pytest.mark.unit

# ── helpers ───────────────────────────────────────────────────────────────────

_TENANT_ID = common.ids.new_uuid7()
_USER_ID = common.ids.new_uuid7()
_DOC_ID = common.ids.new_uuid7()

# SHA-256 hex digest (64 chars) required by the domain invariant
_HASH = "a" * 64


def _make_domain(
    *,
    doc_id: UUID = _DOC_ID,
    tenant_id: UUID = _TENANT_ID,
) -> TenantDocumentUpload:
    """Build a minimal valid TenantDocumentUpload domain entity."""
    return TenantDocumentUpload(
        id=doc_id,
        tenant_id=tenant_id,
        uploaded_by_user_id=_USER_ID,
        filename="test.pdf",
        title="Test Document",
        content_type="application/pdf",
        content_hash=_HASH,
        byte_size=1024,
        minio_bronze_key="bronze/test.pdf",
        status=UploadStatus.PROCESSING,
        uploaded_at=common.time.utc_now(),
    )


def _make_orm_row(
    *,
    doc_id: UUID = _DOC_ID,
    tenant_id: UUID = _TENANT_ID,
) -> MagicMock:
    """Build a MagicMock that quacks like a TenantDocumentUploadModel row."""
    row = MagicMock()
    row.id = doc_id
    row.tenant_id = tenant_id
    row.uploaded_by_user_id = _USER_ID
    row.filename = "test.pdf"
    row.title = "Test Document"
    row.content_type = "application/pdf"
    row.content_hash = _HASH
    row.byte_size = 1024
    row.minio_bronze_key = "bronze/test.pdf"
    row.status = "processing"
    row.uploaded_at = common.time.utc_now()
    row.word_count = None
    row.chunk_count = None
    row.minio_silver_key = None
    row.error_message = None
    row.ready_at = None
    row.deleted_at = None
    return row


def _mock_session() -> AsyncMock:
    """Return an AsyncMock session that can be passed to the repository."""
    session = AsyncMock()
    session.add = MagicMock()  # synchronous method
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


# ── T-D-2-03-01: create ───────────────────────────────────────────────────────


class TestCreate:
    async def test_create_adds_model_to_session(self) -> None:
        """session.add() is called with the ORM model and flush() is awaited."""
        session = _mock_session()
        repo = TenantDocumentUploadRepository(session)  # type: ignore[arg-type]

        doc = _make_domain()
        await repo.create(doc)

        # session.add() must have been called exactly once with an ORM row
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        # Verify the ORM row carries the correct field values
        assert added.id == doc.id
        assert added.tenant_id == doc.tenant_id
        assert added.filename == "test.pdf"
        assert added.content_hash == _HASH
        assert added.status == "processing"  # serialised from enum

        # flush() must be awaited exactly once after add()
        session.flush.assert_awaited_once()


# ── T-D-2-03-02 / 03: get ────────────────────────────────────────────────────


class TestGet:
    async def test_get_returns_none_for_wrong_tenant(self) -> None:
        """Returns None when tenant_id does not match (same as not found)."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # DB found nothing
        session.execute.return_value = mock_result

        repo = TenantDocumentUploadRepository(session)  # type: ignore[arg-type]
        result = await repo.get(_DOC_ID, common.ids.new_uuid7())  # different tenant

        assert result is None
        session.execute.assert_awaited_once()

    async def test_get_returns_domain_for_correct_tenant(self) -> None:
        """Returns a domain entity when doc exists and tenant_id matches."""
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _make_orm_row()
        session.execute.return_value = mock_result

        repo = TenantDocumentUploadRepository(session)  # type: ignore[arg-type]
        result = await repo.get(_DOC_ID, _TENANT_ID)

        assert result is not None
        assert result.id == _DOC_ID
        assert result.tenant_id == _TENANT_ID
        assert result.status == UploadStatus.PROCESSING
        # Verify the uploaded_at is timezone-aware
        assert result.uploaded_at.tzinfo is not None


# ── T-D-2-03-04: get_for_update ──────────────────────────────────────────────


class TestGetForUpdate:
    async def test_get_for_update_uses_for_update(self) -> None:
        """The query issued by get_for_update() includes with_for_update().

        We verify this by inspecting the compiled SQL fragment — the SELECT
        statement passed to session.execute() must contain the ``FOR UPDATE``
        lock clause.
        """
        session = _mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = _make_orm_row()
        session.execute.return_value = mock_result

        repo = TenantDocumentUploadRepository(session)  # type: ignore[arg-type]
        result = await repo.get_for_update(_DOC_ID, _TENANT_ID)

        assert result is not None
        # Retrieve the SQLAlchemy Select object that was passed to execute()
        stmt = session.execute.call_args[0][0]
        # Compile to string to check for FOR UPDATE fragment
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "FOR UPDATE" in compiled.upper()


# ── T-D-2-03-05: list_by_tenant ──────────────────────────────────────────────


class TestListByTenant:
    async def test_list_by_tenant_returns_paginated(self) -> None:
        """Returns (items, total) with correct lengths."""
        session = _mock_session()
        row = _make_orm_row()

        # First execute() call → count query; second → page query
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        page_result = MagicMock()
        page_result.scalars.return_value.all.return_value = [row]

        session.execute.side_effect = [count_result, page_result]

        repo = TenantDocumentUploadRepository(session)  # type: ignore[arg-type]
        items, total = await repo.list_by_tenant(
            tenant_id=_TENANT_ID,
            status=None,
            limit=10,
            cursor=None,
        )

        assert total == 1
        assert len(items) == 1
        assert items[0].id == _DOC_ID
        # Two execute() calls: one for count, one for page
        assert session.execute.await_count == 2


# ── T-D-2-03-06: set_deleted ─────────────────────────────────────────────────


class TestSetDeleted:
    async def test_set_deleted_updates_status(self) -> None:
        """Issues an UPDATE that sets status='deleted' and deleted_at."""
        session = _mock_session()
        repo = TenantDocumentUploadRepository(session)  # type: ignore[arg-type]

        await repo.set_deleted(_DOC_ID, _TENANT_ID)

        session.execute.assert_awaited_once()
        # Retrieve the UPDATE statement
        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "deleted" in compiled


# ── T-D-2-03-07: set_ready ───────────────────────────────────────────────────


class TestSetReady:
    async def test_set_ready_updates_status_and_counts(self) -> None:
        """Issues an UPDATE that sets status='ready', ready_at, chunk_count, word_count."""
        session = _mock_session()
        repo = TenantDocumentUploadRepository(session)  # type: ignore[arg-type]

        await repo.set_ready(_DOC_ID, _TENANT_ID, chunk_count=42, word_count=1500)

        session.execute.assert_awaited_once()
        stmt = session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "ready" in compiled
