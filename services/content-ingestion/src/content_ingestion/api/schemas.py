"""Pydantic request/response models for the S4 API."""

from __future__ import annotations

import ipaddress
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# ── Source CRUD ──────────────────────────────────────────────────────────────

# Private IP networks for SSRF prevention
_PRIVATE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
)


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
    config: dict[str, str | int | bool] = Field(default_factory=dict)
    enabled: bool = True


class SourceUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    enabled: bool | None = None
    config: dict[str, str | int | bool] | None = None


class TriggerResponse(BaseModel):
    status: str = "triggered"
    source_id: UUID


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
        """Enforce http(s) scheme and reject private IP ranges (SSRF prevention)."""
        if v is None:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            msg = "URL must use http or https scheme"
            raise ValueError(msg)
        hostname = parsed.hostname
        if hostname is not None:
            try:
                addr = ipaddress.ip_address(hostname)
                if any(addr in net for net in _PRIVATE_NETWORKS):
                    msg = "URL must not target private IP ranges"
                    raise ValueError(msg)
            except ValueError as exc:
                # Not an IP address (it's a hostname) — that's fine, unless it was our own raise
                if "private IP" in str(exc) or "http or https" in str(exc):
                    raise
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
