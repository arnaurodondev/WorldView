"""Unit tests for api_gateway.application.http_utils.

Covers:
- proxy_get: success, retry on 500, retry on 503, no retry on 404, network errors
- proxy_post: success, JSON body forwarding, no retry by default, retry opt-in
- map_upstream_error: 500 → 502, 404 → 404
- map_network_error: timeout → 503

All tests mock asyncio.sleep to avoid real delays and assert backoff call counts
so the retry logic is exercised without slowing the test suite down.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from api_gateway.application.http_utils import (
    map_network_error,
    map_upstream_error,
    proxy_get,
    proxy_post,
)
from fastapi import HTTPException

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


def _mock_response(status: int, body: dict | None = None, text: str = "") -> MagicMock:
    """Build a minimal mock httpx.Response.

    WHY MagicMock(spec=httpx.Response): constructing a real httpx.Response
    requires a Request object and low-level internals; the mock is sufficient
    because _checked_get/post only reads .status_code, .text[:200], and .json().
    """
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    # .text is read for error-detail truncation (text[:200])
    r.text = text or json.dumps(body or {})
    # .json() is called on success to deserialise the response body
    r.json = MagicMock(return_value=body or {})
    return r


def _mock_http_status_error(status: int, body: str = "") -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError with a minimal mock response."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status
    mock_resp.text = body or f"HTTP {status} error"
    return httpx.HTTPStatusError(
        message=f"HTTP {status}",
        request=MagicMock(spec=httpx.Request),
        response=mock_resp,
    )


# ── proxy_get tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_get_success() -> None:
    """200 response is parsed and returned directly."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [_mock_response(200, {"data": "ok"})]

    with patch("api_gateway.clients.asyncio.sleep", AsyncMock()):
        result = await proxy_get(mock_client, "svc", "/path")

    assert result == {"data": "ok"}
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_proxy_get_retries_on_500() -> None:
    """500 twice then 200 → retries and returns the success body."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [
        _mock_response(500, text="server error"),
        _mock_response(500, text="still broken"),
        _mock_response(200, {"recovered": True}),
    ]

    sleep_mock = AsyncMock()
    with patch("api_gateway.clients.asyncio.sleep", sleep_mock):
        result = await proxy_get(mock_client, "svc", "/path")

    assert result == {"recovered": True}
    # 3 attempts: initial + 2 retries
    assert mock_client.get.call_count == 3
    # sleep called twice (before attempt 2 and 3; not before the first attempt)
    assert sleep_mock.call_count == 2


@pytest.mark.asyncio
async def test_proxy_get_retries_on_503() -> None:
    """503 then 200 → retries and succeeds (503 is in _RETRY_STATUSES)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [
        _mock_response(503, text="unavailable"),
        _mock_response(200, {"ok": True}),
    ]

    sleep_mock = AsyncMock()
    with patch("api_gateway.clients.asyncio.sleep", sleep_mock):
        result = await proxy_get(mock_client, "svc", "/path")

    assert result == {"ok": True}
    assert mock_client.get.call_count == 2
    assert sleep_mock.call_count == 1


@pytest.mark.asyncio
async def test_proxy_get_no_retry_on_404() -> None:
    """404 raises HTTPException(404) immediately — 4xx is never retried."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [_mock_response(404, text="not found")]

    sleep_mock = AsyncMock()
    with patch("api_gateway.clients.asyncio.sleep", sleep_mock):
        with pytest.raises(HTTPException) as exc_info:
            await proxy_get(mock_client, "svc", "/path")

    # 404 from upstream → forwarded as 404 (not remapped to 502)
    assert exc_info.value.status_code == 404
    # Only 1 attempt — 404 is deterministic
    assert mock_client.get.call_count == 1
    assert sleep_mock.call_count == 0


@pytest.mark.asyncio
async def test_proxy_get_timeout_raises_503() -> None:
    """httpx.TimeoutException on GET → HTTPException(503)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.TimeoutException("timeout")

    with patch("api_gateway.clients.asyncio.sleep", AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await proxy_get(mock_client, "my-service", "/path")

    assert exc_info.value.status_code == 503
    assert "my-service" in exc_info.value.detail


@pytest.mark.asyncio
async def test_proxy_get_network_error_raises_503() -> None:
    """httpx.NetworkError on GET → HTTPException(503)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.NetworkError("connection refused")

    with patch("api_gateway.clients.asyncio.sleep", AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await proxy_get(mock_client, "my-service", "/path")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_proxy_get_params_forwarded() -> None:
    """params kwarg is forwarded to the underlying httpx client GET call."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [_mock_response(200, {"results": []})]

    with patch("api_gateway.clients.asyncio.sleep", AsyncMock()):
        await proxy_get(mock_client, "svc", "/search", params={"q": "AAPL", "page": 1})

    call_kwargs = mock_client.get.call_args.kwargs
    assert call_kwargs.get("params") == {"q": "AAPL", "page": 1}


@pytest.mark.asyncio
async def test_proxy_get_5xx_exhausted_raises_502() -> None:
    """All 4 attempts return 500 → HTTPException(502) (gateway maps 5xx → 502)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    # _RETRY_DELAYS has 3 elements → 4 total attempts (initial + 3 retries)
    mock_client.get.side_effect = [_mock_response(500, text="err")] * 4

    sleep_mock = AsyncMock()
    with patch("api_gateway.clients.asyncio.sleep", sleep_mock):
        with pytest.raises(HTTPException) as exc_info:
            await proxy_get(mock_client, "svc", "/path")

    # 5xx from upstream → 502 (our gateway is fine; upstream is broken)
    assert exc_info.value.status_code == 502
    assert mock_client.get.call_count == 4


# ── proxy_post tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_proxy_post_success() -> None:
    """POST 200 → returns parsed body directly."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [_mock_response(200, {"created": True})]

    with patch("api_gateway.clients.asyncio.sleep", AsyncMock()):
        result = await proxy_post(mock_client, "svc", "/items")

    assert result == {"created": True}
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_proxy_post_json_body_forwarded() -> None:
    """json= kwarg is forwarded as the POST body."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [_mock_response(200, {"id": "abc"})]
    payload = {"name": "My Watchlist", "tickers": ["AAPL", "MSFT"]}

    with patch("api_gateway.clients.asyncio.sleep", AsyncMock()):
        result = await proxy_post(mock_client, "svc", "/items", json=payload)

    assert result == {"id": "abc"}
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs.get("json") == payload


@pytest.mark.asyncio
async def test_proxy_post_no_retry_by_default() -> None:
    """POST 503 without allow_retry → HTTPException raised after 1 attempt (BP-025)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [_mock_response(503, text="unavailable")]

    sleep_mock = AsyncMock()
    with patch("api_gateway.clients.asyncio.sleep", sleep_mock):
        with pytest.raises(HTTPException) as exc_info:
            await proxy_post(mock_client, "svc", "/items")

    assert exc_info.value.status_code == 502  # 5xx → 502
    # Only 1 attempt — POST is not idempotent by default
    assert mock_client.post.call_count == 1
    assert sleep_mock.call_count == 0


@pytest.mark.asyncio
async def test_proxy_post_retries_when_allow_retry_true() -> None:
    """allow_retry=True: 500 then 200 → retries and succeeds."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [
        _mock_response(500, text="server error"),
        _mock_response(200, {"ok": True}),
    ]

    sleep_mock = AsyncMock()
    with patch("api_gateway.clients.asyncio.sleep", sleep_mock):
        result = await proxy_post(mock_client, "svc", "/items", allow_retry=True)

    assert result == {"ok": True}
    assert mock_client.post.call_count == 2
    assert sleep_mock.call_count == 1


@pytest.mark.asyncio
async def test_proxy_post_timeout_raises_503() -> None:
    """httpx.TimeoutException on POST → HTTPException(503)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.TimeoutException("timed out")

    with patch("api_gateway.clients.asyncio.sleep", AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await proxy_post(mock_client, "chat", "/api/v1/chat")

    assert exc_info.value.status_code == 503
    assert "chat" in exc_info.value.detail


# ── map_upstream_error tests ────────────────────────────────────────────────────


def test_map_upstream_error_500_returns_502() -> None:
    """HTTP 500 from upstream → HTTPException(502 Bad Gateway)."""
    exc = _mock_http_status_error(500, "Internal Server Error")
    result = map_upstream_error(exc)

    assert isinstance(result, HTTPException)
    assert result.status_code == 502
    assert "502" in result.detail or "error" in result.detail.lower()


def test_map_upstream_error_503_returns_502() -> None:
    """HTTP 503 from upstream → HTTPException(502 Bad Gateway)."""
    exc = _mock_http_status_error(503, "Service Unavailable")
    result = map_upstream_error(exc)

    assert isinstance(result, HTTPException)
    assert result.status_code == 502


def test_map_upstream_error_404_returns_404() -> None:
    """HTTP 404 from upstream → HTTPException(404) — mirrors the client error."""
    exc = _mock_http_status_error(404, "not found")
    result = map_upstream_error(exc)

    assert isinstance(result, HTTPException)
    assert result.status_code == 404
    assert "not found" in result.detail


def test_map_upstream_error_403_returns_403() -> None:
    """HTTP 403 from upstream → HTTPException(403) — client is forbidden."""
    exc = _mock_http_status_error(403, "forbidden")
    result = map_upstream_error(exc)

    assert isinstance(result, HTTPException)
    assert result.status_code == 403


def test_map_upstream_error_truncates_long_body() -> None:
    """4xx detail is truncated to 200 chars to avoid leaking internals (F-005)."""
    long_body = "x" * 500
    exc = _mock_http_status_error(422, long_body)
    result = map_upstream_error(exc)

    assert isinstance(result, HTTPException)
    assert result.status_code == 422
    assert len(result.detail) <= 200


# ── map_network_error tests ────────────────────────────────────────────────────


def test_map_network_error_timeout_returns_503() -> None:
    """httpx.TimeoutException → HTTPException(503) with service name in detail."""
    exc = httpx.TimeoutException("timed out after 10s")
    result = map_network_error(exc, "portfolio")

    assert isinstance(result, HTTPException)
    assert result.status_code == 503
    assert "portfolio" in result.detail


def test_map_network_error_default_service_name() -> None:
    """Default service_name is 'upstream' when not provided."""
    exc = httpx.NetworkError("connection refused")
    result = map_network_error(exc)

    assert isinstance(result, HTTPException)
    assert result.status_code == 503
    assert "upstream" in result.detail
