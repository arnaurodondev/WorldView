"""Unit tests for _checked_get and _checked_post retry logic (T-A-2-01).

Verifies:
1. _checked_get retries on 500 twice then succeeds on 200.
2. _checked_get raises immediately on 404 (no retry for 4xx).
3. _checked_post does NOT retry by default (allow_retry=False).
4. _checked_post retries when allow_retry=True.
5. _checked_get exhausts all retries (3x 500) and raises the last error.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from api_gateway.clients import DownstreamError, _checked_get, _checked_post

pytestmark = pytest.mark.unit


def _make_response(status: int, body: bytes) -> MagicMock:
    """Build a lightweight mock httpx.Response for the given status + body.

    WHY MagicMock(spec=httpx.Response) instead of a real httpx.Response:
    constructing a real Response requires a Request object and low-level
    internals. The mock is sufficient because _checked_get/post only reads
    .status_code, .text[:200], and .json() — all easily stubbed.
    """
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    # .text is read for error detail truncation (text[:200])
    r.text = body.decode("utf-8", errors="replace")
    # .json() is called on success to deserialise the response body
    r.json = MagicMock(return_value=json.loads(body) if status < 400 else {})
    return r


# ── _checked_get retry tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checked_get_retries_500_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """500 twice then 200 → returns the 200 body (3 total attempts)."""
    # Patch asyncio.sleep to avoid real delays in unit tests. We still
    # assert that it was called so the backoff logic is exercised.
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [
        _make_response(500, b'{"err": "oops"}'),
        _make_response(500, b'{"err": "still bad"}'),
        _make_response(200, b'{"ok": true}'),
    ]

    result = await _checked_get(mock_client, "svc", "/test")

    assert result == {"ok": True}
    # 3 attempts: initial + 2 retries
    assert mock_client.get.call_count == 3
    # sleep called twice (before attempt 2 and attempt 3, not before attempt 1)
    assert sleep_mock.call_count == 2


@pytest.mark.asyncio
async def test_checked_get_does_not_retry_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 → raises DownstreamError immediately without retrying."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [_make_response(404, b"not found")]

    with pytest.raises(DownstreamError) as exc_info:
        await _checked_get(mock_client, "svc", "/test")

    assert exc_info.value.status == 404
    # Only 1 attempt — 404 is not in _RETRY_STATUSES
    assert mock_client.get.call_count == 1
    # No sleep on the first attempt (delay is 0.0)
    assert sleep_mock.call_count == 0


@pytest.mark.asyncio
async def test_checked_get_does_not_retry_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """401 (auth failure) → raises immediately (deterministic, retrying won't help)."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [_make_response(401, b"unauthorized")]

    with pytest.raises(DownstreamError) as exc_info:
        await _checked_get(mock_client, "svc", "/test")

    assert exc_info.value.status == 401
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_checked_get_exhausts_retries_raises_last(monkeypatch: pytest.MonkeyPatch) -> None:
    """All 4 attempts (initial + 3 retries) return 503 → raises DownstreamError."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    # 4 calls: initial + 3 retry attempts (_RETRY_DELAYS has 3 elements)
    mock_client.get.side_effect = [
        _make_response(503, b"unavailable"),
        _make_response(503, b"unavailable"),
        _make_response(503, b"unavailable"),
        _make_response(503, b"unavailable"),
    ]

    with pytest.raises(DownstreamError) as exc_info:
        await _checked_get(mock_client, "svc", "/test")

    assert exc_info.value.status == 503
    # 4 total attempts: attempt 0 (delay=0.0), 1 (0.1s), 2 (0.5s), 3 (1.5s)
    assert mock_client.get.call_count == 4
    # sleep called 3 times (before each retry; not before initial attempt)
    assert sleep_mock.call_count == 3


@pytest.mark.asyncio
async def test_checked_get_retries_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """503 then 200 → retries and succeeds (503 is in _RETRY_STATUSES)."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [
        _make_response(503, b"unavailable"),
        _make_response(200, b'{"recovered": true}'),
    ]

    result = await _checked_get(mock_client, "svc", "/test")

    assert result == {"recovered": True}
    assert mock_client.get.call_count == 2


# ── _checked_post retry tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_checked_post_does_not_retry_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST 503 → raises immediately with allow_retry=False (default).

    WHY: POST may create duplicate records on retry. Never retry by default
    (BP-025 idempotency rule).
    """
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [_make_response(503, b"unavailable")]

    with pytest.raises(DownstreamError) as exc_info:
        await _checked_post(mock_client, "svc", "/test")

    assert exc_info.value.status == 503
    # Only 1 attempt — allow_retry=False is the default
    assert mock_client.post.call_count == 1
    assert sleep_mock.call_count == 0


@pytest.mark.asyncio
async def test_checked_post_does_not_retry_500_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST 500 → raises immediately when allow_retry=False."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [_make_response(500, b"server error")]

    with pytest.raises(DownstreamError) as exc_info:
        await _checked_post(mock_client, "svc", "/test")

    assert exc_info.value.status == 500
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_checked_post_retries_when_allow_retry_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """allow_retry=True: 500 then 200 → retries and succeeds.

    Only callers that guarantee idempotency should pass allow_retry=True.
    """
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [
        _make_response(500, b"error"),
        _make_response(200, b'{"created": true}'),
    ]

    result = await _checked_post(mock_client, "svc", "/test", allow_retry=True)

    assert result == {"created": True}
    assert mock_client.post.call_count == 2
    assert sleep_mock.call_count == 1


@pytest.mark.asyncio
async def test_checked_post_success_no_retry_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST 200 on first attempt → returns body immediately (no retry)."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = [_make_response(200, b'{"status": "ok"}')]

    result = await _checked_post(mock_client, "svc", "/test")

    assert result == {"status": "ok"}
    assert mock_client.post.call_count == 1
    assert sleep_mock.call_count == 0


@pytest.mark.asyncio
async def test_checked_get_passes_kwargs_on_each_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """kwargs (e.g. params=) are forwarded to every retry attempt."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [
        _make_response(503, b"unavailable"),
        _make_response(200, b'{"x": 1}'),
    ]

    await _checked_get(mock_client, "svc", "/test", params={"q": "hello"})

    # Both calls must have received the params kwarg
    for call in mock_client.get.call_args_list:
        assert call.kwargs.get("params") == {"q": "hello"}


@pytest.mark.asyncio
async def test_downstream_error_detail_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Error detail is truncated to 200 chars (F-005 — don't leak internals)."""
    sleep_mock = AsyncMock()
    monkeypatch.setattr("api_gateway.clients.asyncio.sleep", sleep_mock)

    long_error = "x" * 500
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = [_make_response(404, long_error.encode())]

    with pytest.raises(DownstreamError) as exc_info:
        await _checked_get(mock_client, "svc", "/test")

    assert len(exc_info.value.detail) <= 200
