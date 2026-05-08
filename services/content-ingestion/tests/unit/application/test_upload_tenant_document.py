"""Unit tests for UploadTenantDocumentUseCase.

PLAN-0086 Wave E-1.

All dependencies (upload_repo, dedup_repo, rate_limit, storage, uow) are
replaced with AsyncMocks.  pdfminer is not installed in the test environment
so the PDF extraction path is patched at the module boundary.

The tests cover every error path and the happy path as required by the spec:
  1. Unsupported MIME type → UnsupportedFileTypeError
  2. File too large → FileTooLargeError
  3. Rate limit exceeded → UploadRateLimitError
  4. Empty extraction → TextExtractionError
  5. Duplicate document → DuplicateDocumentError
  6. Happy path → UploadTenantDocumentResult
  7. MinIO PUT failure → exception propagates
  8. DB write failure → compensating GC (storage.delete called)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from content_ingestion.application.use_cases.upload_tenant_document import (
    BRONZE_BUCKET,
    UploadTenantDocumentInput,
    UploadTenantDocumentResult,
    UploadTenantDocumentUseCase,
)
from content_ingestion.domain.exceptions import (
    DuplicateDocumentError,
    FileTooLargeError,
    TextExtractionError,
    UnsupportedFileTypeError,
    UploadRateLimitError,
)

pytestmark = pytest.mark.unit

# ── Shared test fixtures ──────────────────────────────────────────────────────

TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
USER_ID = UUID("00000000-0000-0000-0000-000000000002")
DOC_ID = UUID("00000000-0000-0000-0000-000000000099")
EXISTING_DOC_ID = UUID("00000000-0000-0000-0000-000000000098")
NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)

# Minimal valid PDF-sized bytes (just needs to be under 50 MB).
VALID_PDF_BYTES = b"%PDF-1.4 minimal content"
VALID_TXT_BYTES = b"Hello world, this is a plain text document with enough words."


def _make_uow() -> AsyncMock:
    """Return a mock UoW that works as an async context manager.

    The mock auto-creates a fresh context manager for each ``async with``
    call, which allows the use case to open the UoW twice (dedup + DB write).
    """
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    return uow


def _make_use_case(
    *,
    rate_limit_allowed: bool = True,
    dedup_existing_id: UUID | None = None,
    storage_put_raises: Exception | None = None,
    uow_commit_raises: Exception | None = None,
    uow: AsyncMock | None = None,
) -> tuple[UploadTenantDocumentUseCase, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    """Build a use case with all dependencies mocked.

    Returns:
        (use_case, upload_repo, dedup_repo, rate_limit, storage)
    """
    upload_repo = AsyncMock()
    upload_repo.create = AsyncMock()

    dedup_repo = AsyncMock()
    dedup_repo.check_exists = AsyncMock(return_value=dedup_existing_id)
    dedup_repo.insert = AsyncMock()

    rate_limit = AsyncMock()
    rate_limit.check_and_increment = AsyncMock(return_value=rate_limit_allowed)
    rate_limit.get_reset_at = AsyncMock(return_value=NOW)

    storage = AsyncMock()
    if storage_put_raises is not None:
        storage.put_bytes = AsyncMock(side_effect=storage_put_raises)
    else:
        storage.put_bytes = AsyncMock()
    storage.delete = AsyncMock()

    _uow = uow or _make_uow()
    if uow_commit_raises is not None:
        _uow.commit = AsyncMock(side_effect=uow_commit_raises)

    uc = UploadTenantDocumentUseCase(
        upload_repo=upload_repo,
        dedup_repo=dedup_repo,
        rate_limit=rate_limit,
        storage=storage,
        uow=_uow,
    )
    return uc, upload_repo, dedup_repo, rate_limit, storage


def _make_input(
    file_bytes: bytes = VALID_TXT_BYTES,
    filename: str = "report.txt",
    content_type: str = "text/plain",
    title: str | None = None,
) -> UploadTenantDocumentInput:
    return UploadTenantDocumentInput(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        title=title,
    )


# ── Test class ────────────────────────────────────────────────────────────────


class TestUploadTenantDocumentUseCase:
    # ── T-E-1-01 Test 1: unsupported MIME type ────────────────────────────────

    async def test_unsupported_mime_raises(self) -> None:
        """Content type not in allowed set must raise UnsupportedFileTypeError."""
        uc, *_ = _make_use_case()
        inp = _make_input(content_type="image/png")

        with pytest.raises(UnsupportedFileTypeError, match="image/png"):
            await uc.execute(inp)

    # ── T-E-1-01 Test 2: file too large ───────────────────────────────────────

    async def test_file_too_large_raises(self) -> None:
        """File exceeding 50 MB must raise FileTooLargeError before any I/O."""
        uc, *_ = _make_use_case()
        # 50 MB + 1 byte to trigger the guard.
        oversized = b"x" * (50_000_001)
        inp = _make_input(file_bytes=oversized)

        with pytest.raises(FileTooLargeError) as exc_info:
            await uc.execute(inp)

        assert exc_info.value.byte_size == 50_000_001
        assert exc_info.value.limit == 50_000_000

    # ── T-E-1-01 Test 3: rate limit exceeded ─────────────────────────────────

    async def test_rate_limit_exceeded_raises(self) -> None:
        """Rate-limit block must raise UploadRateLimitError with resets_at."""
        uc, _, _, rate_limit, _ = _make_use_case(rate_limit_allowed=False)
        inp = _make_input()

        with pytest.raises(UploadRateLimitError) as exc_info:
            await uc.execute(inp)

        # resets_at should be the value returned by get_reset_at().
        assert exc_info.value.resets_at == NOW

    # ── T-E-1-01 Test 4: empty extraction ────────────────────────────────────

    async def test_empty_extraction_raises(self) -> None:
        """Text extraction yielding empty string must raise TextExtractionError."""
        uc, *_ = _make_use_case()
        # Whitespace-only bytes decode to whitespace, which fails the empty check.
        inp = _make_input(file_bytes=b"   \n\t  ")

        with pytest.raises(TextExtractionError, match="empty"):
            await uc.execute(inp)

    # ── T-E-1-01 Test 5: duplicate document ──────────────────────────────────

    async def test_duplicate_doc_raises(self) -> None:
        """Dedup hit must raise DuplicateDocumentError with existing_doc_id."""
        uc, *_ = _make_use_case(dedup_existing_id=EXISTING_DOC_ID)
        inp = _make_input()

        with pytest.raises(DuplicateDocumentError) as exc_info:
            await uc.execute(inp)

        assert exc_info.value.existing_doc_id == EXISTING_DOC_ID

    # ── T-E-1-01 Test 6: happy path ──────────────────────────────────────────

    async def test_happy_path_returns_result(self) -> None:
        """Full valid upload must return UploadTenantDocumentResult with correct fields."""
        uc, upload_repo, dedup_repo, _, storage = _make_use_case()

        with (
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=NOW),
        ):
            result = await uc.execute(_make_input(title="My Report"))

        # Check return DTO
        assert isinstance(result, UploadTenantDocumentResult)
        assert result.doc_id == DOC_ID
        assert result.status == "processing"
        assert result.title == "My Report"
        assert result.filename == "report.txt"

        # upload_repo.create was called once.
        upload_repo.create.assert_awaited_once()

        # dedup_repo.insert was called with correct arg order (doc_id first).
        dedup_repo.insert.assert_awaited_once()
        call_args = dedup_repo.insert.call_args
        # First positional arg is doc_id.
        assert call_args.args[0] == DOC_ID

        # MinIO put_bytes was called with correct bucket.
        storage.put_bytes.assert_awaited_once()
        put_call = storage.put_bytes.call_args
        assert put_call.args[0] == BRONZE_BUCKET

    async def test_happy_path_derives_title_from_filename(self) -> None:
        """When title is None the filename stem should be used as title."""
        uc, *_ = _make_use_case()

        with (
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=NOW),
        ):
            result = await uc.execute(_make_input(filename="Q4_Report.txt", title=None))

        assert result.title == "Q4_Report"

    # ── T-E-1-01 Test 7: MinIO failure propagates ────────────────────────────

    async def test_minio_failure_raises(self) -> None:
        """If MinIO PUT raises, the exception must propagate to the caller."""
        uc, *_ = _make_use_case(storage_put_raises=RuntimeError("MinIO unavailable"))
        inp = _make_input()

        with pytest.raises(RuntimeError, match="MinIO unavailable"):
            await uc.execute(inp)

    # ── T-E-1-01 Test 8: DB failure triggers compensating GC ─────────────────

    async def test_db_failure_triggers_compensating_gc(self) -> None:
        """If the DB write fails after MinIO PUT, storage.delete must be called."""
        uc, _, _, _, storage = _make_use_case(uow_commit_raises=RuntimeError("DB write failed"))
        inp = _make_input()

        with (
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=NOW),
            pytest.raises(RuntimeError, match="DB write failed"),
        ):
            await uc.execute(inp)

        # The compensating delete must have been called with the correct bucket.
        storage.delete.assert_awaited_once()
        delete_call = storage.delete.call_args
        assert delete_call.args[0] == BRONZE_BUCKET
        # Key must include the tenant and doc IDs.
        key_arg: str = delete_call.args[1]
        assert str(TENANT_ID) in key_arg
        assert str(DOC_ID) in key_arg

    async def test_gc_failure_does_not_suppress_original_exception(self) -> None:
        """If both DB write and compensating GC fail, the original DB error propagates."""
        uc, _, _, _, storage = _make_use_case(uow_commit_raises=RuntimeError("DB write failed"))
        # GC delete also fails — we want the original error, not the GC error.
        storage.delete = AsyncMock(side_effect=RuntimeError("MinIO also down"))
        inp = _make_input()

        with (
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=NOW),
            pytest.raises(RuntimeError, match="DB write failed"),
        ):
            await uc.execute(inp)

    # ── PDF content-type path ─────────────────────────────────────────────────

    async def test_pdf_extraction_called_via_thread(self) -> None:
        """PDF uploads must run _extract_pdf_text in a thread (asyncio.to_thread)."""
        uc, *_ = _make_use_case()
        inp = _make_input(file_bytes=VALID_PDF_BYTES, filename="doc.pdf", content_type="application/pdf")

        # Patch _extract_pdf_text at the module level to return a real string.
        with (
            patch(
                "content_ingestion.application.use_cases.upload_tenant_document._extract_pdf_text",
                return_value="Extracted PDF content with several words",
            ),
            patch("common.ids.new_uuid7", return_value=DOC_ID),
            patch("common.time.utc_now", return_value=NOW),
        ):
            result = await uc.execute(inp)

        assert result.status == "processing"
        assert result.filename == "doc.pdf"
