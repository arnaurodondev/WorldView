"""Tests for SSRF DNS resolution (CR-2 fix).

Verifies that the URL validator resolves DNS hostnames and checks
ALL resolved IP addresses against private ranges, preventing DNS
rebinding attacks.
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from content_ingestion.api.schemas import IngestSubmitRequest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def _fake_getaddrinfo_private(host: str, port: object) -> list[tuple]:
    """Simulate DNS resolving to a private IP (link-local)."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0)),
    ]


def _fake_getaddrinfo_localhost(host: str, port: object) -> list[tuple]:
    """Simulate DNS resolving to localhost."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
    ]


def _fake_getaddrinfo_public(host: str, port: object) -> list[tuple]:
    """Simulate DNS resolving to a public IP."""
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
    ]


def _fake_getaddrinfo_fail(host: str, port: object) -> list[tuple]:
    """Simulate DNS resolution failure."""
    raise socket.gaierror("Name or service not known")


class TestSSRFDNSResolution:
    def test_rejects_nip_io_private(self) -> None:
        """Hostname resolving to link-local IP must be rejected."""
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_private):
            with pytest.raises(ValidationError, match="private"):
                IngestSubmitRequest(source_type="eodhd", url="http://169.254.169.254.nip.io/latest/meta-data")

    def test_rejects_localhost_hostname(self) -> None:
        """Hostname resolving to 127.0.0.1 must be rejected."""
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_localhost):
            with pytest.raises(ValidationError, match="private"):
                IngestSubmitRequest(source_type="eodhd", url="http://localhost/secret")

    def test_allows_public_hostname(self) -> None:
        """Hostname resolving to a public IP must be allowed."""
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_public):
            req = IngestSubmitRequest(source_type="eodhd", url="http://example.com/article")
            assert req.url == "http://example.com/article"

    def test_rejects_unresolvable_hostname(self) -> None:
        """Non-existent hostname must raise validation error."""
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_fail):
            with pytest.raises(ValidationError, match="resolve"):
                IngestSubmitRequest(source_type="eodhd", url="http://nonexistent.invalid/path")
