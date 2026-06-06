"""BP-623 unit tests: BaseUpstreamClient transport-error disambiguation.

The bug (audit ``docs/audits/2026-05-29-plan-0103-real-user-failures.md``):
the legacy ``_get``/``_post`` returned ``{}`` for EVERY error class — connect
refused, DNS failure, timeout, 4xx, 5xx all collapsed to the same value.
Downstream handlers then rendered that ``{}`` as ``[]``, which the orchestrator
labelled ``status="empty"``, and the LLM said "No data was found" even when
the real situation was "the upstream is DOWN".

These tests pin the new behaviour:
  * connect failure → ``UpstreamTransportError(reason="upstream_unreachable")``
  * timeout         → ``UpstreamTransportError(reason="upstream_timeout")``
  * HTTP 5xx        → ``UpstreamTransportError(reason="upstream_5xx",
                          status_code=503)``
  * HTTP 4xx        → returns ``{}`` (4xx is "I asked wrong / the resource
                          doesn't exist", which is closer to "empty" than
                          "outage" — promoting it would over-trigger the
                          user-facing outage messaging).
  * legitimate 200 with empty payload → returns the empty payload unchanged.

The raised exception MUST inherit from ``BaseException`` (not ``Exception``)
so per-handler ``except Exception: return []`` guards do not swallow it on
the way up to ``ToolExecutor.execute``.
"""

from __future__ import annotations

import httpx
import pytest
from rag_chat.infrastructure.clients.base import (
    BaseUpstreamClient,
    UpstreamTransportError,
)

pytestmark = pytest.mark.unit


def _make_client(handler: httpx.MockTransport) -> BaseUpstreamClient:
    """Build a BaseUpstreamClient pointed at an httpx MockTransport.

    We can't pass a transport through BaseUpstreamClient's constructor (the
    real client is created internally), so we mutate ``._client`` afterwards.
    This is the same pattern used by the existing rag-chat client tests.
    """
    client = BaseUpstreamClient(base_url="http://upstream.test", timeout=5.0)
    client._client = httpx.AsyncClient(base_url="http://upstream.test", transport=handler)
    return client


# ── Inheritance gate ─────────────────────────────────────────────────────────


def test_upstream_transport_error_inherits_from_baseexception_not_exception() -> None:
    """``UpstreamTransportError`` MUST bypass ``except Exception`` guards.

    Every tool handler in ``rag_chat/application/pipeline/handlers/*`` wraps
    upstream calls in ``try/except Exception: return []`` for R9 safe
    degradation. If ``UpstreamTransportError`` inherited from ``Exception``,
    those guards would swallow it before it reached ``ToolExecutor.execute``
    — re-introducing the exact BP-623 silent-collapse pattern. Pin this
    invariant so a future refactor cannot regress it accidentally.
    """
    assert issubclass(UpstreamTransportError, BaseException)
    assert not issubclass(UpstreamTransportError, Exception)


# ── Transport-error happy paths ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_error_raises_upstream_unreachable() -> None:
    """DNS / connect refused → reason="upstream_unreachable"."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nodename nor servname provided")

    client = _make_client(httpx.MockTransport(_handler))
    with pytest.raises(UpstreamTransportError) as exc_info:
        await client._get("/v1/anything")
    assert exc_info.value.reason == "upstream_unreachable"
    assert exc_info.value.status_code is None
    assert exc_info.value.path == "/v1/anything"
    assert exc_info.value.elapsed_ms >= 0


@pytest.mark.asyncio
async def test_timeout_raises_upstream_timeout() -> None:
    """Read/write/connect timeout → reason="upstream_timeout"."""

    def _handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow upstream")

    client = _make_client(httpx.MockTransport(_handler))
    with pytest.raises(UpstreamTransportError) as exc_info:
        await client._post("/v1/slow", {"q": 1})
    assert exc_info.value.reason == "upstream_timeout"
    assert exc_info.value.status_code is None


@pytest.mark.asyncio
async def test_http_503_raises_upstream_5xx_with_status_code() -> None:
    """HTTP 5xx → reason="upstream_5xx", status_code set."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "upstream overloaded"})

    client = _make_client(httpx.MockTransport(_handler))
    with pytest.raises(UpstreamTransportError) as exc_info:
        await client._get("/v1/data")
    assert exc_info.value.reason == "upstream_5xx"
    assert exc_info.value.status_code == 503


# ── HTTP 4xx — must NOT promote to transport_error ───────────────────────────


@pytest.mark.asyncio
async def test_http_404_returns_empty_dict_not_transport_error() -> None:
    """4xx errors stay as ``{}`` so callers treat them as "no result" rather
    than as an upstream outage. Promoting 4xx would over-trigger the user-
    facing "I cannot reach the data source" copy on every legitimate "not
    found" / "bad request"."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    client = _make_client(httpx.MockTransport(_handler))
    result = await client._get("/v1/missing")
    assert result == {}


@pytest.mark.asyncio
async def test_http_422_returns_empty_dict_not_transport_error() -> None:
    """Same shape as 404 — validation error is a client-side problem, not an
    outage."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad payload"})

    client = _make_client(httpx.MockTransport(_handler))
    result = await client._post("/v1/anything", {"bad": "input"})
    assert result == {}


# ── 200 OK with empty list — must NOT be transport_error ─────────────────────


@pytest.mark.asyncio
async def test_http_200_with_empty_dict_returns_empty_dict_not_transport_error() -> None:
    """A successful response with an empty payload is the canonical "empty"
    case the BP-623 fix EXISTS to distinguish from transport errors. Pinning
    this contract here makes the disambiguation invariant testable end-to-end.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = _make_client(httpx.MockTransport(_handler))
    result = await client._get("/v1/fundamentals/batch", params={"tickers": "TSLA"})
    assert result == {}


@pytest.mark.asyncio
async def test_http_200_with_empty_list_field_passes_through_unchanged() -> None:
    """An upstream returning ``{"items": []}`` is a 200-OK empty result; it
    must traverse the client untouched."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    client = _make_client(httpx.MockTransport(_handler))
    result = await client._post("/v1/search", {"q": "x"})
    assert result == {"items": [], "next_cursor": None}
