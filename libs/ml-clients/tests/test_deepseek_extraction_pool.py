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


def test_default_extraction_timeout_is_300s() -> None:
    """Default PER-ATTEMPT wall-clock cap is 300s (gpt-oss-120b deep-extraction tail).

    Task #5 raised the per-attempt cap 90 -> 300s and Task #9 swapped the extraction
    primary to ``openai/gpt-oss-120b@medium`` (fallback ``gpt-oss-20b@low``); a
    medium-effort 120B reasoning pass can spend the better part of a minute enumerating
    candidate entity pairs, so the per-attempt cap is sized for that legitimate tail.
    With the higher cap a bounded retry (default 1 initial + 1 retry = 2 attempts) fits
    inside the TOTAL per-model budget (``_EXTRACTION_TOTAL_BUDGET_S`` = 320s).  The httpx
    read timeout is wired to the same per-attempt value so it never fires before the
    asyncio.wait_for guard.
    """
    from ml_clients.adapters.deepseek_extraction import (
        _EXTRACTION_MAX_ATTEMPTS,
        _EXTRACTION_TIMEOUT_S,
        _EXTRACTION_TOTAL_BUDGET_S,
    )

    assert _EXTRACTION_TIMEOUT_S == pytest.approx(300.0)
    # Task #5: per-model total budget = 320s (one 300s attempt + a short backoff +
    # headroom; the cap bounds the whole per-model call regardless of attempt count).
    assert _EXTRACTION_TOTAL_BUDGET_S == pytest.approx(320.0)
    # Task #5: default attempts lowered 3 -> 2 (1 initial + 1 retry) so a 300s cap fits
    # the per-model budget.
    assert _EXTRACTION_MAX_ATTEMPTS == 2
    # Budget arithmetic: a 300s attempt must fit inside the per-model total budget,
    # which caps the whole per-model call regardless of attempt count.
    assert _EXTRACTION_TIMEOUT_S < _EXTRACTION_TOTAL_BUDGET_S

    # Default constructor (no explicit timeout_s) propagates 300s to the http client.
    adapter = _make_adapter()
    httpx_client = adapter._client._client  # type: ignore[attr-defined]
    assert httpx_client.timeout.read == pytest.approx(300.0)
