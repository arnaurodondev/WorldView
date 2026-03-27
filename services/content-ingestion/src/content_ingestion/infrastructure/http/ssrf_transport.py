"""SSRF-safe httpx transport — validates resolved IPs at connection time.

Prevents DNS rebinding attacks by checking the resolved IP address
just before the TCP connection is established, closing the TOCTOU window
between URL validation and actual HTTP request (BP-024).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpx
import structlog

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP is private, reserved, loopback, multicast, or link-local."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return bool(
        addr.is_private
        or addr.is_reserved
        or addr.is_loopback
        or addr.is_multicast
        or addr.is_link_local
        or (isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT_NETWORK)
    )


class SSRFSafeTransport(httpx.AsyncBaseTransport):
    """httpx transport that validates resolved IPs before connecting.

    Wraps the standard AsyncHTTPTransport and adds a DNS resolution check
    before each request. This prevents DNS rebinding: even if DNS returned
    a public IP at validation time, a private IP at connection time is blocked.
    """

    def __init__(self, **kwargs: object) -> None:
        self._inner = httpx.AsyncHTTPTransport(**kwargs)  # type: ignore[arg-type]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Validate resolved IPs then delegate to inner transport."""
        hostname = request.url.host
        if hostname:
            try:
                addr_infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
            except socket.gaierror:
                msg = f"SSRF: could not resolve {hostname}"
                raise httpx.ConnectError(msg)  # noqa: B904

            for _family, _type, _proto, _canonname, sockaddr in addr_infos:
                addr = ipaddress.ip_address(sockaddr[0])
                if _is_private_ip(addr):
                    msg = f"SSRF blocked: {hostname} resolved to private IP {addr}"
                    logger.warning("ssrf_transport_blocked", hostname=hostname, resolved_ip=str(addr))
                    raise httpx.ConnectError(msg)

        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        """Close the inner transport."""
        await self._inner.aclose()
