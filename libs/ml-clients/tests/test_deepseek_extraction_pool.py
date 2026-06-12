"""DeepSeek extraction adapter — httpx connection-pool limits (Task #14).

Deep extraction on DeepInfra is I/O-bound (12-22s network wait per article).
When the article consumer runs many extractions concurrently, an equal number
of calls hit this adapter's shared client at once.  httpx's default Limits
(max_connections=100, max_keepalive=20) silently queue connections beyond the
keepalive pool.  These tests assert the adapter wires an explicit
``httpx.Limits`` from the constructor args so the pool is sized for the
configured concurrency.

The tests introspect the *real* httpx connection pool that the adapter built
and handed to the openai SDK (``openai.AsyncOpenAI(http_client=...)``), rather
than patching ``httpx.AsyncClient`` — patching it breaks the SDK's internal
``isinstance(http_client, httpx.AsyncClient)`` guard.
"""

from __future__ import annotations

import asyncio

import pytest


def _pool(adapter: object):  # type: ignore[no-untyped-def]
    """Return the httpcore connection pool backing the adapter's openai client.

    Path: DeepSeekExtractionAdapter._client (openai.AsyncOpenAI)
          ._client (httpx.AsyncClient)._transport (httpx.AsyncHTTPTransport)
          ._pool (httpcore.AsyncConnectionPool).
    """
    httpx_client = adapter._client._client  # type: ignore[attr-defined]
    return httpx_client._transport._pool


def _make_adapter(**kwargs: object):  # type: ignore[no-untyped-def]
    from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter

    return DeepSeekExtractionAdapter(
        api_key="test-key",
        semaphore=asyncio.Semaphore(1),
        **kwargs,  # type: ignore[arg-type]
    )


def test_pool_limits_applied_from_defaults() -> None:
    """Default constructor sizes the pool at 64 conns / 32 keepalive."""
    adapter = _make_adapter()
    pool = _pool(adapter)
    assert pool._max_connections == 64
    assert pool._max_keepalive_connections == 32


def test_pool_limits_configurable() -> None:
    """Constructor args override the pool size (driven by config env vars)."""
    adapter = _make_adapter(max_connections=128, max_keepalive_connections=48)
    pool = _pool(adapter)
    assert pool._max_connections == 128
    assert pool._max_keepalive_connections == 48


def test_read_timeout_preserved() -> None:
    """The wall-clock read timeout still flows into the underlying http client."""
    adapter = _make_adapter(timeout_s=120.0)
    httpx_client = adapter._client._client  # type: ignore[attr-defined]
    assert httpx_client.timeout.read == pytest.approx(120.0)


def test_default_extraction_timeout_is_150s() -> None:
    """Default wall-clock cap is 150s (raised from 90s to stop dead-letter bleed).

    p50 deep-extraction latency is ~16.5s, so 150s captures the bursty tail without
    masking genuinely-stalled requests.  The httpx read timeout is wired to the same
    value so it never fires before the asyncio.wait_for guard.
    """
    from ml_clients.adapters.deepseek_extraction import _EXTRACTION_TIMEOUT_S

    assert _EXTRACTION_TIMEOUT_S == pytest.approx(150.0)

    # Default constructor (no explicit timeout_s) propagates 150s to the http client.
    adapter = _make_adapter()
    httpx_client = adapter._client._client  # type: ignore[attr-defined]
    assert httpx_client.timeout.read == pytest.approx(150.0)
