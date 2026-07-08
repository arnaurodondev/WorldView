"""EMBED-RESIL regression: S6 query-embedding hop timeout + single retry.

The bug (clean eval ``run_20260707T201337Z``): the query-embedding hop
``rag-chat → S6 POST /api/v1/embed → DeepInfra bge-large`` timed out at ~10s
(``tool_transport_error reason=upstream_timeout path=/api/v1/embed``) under
concurrent load, cascading into failures of ``search_entity_relations``, entity
resolution and semantic search. DeepInfra itself was healthy (idle ~0.3s) — a
tight-timeout + no-retry gap, NOT an outage.

Two defences pinned here:

  1. **Dedicated longer read timeout** — the embed POST uses its own
     ``httpx.Timeout`` with ``read`` aligned to the 30s upstream default (not
     the deployment's tight ~10s shared upstream timeout) so a slow-but-
     successful embedding is not killed.

  2. **Retry once on a transport timeout** — a single ``upstream_timeout`` /
     ``upstream_unreachable`` failure triggers exactly one fresh retry; if the
     retry also fails the ``UpstreamTransportError`` propagates (BP-623: the
     tool surfaces "cannot reach upstream" rather than a silent zero vector).
"""

from __future__ import annotations

import httpx
import pytest
from rag_chat.application.pipeline.transport_error import UpstreamTransportError
from rag_chat.infrastructure.clients.s6_client import S6Client

pytestmark = pytest.mark.unit

_OK_BODY = {"embedding": [0.1] * 1024}


def _s6_with_transport(handler: httpx.MockTransport, *, embed_timeout_seconds: float | None = None) -> S6Client:
    """Build an S6Client whose real ``_post`` runs against a MockTransport.

    We swap ``._client`` after construction (same pattern as the resolve-retry
    tests) so the genuine ``embed_text`` → ``_post`` → retry chain is exercised
    rather than mocked out.
    """
    client = S6Client(
        base_url="http://nlp-pipeline.test:8006",
        timeout=10.0,  # the deployment's tight shared upstream timeout
        embed_timeout_seconds=embed_timeout_seconds,
    )
    client._client = httpx.AsyncClient(base_url="http://nlp-pipeline.test:8006", transport=handler)
    return client


# ── Timeout is raised to the upstream default (BP-235 explicit httpx.Timeout) ──


def test_embed_read_timeout_defaults_to_upstream_default_not_shared_10s() -> None:
    """The embed hop's read timeout is >=20s even when the shared timeout is 10s.

    Pins that the slow bge-large call gets a generous read budget and is NOT
    killed at the deployment-tightened ~10s shared upstream ReadTimeout.
    """
    client = S6Client(base_url="http://nlp-pipeline.test:8006", timeout=10.0)
    assert client._embed_timeout_seconds >= 20.0
    # Explicit configuration wins over the max(timeout, 30) default.
    tuned = S6Client(base_url="http://x", timeout=10.0, embed_timeout_seconds=25.0)
    assert tuned._embed_timeout_seconds == 25.0


@pytest.mark.asyncio
async def test_embed_uses_explicit_httpx_timeout_with_long_read() -> None:
    """The embed POST passes a per-request ``httpx.Timeout`` with read>=20s.

    Captures the effective request timeout the transport sees so we assert the
    read leg is the raised value (not the tight 10s shared client default), and
    that connect stays tight (BP-235: distinct connect vs read legs).
    """
    seen: dict[str, httpx.Timeout] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        ext = request.extensions.get("timeout") or {}
        seen["read"] = ext.get("read")  # type: ignore[assignment]
        seen["connect"] = ext.get("connect")  # type: ignore[assignment]
        return httpx.Response(200, json=_OK_BODY)

    client = _s6_with_transport(httpx.MockTransport(_handler))
    vec = await client.embed_text("Apple acquisitions")

    assert len(vec) == 1024
    assert seen["read"] is not None and seen["read"] >= 20.0, "embed read timeout must be raised, not 10s"
    assert seen["connect"] == 5.0, "connect leg stays tight"


# ── Retry once on a transport timeout, then succeed ───────────────────────────


@pytest.mark.asyncio
async def test_embed_retries_once_on_read_timeout_then_succeeds() -> None:
    """First call ReadTimeout → one retry → real embedding returned.

    This is the exact eval failure path made recoverable: a transient slow first
    embedding is retried on a fresh call which succeeds.
    """
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("query embedding timed out", request=request)
        return httpx.Response(200, json=_OK_BODY)

    client = _s6_with_transport(httpx.MockTransport(_handler))
    vec = await client.embed_text("Apple acquisitions")

    assert calls["n"] == 2, "exactly one retry after the read-timeout"
    assert len(vec) == 1024
    assert vec[0] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_embed_gives_up_after_retry_and_raises() -> None:
    """Both attempts ReadTimeout → bounded retry, then ``UpstreamTransportError``.

    The transport error must PROPAGATE (BaseException — not the silent zero
    vector) so the caller surfaces the outage (BP-623). Attempt count is pinned
    so the retry stays bounded (no latency blow-up on a genuinely-slow upstream).
    """
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("still timing out", request=request)

    client = _s6_with_transport(httpx.MockTransport(_handler))

    with pytest.raises(UpstreamTransportError) as exc_info:
        await client.embed_text("Apple acquisitions")

    assert exc_info.value.reason == "upstream_timeout"
    assert exc_info.value.path == "/api/v1/embed"
    assert calls["n"] == 2, "first try + exactly one retry, then give up"


@pytest.mark.asyncio
async def test_embed_does_not_retry_upstream_5xx() -> None:
    """A 5xx (up-but-broken) is NOT retried — fail fast, propagate immediately."""
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"detail": "unavailable"})

    client = _s6_with_transport(httpx.MockTransport(_handler))

    with pytest.raises(UpstreamTransportError) as exc_info:
        await client.embed_text("Apple acquisitions")

    assert exc_info.value.reason == "upstream_5xx"
    assert calls["n"] == 1, "5xx must NOT be retried"


@pytest.mark.asyncio
async def test_embed_success_first_try_makes_exactly_one_call() -> None:
    """Happy path: one 200 response, one HTTP call, embedding returned unchanged."""
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_OK_BODY)

    client = _s6_with_transport(httpx.MockTransport(_handler))
    vec = await client.embed_text("Apple acquisitions")

    assert calls["n"] == 1, "no retry on success — behaviour unchanged"
    assert len(vec) == 1024


@pytest.mark.asyncio
async def test_embed_non_transport_error_degrades_to_zero_vector() -> None:
    """A non-transport error still degrades to a zero vector (unchanged R9 path).

    A malformed JSON body raises a plain ``Exception`` inside ``_post``/parse,
    which is caught and degraded so callers can detect the empty vector.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})

    client = _s6_with_transport(httpx.MockTransport(_handler))
    vec = await client.embed_text("Apple acquisitions")

    assert vec == [0.0] * 1024


@pytest.mark.asyncio
async def test_embed_empty_text_short_circuits_without_call() -> None:
    """Blank text returns a zero vector without any HTTP call (unchanged)."""
    calls = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not fire
        calls["n"] += 1
        return httpx.Response(200, json=_OK_BODY)

    client = _s6_with_transport(httpx.MockTransport(_handler))
    vec = await client.embed_text("   ")

    assert vec == [0.0] * 1024
    assert calls["n"] == 0
