"""UploadTenantDocumentUseCase — accept a raw document upload from a tenant user.

PLAN-0086 Wave E-1: Multi-Tenant Content Pipeline Isolation.

Step order is MANDATORY for R24 compliance — no DB session may be open during
MinIO I/O or text extraction, as those are long-running blocking operations that
would hold a connection pool slot for seconds or minutes.

Processing pipeline:
  1. Validate MIME type (no I/O)
  2. Validate file size (no I/O)
  3. Check rate limit (Valkey only — no DB)
  4. Extract text   (CPU / subprocess — no DB, no MinIO)
  5. Compute content hash and word count (no I/O)
  6. Dedup check    (DB read, then session closed)
  7. Generate IDs and MinIO key (no I/O)
  8. PUT MinIO bronze  (object store only — no DB)
  9. DB write + outbox (DB only — MinIO already written)

Step 9 has compensating cleanup: if the DB write fails, the MinIO object is
deleted to avoid orphaned objects in the bronze tier.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from content_ingestion.domain.exceptions import (
    DuplicateDocumentError,
    FileTooLargeError,
    TextExtractionError,
    UnsupportedFileTypeError,
    UploadRateLimitError,
)
from content_ingestion.domain.tenant_upload import TenantDocumentUpload, UploadStatus

if TYPE_CHECKING:
    from content_ingestion.application.ports.repositories import OutboxPort
    from content_ingestion.application.ports.tenant_upload import (
        TenantDedupHashRepositoryPort,
        TenantDocumentUploadRepositoryPort,
        UploadRateLimitPort,
    )
    from content_ingestion.application.ports.unit_of_work import UnitOfWork

log = structlog.get_logger()  # type: ignore[no-any-return]

# ── Constants ─────────────────────────────────────────────────────────────────

ALLOWED_CONTENT_TYPES = {"application/pdf", "text/plain"}
# 50 MB — any larger file is rejected before extraction to avoid OOM risk.
MAX_FILE_BYTES = 50_000_000
# Hard cap on extracted text to prevent downstream embedding OOM.
MAX_TEXT_CHARS = 500_000
# Bronze bucket — must match the MinIO bootstrap in docker-compose.
BRONZE_BUCKET = "worldview-bronze"


# ── I/O-free helper ──────────────────────────────────────────────────────────


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Synchronous PDF text extraction — always called via asyncio.to_thread.

    Kept synchronous because pdfminer.six is a synchronous library and uses
    internal file seeks that are incompatible with asyncio streams.  The
    to_thread wrapper prevents blocking the event loop.

    Raises:
        TextExtractionError: If pdfminer raises any exception during extraction.
    """
    import io

    try:
        from pdfminer.high_level import (
            extract_text as pdfminer_extract,  # type: ignore[import-untyped,import-not-found]
        )

        return pdfminer_extract(io.BytesIO(file_bytes))  # type: ignore[no-any-return]
    except Exception as exc:
        raise TextExtractionError(f"PDF extraction failed: {exc}") from exc


# ── DTOs ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UploadTenantDocumentInput:
    """All inputs required for a single tenant document upload.

    ``title`` is optional — when None the filename stem is used as the display
    title (e.g. ``"Q4 Report"`` for ``"Q4 Report.pdf"``).
    """

    file_bytes: bytes
    filename: str
    content_type: str
    tenant_id: UUID
    user_id: UUID
    # None → derive from filename stem at execution time.
    title: str | None


@dataclass(frozen=True)
class UploadTenantDocumentResult:
    """Response DTO returned to the API layer after a successful upload."""

    doc_id: UUID
    status: str
    title: str
    filename: str


# ── Use case ──────────────────────────────────────────────────────────────────


class UploadTenantDocumentUseCase:
    """Accept a tenant document upload and initiate the processing pipeline.

    Dependencies are injected — never imported from infrastructure directly.
    The ``uow`` is used as an async context manager; each time a DB session is
    needed a fresh ``async with self._uow:`` block is opened and closed, so no
    single session spans a MinIO PUT or CPU-bound PDF extraction (R24).

    Args:
        upload_repo:       Repository for TenantDocumentUpload persistence.
        dedup_repo:        Repository for per-tenant content-hash deduplication.
        rate_limit:        Valkey-backed rate limiter port.
        storage:           Object storage port (MinIO bronze tier).
                           Must support ``put_bytes(bucket, key, data, content_type)``
                           and ``delete(bucket, key)``.
        uow:               Unit of Work — used as an async context manager.
                           Opened twice: once for dedup read, once for DB write.
        upload_rate_limit: Maximum uploads allowed per window per tenant.
        upload_window_seconds: Sliding window size in seconds (default: 1 day).
    """

    def __init__(
        self,
        upload_repo: TenantDocumentUploadRepositoryPort,
        dedup_repo: TenantDedupHashRepositoryPort,
        outbox: OutboxPort,
        rate_limit: UploadRateLimitPort,
        storage: object,  # ObjectStorage from libs/storage — duck-typed to avoid hard dep
        uow: UnitOfWork,
        upload_rate_limit: int = 100,
        upload_window_seconds: int = 86400,
    ) -> None:
        self._upload_repo = upload_repo
        self._dedup_repo = dedup_repo
        self._outbox = outbox
        self._rate_limit = rate_limit
        self._storage = storage
        self._uow = uow
        self._rate_limit_max = upload_rate_limit
        self._rate_limit_window = upload_window_seconds

    async def execute(self, inp: UploadTenantDocumentInput) -> UploadTenantDocumentResult:
        """Run the full upload pipeline.  See module docstring for step ordering."""
        # ── Step 1: Validate MIME type ────────────────────────────────────────
        if inp.content_type not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedFileTypeError(
                f"Unsupported content type '{inp.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
            )

        # ── Step 2: Validate file size ────────────────────────────────────────
        if len(inp.file_bytes) > MAX_FILE_BYTES:
            raise FileTooLargeError(len(inp.file_bytes), MAX_FILE_BYTES)

        # ── Step 3: Rate-limit check (Valkey — no DB session open) ────────────
        allowed = await self._rate_limit.check_and_increment(
            inp.tenant_id, self._rate_limit_window, self._rate_limit_max
        )
        if not allowed:
            reset_at = await self._rate_limit.get_reset_at(inp.tenant_id)
            from common.time import utc_now  # type: ignore[import-untyped]

            raise UploadRateLimitError(reset_at or utc_now())

        # ── Step 4: Extract text (CPU — no DB, no MinIO) ──────────────────────
        if inp.content_type == "application/pdf":
            # Run in a thread pool so the event loop is not blocked during I/O.
            extracted: str = await asyncio.to_thread(_extract_pdf_text, inp.file_bytes)
        else:
            # Plain text — decode with error replacement; never raises.
            extracted = inp.file_bytes.decode("utf-8", errors="replace").strip()

        if not extracted or not extracted.strip():
            raise TextExtractionError("Extraction yielded empty or whitespace-only content")

        # Truncate before hashing to match what downstream embedders will see.
        if len(extracted) > MAX_TEXT_CHARS:
            extracted = extracted[:MAX_TEXT_CHARS]

        # ── Step 5: Hash + word count (no I/O) ───────────────────────────────
        content_hash = hashlib.sha256(extracted.encode()).hexdigest()
        word_count = len(extracted.split())
        # Derive display title from filename stem if caller did not provide one.
        title = inp.title or inp.filename.rsplit(".", 1)[0]

        # ── Step 6: Dedup check (short-lived DB read, session closed after) ───
        async with self._uow:
            existing_id = await self._dedup_repo.check_exists("sha256", content_hash, inp.tenant_id)
            if existing_id is not None:
                raise DuplicateDocumentError(existing_id)
            # Session is closed here — no session spans the MinIO PUT below.

        # ── Step 7: Generate IDs and keys (no I/O) ───────────────────────────
        from common.ids import new_uuid7  # type: ignore[import-untyped]
        from common.time import utc_now  # type: ignore[import-untyped]

        doc_id = new_uuid7()
        minio_bronze_key = f"tenant-uploads/{inp.tenant_id}/{doc_id}/bronze/{inp.filename}"

        # ── Step 8: PUT MinIO bronze (no DB session) ──────────────────────────
        # Track whether the object was written so Step 9 can compensate on failure.
        pending_bronze_key: str | None = None
        try:
            await self._storage.put_bytes(  # type: ignore[attr-defined]
                BRONZE_BUCKET, minio_bronze_key, inp.file_bytes, inp.content_type
            )
            pending_bronze_key = minio_bronze_key
        except Exception as exc:
            log.error(
                "upload_minio_put_failed",
                tenant_id=str(inp.tenant_id),
                filename=inp.filename,
                error=str(exc),
            )
            raise

        # ── Step 9: DB write + outbox (session open only for DB work) ─────────
        try:
            async with self._uow:
                doc = TenantDocumentUpload(
                    id=doc_id,
                    tenant_id=inp.tenant_id,
                    uploaded_by_user_id=inp.user_id,
                    filename=inp.filename,
                    title=title,
                    content_type=inp.content_type,
                    content_hash=content_hash,
                    byte_size=len(inp.file_bytes),
                    minio_bronze_key=minio_bronze_key,
                    status=UploadStatus.PROCESSING,
                    uploaded_at=utc_now(),
                    word_count=word_count,
                )
                await self._upload_repo.create(doc)
                # Record the dedup hash so future uploads of the same content are rejected.
                await self._dedup_repo.insert(doc_id, "sha256", content_hash, inp.tenant_id)
                # Publish content.article.raw.v1 so S5 content-store picks up the document
                # and S6 NLP pipeline processes it.  The event_id is deterministic so the
                # outbox ON CONFLICT (event_id) DO NOTHING guard deduplicates retries.
                from common.ids import uuid5_from_parts  # type: ignore[import-untyped]
                from common.time import utc_now as _utc_now  # type: ignore[import-untyped]

                await self._outbox.append(
                    aggregate_type="content_document",
                    aggregate_id=doc_id,
                    event_type="content.article.raw.v1",
                    topic="content.article.raw.v1",
                    payload={
                        "event_id": uuid5_from_parts(str(doc_id), "content_article_raw_v1"),
                        "event_type": "content.article.raw",
                        "schema_version": 1,
                        "occurred_at": _utc_now().isoformat(),
                        "doc_id": str(doc_id),
                        "source_type": "tenant_upload",
                        "source_url": None,
                        "minio_bronze_key": minio_bronze_key,
                        "content_hash": content_hash,
                        "fetch_id": str(doc_id),  # no fetch for uploads; use doc_id
                        "title": title,
                        "published_at": None,
                        "is_backfill": False,
                        "correlation_id": None,
                        "tenant_id": str(inp.tenant_id),
                    },
                )
                await self._uow.commit()
        except Exception:
            # Compensating GC: the MinIO object is now orphaned — delete it.
            # This is best-effort; a reconciliation job handles any missed ones.
            if pending_bronze_key is not None:
                try:
                    await self._storage.delete(BRONZE_BUCKET, pending_bronze_key)  # type: ignore[attr-defined]
                    log.info("compensating_gc_complete", key=pending_bronze_key)
                except Exception as gc_exc:
                    log.warning(
                        "compensating_gc_failed",
                        key=pending_bronze_key,
                        error=str(gc_exc),
                    )
            raise

        log.info(
            "tenant_document_uploaded",
            doc_id=str(doc_id),
            tenant_id=str(inp.tenant_id),
            filename=inp.filename,
            word_count=word_count,
        )
        return UploadTenantDocumentResult(
            doc_id=doc_id,
            status="processing",
            title=title,
            filename=inp.filename,
        )
