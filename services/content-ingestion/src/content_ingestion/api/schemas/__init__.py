"""Pydantic request/response models for the S4 API.

All schemas live here (flat — no sub-modules required).
The ``schemas/`` package replaced the old ``schemas.py`` module in Wave E-2;
existing imports (``from content_ingestion.api.schemas import X``) continue
to work unchanged since the package ``__init__.py`` exposes all names.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# ── SSRF Prevention ──────────────────────────────────────────────────────────


def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP is private, reserved, loopback, multicast, or link-local.

    Handles IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1) by extracting
    the IPv4 part before checking. Uses Python builtins for future-proof coverage
    including CGNAT (100.64.0.0/10), multicast (224.0.0.0/4), reserved (240.0.0.0/4).
    """
    # Handle IPv4-mapped IPv6 (e.g., ::ffff:127.0.0.1) — extract the IPv4 part
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return bool(
        addr.is_private
        or addr.is_reserved
        or addr.is_loopback
        or addr.is_multicast
        or addr.is_link_local
        # CGNAT shared space — not classified by Python 3.12 builtins
        or (isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT_NETWORK),
    )


# CGNAT shared address space — Python 3.12 doesn't classify it in any builtin
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _check_literal_ip_not_private(hostname: str) -> None:
    """Check literal IP hostname against private ranges (sync, fast).

    Only checks if hostname is a literal IP address. DNS hostnames are
    checked asynchronously in `check_url_ssrf_async` (BP-022).
    """
    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private_ip(addr):
            msg = "URL must not target private IP ranges"
            raise ValueError(msg)
    except ValueError as exc:
        if "private IP" in str(exc):
            raise
        # Not a literal IP — DNS check will be done async in route handler


async def check_url_ssrf_async(url: str) -> None:
    """Async SSRF check — resolves DNS hostnames in thread pool with timeout.

    Call from async route handlers BEFORE making HTTP requests.
    Covers DNS rebinding by resolving and checking ALL addresses (BP-022, BP-023).
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        return
    # Literal IP — fast sync check
    try:
        addr = ipaddress.ip_address(hostname)
        if _is_private_ip(addr):
            msg = "URL must not target private IP ranges"
            raise ValueError(msg)
        return
    except ValueError as exc:
        if "private IP" in str(exc):
            raise
        # Not a literal IP — resolve via DNS below

    # DNS resolution in thread pool with timeout (BP-022)
    try:
        addr_infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, hostname, None),
            timeout=5.0,
        )
    except TimeoutError:
        msg = f"DNS resolution timed out for hostname: {hostname}"
        raise ValueError(msg)  # noqa: B904
    except socket.gaierror:
        msg = f"Could not resolve hostname: {hostname}"
        raise ValueError(msg)  # noqa: B904

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        addr = ipaddress.ip_address(ip_str)
        if _is_private_ip(addr):
            msg = "URL must not target private IP ranges"
            raise ValueError(msg)


class SourceResponse(BaseModel):
    id: UUID
    name: str
    source_type: str
    enabled: bool
    last_fetch_at: datetime | None = None


class SourceListResponse(BaseModel):
    sources: list[SourceResponse]


class SourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_type: str = Field(..., min_length=1, max_length=50)
    config: dict[str, str | int | bool | list[str | int | bool]] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: str) -> str:
        from content_ingestion.domain.entities import SourceType

        allowed = {st.value for st in SourceType}
        if v not in allowed:
            msg = f"Invalid source_type '{v}'. Allowed: {', '.join(sorted(allowed))}"
            raise ValueError(msg)
        return v


class SourceUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    enabled: bool | None = None
    config: dict[str, str | int | bool | list[str | int | bool]] | None = None


class TriggerResponse(BaseModel):
    status: str = "queued"
    source_id: UUID
    task_id: UUID | None = None


# ── Status ───────────────────────────────────────────────────────────────────


class SourceStatusDetail(BaseModel):
    name: str
    last_fetch_at: datetime | None = None
    articles_fetched_24h: int = 0
    errors_24h: int = 0


class StatusResponse(BaseModel):
    sources: list[SourceStatusDetail]
    outbox_pending: int = 0
    dlq_count: int = 0


# ── Internal ingest submit ───────────────────────────────────────────────────


class IngestSubmitRequest(BaseModel):
    url: str | None = Field(None, max_length=4096)
    raw_content: str | None = Field(None, max_length=5_242_880)
    source_type: str = Field(..., min_length=1, max_length=50)
    title: str | None = Field(None, max_length=500)
    published_at: datetime | None = None

    @field_validator("url")
    @classmethod
    def validate_url_scheme_and_host(cls, v: str | None) -> str | None:
        """Enforce http(s) scheme and reject private IP ranges (SSRF prevention).

        Resolves DNS hostnames and checks ALL resolved addresses against
        private IP ranges to prevent DNS rebinding attacks (CR-2).
        """
        if v is None:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            msg = "URL must use http or https scheme"
            raise ValueError(msg)
        hostname = parsed.hostname
        if hostname is None:
            return v

        _check_literal_ip_not_private(hostname)
        return v


class IngestSubmitResponse(BaseModel):
    doc_id: UUID
    status: str = "accepted"


# ── DLQ ──────────────────────────────────────────────────────────────────────


class DLQEntryResponse(BaseModel):
    dlq_id: UUID
    original_event_id: UUID
    topic: str
    error_detail: str | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class DLQListResponse(BaseModel):
    entries: list[DLQEntryResponse]
    count: int


class DLQResolveRequest(BaseModel):
    note: str = Field(..., min_length=1, max_length=2000)


# ── Error ────────────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ── Tenant Document Upload (PLAN-0086 Wave E-2) ───────────────────────────────


class UploadResponse(BaseModel):
    """Response body for a successful POST /api/v1/documents/upload (202 Accepted).

    The document is queued for async processing; ``status`` will be
    ``"processing"`` until the pipeline stages complete.
    """

    doc_id: UUID
    status: str
    title: str
    filename: str


class DocumentStatusResponse(BaseModel):
    """Full status for a single tenant document (GET /api/v1/documents/{doc_id}).

    Pipeline-output fields (``word_count``, ``chunk_count``, ``ready_at``) are
    None until the corresponding pipeline stage populates them.
    """

    doc_id: UUID
    title: str
    filename: str
    status: str
    word_count: int | None = None
    chunk_count: int | None = None
    uploaded_at: datetime
    ready_at: datetime | None = None
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    """Paginated list of tenant documents (GET /api/v1/documents).

    ``next_cursor`` is None on the last page — pass it as the ``cursor``
    query param on subsequent requests to advance the page.
    """

    items: list[DocumentStatusResponse]
    next_cursor: str | None = None
    total: int


class DeleteResponse(BaseModel):
    """Response body for a successful DELETE /api/v1/documents/{doc_id} (200 OK).

    Returns 200 (not 204) so the response body is always present — BP-064.
    """

    doc_id: UUID
    status: str
