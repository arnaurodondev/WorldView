"""Tenant document upload/management API endpoints.

PLAN-0086 Wave E-2: Multi-Tenant Content Pipeline Isolation.

These routes let authenticated tenant users upload, list, inspect, and delete
their own documents.  ``X-Tenant-ID`` and ``X-User-ID`` are optional forwarded
headers from S9.  The primary source of truth is ``request.state.tenant_id``
and ``request.state.user_id`` set by ``InternalJWTMiddleware`` from the JWT
payload.  If explicit headers are present they are validated and used;
otherwise the state values are used.  This avoids requiring S9 to inject
extra headers while keeping the route signatures self-documenting.

Endpoints:
  POST   /api/v1/documents/upload         — 202 Accepted, multipart file upload
  GET    /api/v1/documents/{doc_id}       — 200 single document status
  GET    /api/v1/documents               — 200 paginated list
  DELETE /api/v1/documents/{doc_id}       — 200 soft-delete (BP-064: never 204)

Error mapping (caught at route level):
  UnsupportedFileTypeError   → 400
  FileTooLargeError          → 413
  TextExtractionError        → 422
  DuplicateDocumentError     → 409  {"existing_doc_id": "..."}
  UploadRateLimitError       → 429  {"resets_at": "..."}
  NotFoundError              → 404
  AlreadyDeletedError        → 409
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse

from content_ingestion.api.schemas import (
    DeleteResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    UploadResponse,
)
from content_ingestion.domain.exceptions import (
    AlreadyDeletedError,
    DuplicateDocumentError,
    FileTooLargeError,
    NotFoundError,
    TextExtractionError,
    UnsupportedFileTypeError,
    UploadRateLimitError,
)
from content_ingestion.domain.tenant_upload import UploadStatus

router = APIRouter(prefix="/api/v1", tags=["documents"])


# ── Header-based identity extractors ──────────────────────────────────────────
# S9 can forward X-Tenant-ID and X-User-ID explicitly (useful for testing and
# for services that don't run InternalJWTMiddleware).  When the headers are
# absent, the values are read from request.state which InternalJWTMiddleware
# populates from the JWT payload.  A 401 is returned if neither source works.


def tenant_id_dep(
    request: Request,
    x_tenant_id: str | None = Header(None),
) -> UUID:
    """Resolve tenant_id from InternalJWT state or X-Tenant-ID header.

    Precedence:
    1. request.state.tenant_id (set by InternalJWTMiddleware — verified JWT)
    2. X-Tenant-ID header (fallback for internal service-to-service calls only)

    JWT-derived state always takes precedence so that a caller who bypasses S9
    cannot spoof their tenant via the header.

    Raises 400 on malformed UUID.  Raises 401 if no tenant identity is found.
    """
    raw: str | None = getattr(request.state, "tenant_id", None) or x_tenant_id or None
    if not raw:
        raise HTTPException(status_code=401, detail="Tenant identity missing (X-Tenant-ID or JWT)")
    try:
        return UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant_id — not a valid UUID")  # noqa: B904


def user_id_dep(
    request: Request,
    x_user_id: str | None = Header(None),
) -> UUID:
    """Resolve user_id from InternalJWT state or X-User-ID header.

    Precedence:
    1. request.state.user_id (set by InternalJWTMiddleware — verified JWT)
    2. X-User-ID header (fallback for internal service-to-service calls only)

    Raises 400 on malformed UUID.  Raises 401 if no user identity is found.
    """
    raw: str | None = getattr(request.state, "user_id", None) or x_user_id or None
    if not raw:
        raise HTTPException(status_code=401, detail="User identity missing (X-User-ID or JWT)")
    try:
        return UUID(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id — not a valid UUID")  # noqa: B904


TenantIdDep = Annotated[UUID, Depends(tenant_id_dep)]
UserIdDep = Annotated[UUID, Depends(user_id_dep)]


# ── Inline UoW shim ───────────────────────────────────────────────────────────
# The upload and delete use cases need upload_repo + dedup_repo to share the
# same SQLAlchemy session as the UoW commit/rollback.  Rather than using the
# generic UoWDep (which opens its own session), we open a session directly from
# write_factory and wrap it in this minimal shim that satisfies the UnitOfWork
# protocol without opening a second session.


class _InlineUoW:
    """Minimal UoW shim wrapping an already-open SQLAlchemy session.

    The UploadTenantDocumentUseCase opens the UoW twice (dedup read + DB write)
    via ``async with self._uow``.  Each ``async with`` on this shim is a no-op;
    ``commit()`` / ``rollback()`` delegate to the live session so all operations
    are atomic.

    This shim is not a full UnitOfWork implementation — it exists only to
    satisfy the constructor contract of use cases that accept a ``UnitOfWork``
    parameter while operating inside a manually-managed session.
    """

    def __init__(self, session: object) -> None:
        # session is AsyncSession; duck-typed to avoid importing SQLAlchemy here
        self._session = session

    async def __aenter__(self) -> _InlineUoW:
        # No-op — session is already open, managed by the outer `async with`
        return self

    async def __aexit__(self, *_: object) -> None:
        pass  # session lifecycle managed by the outer context

    async def commit(self) -> None:
        await self._session.commit()  # type: ignore[attr-defined]

    async def rollback(self) -> None:
        await self._session.rollback()  # type: ignore[attr-defined]


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post(
    "/documents/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a tenant document for async processing",
)
async def upload_document(
    request: Request,
    file: UploadFile,
    tenant_id: TenantIdDep,
    user_id: UserIdDep,
) -> UploadResponse | JSONResponse:
    """Accept a raw document upload and queue it for the processing pipeline.

    Supports ``application/pdf`` and ``text/plain``.  Files over 50 MB are
    rejected before extraction to protect the event loop from OOM conditions.

    The 202 response means the document was accepted; poll
    ``GET /api/v1/documents/{doc_id}`` to track pipeline progress.

    Error responses:
    - 400  Unsupported MIME type (not PDF or plain text)
    - 413  File exceeds 50 MB size limit
    - 422  Text extraction yielded no usable content (e.g. image-only PDF)
    - 409  Duplicate document (same content already uploaded by this tenant)
    - 429  Upload rate limit exceeded for this tenant
    """
    # Read the file bytes before opening any DB session — avoids holding a
    # connection-pool slot during the file read I/O.
    file_bytes = await file.read()
    # Fallback to octet-stream if the client omitted Content-Type.
    content_type = file.content_type or "application/octet-stream"

    # Deferred imports: infrastructure imports live inside route functions per
    # R12 (domain-layer independence) and to avoid circular import chains.
    from content_ingestion.application.use_cases.upload_tenant_document import (
        UploadTenantDocumentInput,
        UploadTenantDocumentUseCase,
    )
    from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
    from content_ingestion.infrastructure.db.repositories.tenant_upload import (
        TenantDedupHashRepository,
        TenantDocumentUploadRepository,
    )
    from content_ingestion.infrastructure.valkey.upload_rate_limit import UploadRateLimitAdapter

    settings = request.app.state.settings

    # Open a single write session so upload_repo, dedup_repo, and the outbox
    # all share one transaction.  We use _InlineUoW to satisfy the use case's
    # UnitOfWork dependency without opening a second connection.
    async with request.app.state.write_factory() as session:
        upload_repo = TenantDocumentUploadRepository(session)
        dedup_repo = TenantDedupHashRepository(session)
        outbox = OutboxRepository(session)
        rate_limit = UploadRateLimitAdapter(request.app.state.valkey)
        storage = request.app.state.storage
        inline_uow = _InlineUoW(session)

        uc = UploadTenantDocumentUseCase(
            upload_repo=upload_repo,
            dedup_repo=dedup_repo,
            outbox=outbox,  # type: ignore[arg-type]
            rate_limit=rate_limit,
            storage=storage,
            uow=inline_uow,  # type: ignore[arg-type]
            upload_rate_limit=getattr(settings, "upload_rate_limit", 100),
            upload_window_seconds=getattr(settings, "upload_window_seconds", 86400),
        )

        inp = UploadTenantDocumentInput(
            file_bytes=file_bytes,
            filename=file.filename or "upload",
            content_type=content_type,
            tenant_id=tenant_id,
            user_id=user_id,
            title=None,  # derive from filename stem inside the use case
        )

        try:
            result = await uc.execute(inp)
        except UnsupportedFileTypeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except TextExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except DuplicateDocumentError as exc:
            # Return JSONResponse directly — cannot raise HTTPException with a
            # non-string body that contains the existing_doc_id field.
            return JSONResponse(
                status_code=409,
                content={"existing_doc_id": str(exc.existing_doc_id)},
            )
        except UploadRateLimitError as exc:
            return JSONResponse(
                status_code=429,
                content={"resets_at": exc.resets_at.isoformat()},
            )

    return UploadResponse(
        doc_id=result.doc_id,
        status=result.status,
        title=result.title,
        filename=result.filename,
    )


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a single tenant document by ID",
)
async def get_document(
    request: Request,
    doc_id: UUID,
    tenant_id: TenantIdDep,
) -> DocumentStatusResponse:
    """Fetch the processing status and metadata for a single document.

    Returns 404 if the document does not exist OR if it belongs to a different
    tenant — the error is intentionally ambiguous to prevent cross-tenant
    information leakage.
    """
    from content_ingestion.application.use_cases.get_tenant_document import GetTenantDocumentUseCase
    from content_ingestion.infrastructure.db.repositories.tenant_upload import TenantDocumentUploadRepository

    # Read-only use case: use the read replica factory (R27).
    async with request.app.state.read_factory() as session:
        repo = TenantDocumentUploadRepository(session)
        # GetTenantDocumentUseCase also takes a ReadOnlyUnitOfWork; we pass an
        # inline shim — the use case opens it once for the repo.get() call.
        uc = GetTenantDocumentUseCase(repo=repo, uow=_InlineUoW(session))  # type: ignore[arg-type]
        doc = await uc.execute(doc_id=doc_id, tenant_id=tenant_id)

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentStatusResponse(
        doc_id=doc.id,
        title=doc.title,
        filename=doc.filename,
        status=doc.status.value,
        word_count=doc.word_count,
        chunk_count=doc.chunk_count,
        uploaded_at=doc.uploaded_at,
        ready_at=doc.ready_at,
        error_message=doc.error_message,
    )


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    status_code=status.HTTP_200_OK,
    summary="List tenant documents with optional status filter and cursor pagination",
)
async def list_documents(
    request: Request,
    tenant_id: TenantIdDep,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
) -> DocumentListResponse:
    """Return a keyset-paginated list of tenant documents.

    Pass the ``next_cursor`` from one response as the ``cursor`` query param
    on the next request to fetch the next page.  The ``total`` field reflects
    the total matching row count across all pages.

    Query params:
    - ``status``: Filter to a specific upload status (processing, ready, failed, deleted).
    - ``limit``:  Page size (1-100; default 20).
    - ``cursor``: Opaque cursor from the previous page's ``next_cursor`` field.
    """
    from content_ingestion.application.use_cases.list_tenant_documents import ListTenantDocumentsUseCase
    from content_ingestion.infrastructure.db.repositories.tenant_upload import TenantDocumentUploadRepository

    # Validate optional status filter before touching the DB.
    parsed_status: UploadStatus | None = None
    if status_filter is not None:
        try:
            parsed_status = UploadStatus(status_filter)
        except ValueError:
            raise HTTPException(  # noqa: B904
                status_code=400,
                detail=f"Invalid status '{status_filter}'. Allowed: {[s.value for s in UploadStatus]}",
            )

    # Validate cursor format eagerly — a malformed cursor is a caller error
    # that should return 400 before any DB I/O.
    if cursor is not None:
        try:
            import base64 as _b64

            raw = _b64.urlsafe_b64decode(cursor.encode()).decode()
            if "|" not in raw:
                raise ValueError("missing separator")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor")  # noqa: B904

    async with request.app.state.read_factory() as session:
        repo = TenantDocumentUploadRepository(session)
        uc = ListTenantDocumentsUseCase(repo=repo, uow=_InlineUoW(session))  # type: ignore[arg-type]
        list_result = await uc.execute(
            tenant_id=tenant_id,
            status=parsed_status,
            limit=limit,
            cursor=cursor,
        )

    return DocumentListResponse(
        items=[
            DocumentStatusResponse(
                doc_id=doc.id,
                title=doc.title,
                filename=doc.filename,
                status=doc.status.value,
                word_count=doc.word_count,
                chunk_count=doc.chunk_count,
                uploaded_at=doc.uploaded_at,
                ready_at=doc.ready_at,
                error_message=doc.error_message,
            )
            for doc in list_result.items
        ],
        next_cursor=list_result.next_cursor,
        total=list_result.total,
    )


@router.delete(
    "/documents/{doc_id}",
    response_model=DeleteResponse,
    status_code=status.HTTP_200_OK,  # BP-064: always 200 with body, never 204
    summary="Soft-delete a tenant document",
)
async def delete_document(
    request: Request,
    doc_id: UUID,
    tenant_id: TenantIdDep,
) -> DeleteResponse:
    """Soft-delete a tenant document and emit a deletion event via the outbox.

    The document row is retained in the DB with status=deleted; physical MinIO
    deletion is handled asynchronously by a GC worker.  The deletion event is
    emitted to ``content.document.deleted.v1`` via the transactional outbox so
    downstream services (S6 NLP) can remove related data.

    Returns 200 (not 204) so the response body is always present (BP-064).

    Error responses:
    - 404  Document not found or belongs to a different tenant
    - 409  Document is already in DELETED state
    """
    from content_ingestion.application.use_cases.delete_tenant_document import DeleteTenantDocumentUseCase
    from content_ingestion.infrastructure.db.repositories.outbox import OutboxRepository
    from content_ingestion.infrastructure.db.repositories.tenant_upload import TenantDocumentUploadRepository

    # Single write session so the status update and the outbox event are
    # committed atomically (R5 — outbox pattern, never dual-write).
    async with request.app.state.write_factory() as session:
        upload_repo = TenantDocumentUploadRepository(session)
        # OutboxRepository shares the same session as the upload_repo so the
        # status update and the outbox append are in one transaction.
        outbox = OutboxRepository(session)
        inline_uow = _InlineUoW(session)

        uc = DeleteTenantDocumentUseCase(
            upload_repo=upload_repo,
            outbox=outbox,  # type: ignore[arg-type]
            uow=inline_uow,  # type: ignore[arg-type]
        )

        try:
            await uc.execute(doc_id=doc_id, tenant_id=tenant_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AlreadyDeletedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return DeleteResponse(doc_id=doc_id, status="deleted")
