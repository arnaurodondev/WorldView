"""Unit tests for SSRFSafeTransport — DNS rebinding prevention at connection time."""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from content_ingestion.infrastructure.http.ssrf_transport import SSRFSafeTransport, _is_private_ip

pytestmark = pytest.mark.unit


class TestTransportIsPrivateIp:
    def test_ipv4_private(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("10.0.0.1")) is True

    def test_ipv4_public(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("8.8.8.8")) is False

    def test_ipv4_mapped_ipv6_private(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("::ffff:10.0.0.1")) is True

    def test_ipv4_mapped_ipv6_loopback(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("::ffff:127.0.0.1")) is True

    def test_ipv6_loopback(self) -> None:
        assert _is_private_ip(ipaddress.ip_address("::1")) is True


class TestSSRFSafeTransport:
    @patch("content_ingestion.infrastructure.http.ssrf_transport.socket.getaddrinfo")
    async def test_blocks_private_ip(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 80)),
        ]
        transport = SSRFSafeTransport()
        request = httpx.Request("GET", "http://evil.example.com/")

        with pytest.raises(httpx.ConnectError, match="SSRF blocked"):
            await transport.handle_async_request(request)

    @patch("content_ingestion.infrastructure.http.ssrf_transport.socket.getaddrinfo")
    async def test_allows_public_ip(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80)),
        ]
        transport = SSRFSafeTransport()
        transport._inner = AsyncMock()
        transport._inner.handle_async_request.return_value = httpx.Response(200)
        request = httpx.Request("GET", "http://example.com/")

        response = await transport.handle_async_request(request)
        assert response.status_code == 200

    @patch("content_ingestion.infrastructure.http.ssrf_transport.socket.getaddrinfo")
    async def test_blocks_ipv4_mapped_ipv6(self, mock_getaddrinfo: MagicMock) -> None:
        """Transport must block IPv4-mapped IPv6 addresses (DNS rebinding via ::ffff:)."""
        mock_getaddrinfo.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::ffff:10.0.0.1", 80, 0, 0)),
        ]
        transport = SSRFSafeTransport()
        request = httpx.Request("GET", "http://sneaky.example.com/")

        with pytest.raises(httpx.ConnectError, match="SSRF blocked"):
            await transport.handle_async_request(request)

    @patch("content_ingestion.infrastructure.http.ssrf_transport.socket.getaddrinfo")
    async def test_blocks_dns_resolution_failure(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.side_effect = socket.gaierror("Name not found")
        transport = SSRFSafeTransport()
        request = httpx.Request("GET", "http://nonexistent.invalid/")

        with pytest.raises(httpx.ConnectError, match="could not resolve"):
            await transport.handle_async_request(request)
