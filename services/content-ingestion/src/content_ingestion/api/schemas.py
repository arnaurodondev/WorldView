"""Pydantic request/response models for the S4 API."""

from __future__ import annotations

import ipaddress
import socket
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
    ipaddress.ip_network("0.0.0.0/8"),
)

# IPv6 loopback
_PRIVATE_NETWORKS_V6 = (
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is in a private/reserved range."""
    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in net for net in _PRIVATE_NETWORKS)
    return any(addr in net for net in _PRIVATE_NETWORKS_V6)


def _check_ip_not_private(hostname: str) -> None:
    """Resolve hostname and check ALL IPs against private ranges.

    Handles both literal IPs and DNS hostnames. Raises ValueError
    if any resolved address is private (SSRF prevention via DNS rebinding).
    """
    # Try as literal IP first
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

    # DNS resolution — check ALL addresses
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
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

        _check_ip_not_private(hostname)
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
