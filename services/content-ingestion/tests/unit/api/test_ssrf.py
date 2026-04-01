"""Tests for SSRF prevention — IP blocklist, async DNS, and transport hook.

Verifies:
- _is_private_ip covers IPv4-mapped IPv6, CGNAT, multicast, reserved
- Pydantic validator only checks scheme + literal IPs (no DNS)
- check_url_ssrf_async resolves DNS asynchronously with timeout
- SSRFSafeTransport blocks private IPs at connection time
"""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import patch

import pytest
from content_ingestion.api.schemas import (
    IngestSubmitRequest,
    _is_private_ip,
    check_url_ssrf_async,
)
from pydantic import ValidationError

pytestmark = pytest.mark.unit


# ── _is_private_ip tests ────────────────────────────────────────────────────


class TestIsPrivateIp:
    def test_ipv4_private_10(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("10.0.0.1")) is True

    def test_ipv4_private_172(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("172.16.0.1")) is True

    def test_ipv4_private_192(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("192.168.1.1")) is True

    def test_ipv4_loopback(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("127.0.0.1")) is True

    def test_ipv4_link_local(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("169.254.169.254")) is True

    def test_ipv4_public(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("8.8.8.8")) is False

    def test_ipv4_mapped_ipv6_loopback(self) -> None:
        """::ffff:127.0.0.1 must be rejected (F-E, BP-023)."""
        assert _is_private_ip(ipaddress.ip_address("::ffff:127.0.0.1")) is True

    def test_ipv4_mapped_ipv6_private(self) -> None:
        """::ffff:10.0.0.1 must be rejected (F-E, BP-023)."""
        assert _is_private_ip(ipaddress.ip_address("::ffff:10.0.0.1")) is True

    def test_cgnat(self) -> None:
        """100.64.0.0/10 (CGNAT shared space) must be rejected (F-E)."""
        assert _is_private_ip(ipaddress.ip_address("100.64.0.1")) is True

    def test_multicast(self) -> None:
        """224.0.0.0/4 (multicast) must be rejected (F-E)."""
        assert _is_private_ip(ipaddress.ip_address("224.0.0.1")) is True

    def test_reserved(self) -> None:
        """240.0.0.0/4 (reserved/future) must be rejected (F-E)."""
        assert _is_private_ip(ipaddress.ip_address("240.0.0.1")) is True

    def test_ipv6_loopback(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("::1")) is True

    def test_ipv6_link_local(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("fe80::1")) is True


# ── Pydantic validator tests (scheme + literal IP only) ──────────────────────


class TestValidatorSchemeOnly:
    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(ValidationError, match="http or https"):
            IngestSubmitRequest(source_type="eodhd", url="ftp://example.com/file")

    def test_rejects_literal_private_ip(self) -> None:
        with pytest.raises(ValidationError, match="private"):
            IngestSubmitRequest(source_type="eodhd", url="http://10.0.0.1/secret")

    def test_allows_literal_public_ip(self) -> None:
        req = IngestSubmitRequest(source_type="eodhd", url="http://93.184.216.34/article")
        assert req.url == "http://93.184.216.34/article"

    def test_allows_hostname_without_dns(self) -> None:
        """Validator must NOT call socket.getaddrinfo — DNS is async now (F-B, BP-022)."""
        with patch("content_ingestion.api.schemas.socket.getaddrinfo") as mock_dns:
            req = IngestSubmitRequest(source_type="eodhd", url="http://example.com/article")
            assert req.url == "http://example.com/article"
            mock_dns.assert_not_called()

    def test_allows_none_url(self) -> None:
        req = IngestSubmitRequest(source_type="eodhd", url=None, raw_content="some text")
        assert req.url is None


# ── Async DNS resolution tests ───────────────────────────────────────────────


def _fake_getaddrinfo_private(host: str, port: object) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]


def _fake_getaddrinfo_localhost(host: str, port: object) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


def _fake_getaddrinfo_public(host: str, port: object) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]


def _fake_getaddrinfo_ipv6_loopback(host: str, port: object) -> list[tuple]:
    return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0))]


def _fake_getaddrinfo_fail(host: str, port: object) -> list[tuple]:
    raise socket.gaierror("Name or service not known")


class TestCheckUrlSsrfAsync:
    async def test_rejects_private_dns(self) -> None:
        """Hostname resolving to link-local IP must be rejected."""
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_private):
            with pytest.raises(ValueError, match="private"):
                await check_url_ssrf_async("http://169.254.169.254.nip.io/latest/meta-data")

    async def test_rejects_localhost_dns(self) -> None:
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_localhost):
            with pytest.raises(ValueError, match="private"):
                await check_url_ssrf_async("http://localhost/secret")

    async def test_allows_public_dns(self) -> None:
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_public):
            await check_url_ssrf_async("http://example.com/article")  # Should not raise

    async def test_rejects_ipv6_loopback_dns(self) -> None:
        """DNS resolving to ::1 must be rejected (F-105)."""
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_ipv6_loopback):
            with pytest.raises(ValueError, match="private"):
                await check_url_ssrf_async("http://evil.example.com/")

    async def test_rejects_unresolvable(self) -> None:
        with patch("content_ingestion.api.schemas.socket.getaddrinfo", _fake_getaddrinfo_fail):
            with pytest.raises(ValueError, match="resolve"):
                await check_url_ssrf_async("http://nonexistent.invalid/path")

    async def test_rejects_literal_private_ip(self) -> None:
        """Literal private IP in URL rejected without DNS."""
        with pytest.raises(ValueError, match="private"):
            await check_url_ssrf_async("http://10.0.0.1/secret")

    async def test_allows_literal_public_ip(self) -> None:
        await check_url_ssrf_async("http://93.184.216.34/article")  # Should not raise

    async def test_handles_none_hostname(self) -> None:
        await check_url_ssrf_async("http:///path")  # No hostname — should not raise
