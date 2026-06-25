"""Unit tests for FIX-LIVE-D — RateLimitMiddleware Valkey resilience.

PLAN-0093 Phase 5c live chat-eval (2026-05-24) found that Q5/Q6/Q7 all
returned HTTP 503 with 5-13ms latency because a transient Valkey hiccup
mid-run caused ``RateLimitMiddleware`` to fail-closed instantly with no
retry. The chat eval then misattributed RAG failure verdicts to
questions that never even reached S8.

FIX-LIVE-D adds:

1. 1-retry with 50ms backoff on transient (network/timeout) Valkey errors
2. Structured ``valkey_op_failed`` logs with ``valkey_retry_attempt`` field
3. A Prometheus counter ``rate_limiting_unavailable_total`` labelled by
   ``fallback_action`` (``retry_succeeded`` / ``fail_open_after_retry`` /
   ``503_no_retry``) so Grafana can alert on degradation.

F-007 (2026-06-21) amends the policy: an exhausted-retry *transient* error now
FAILS OPEN (200) rather than fail-closed (503). The original FIX-LIVE-D allowlist
listed only the Python builtin ConnectionError/TimeoutError, which do NOT match
redis-py's own ConnectionError/TimeoutError (they inherit from RedisError), so
every real Valkey timeout under load fell into ``503_no_retry`` and 503ed
/v1/quotes. The middleware now (a) classifies the redis exception classes as
transient and (b) fails open on transient errors so a blip never 503s traffic.

These tests use ``AsyncMock`` with ``side_effect`` lists to drive the
retry state machine deterministically. We assert the Prometheus counter
delta (not absolute value) because the counter is a module-level global
that persists across tests in the same process.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_minimal_app() -> FastAPI:
    """Mirror the ``_make_minimal_app`` helper from ``test_middleware.py``.

    A trivial app with a single ``/test`` route is enough — the rate-limit
    middleware only cares about the request path + method, not the handler.
    """
    app = FastAPI()

    @app.get("/test")
    async def test_route() -> dict[str, bool]:
        return {"ok": True}

    return app


def _counter_value(label: str) -> float:
    """Read the current value of ``rate_limiting_unavailable_total{fallback_action=label}``.

    The counter is registered on the global REGISTRY at import time, so we
    fetch it by name. Returns 0.0 if no samples for the label have been
    emitted yet — Prometheus client lazily creates the child series on the
    first ``.inc()`` call.
    """
    collector = REGISTRY._names_to_collectors.get("rate_limiting_unavailable_total")
    if collector is None:
        return 0.0
    # ``Counter.labels(...)._value.get()`` is the documented private path used
    # in the upstream prometheus_client tests. We use it here to avoid having
    # to walk the metric family samples list for one label combination.
    try:
        return float(collector.labels(fallback_action=label)._value.get())
    except Exception:
        return 0.0


# ── Test 1: transient error then success → retry kicks in, returns 200 ────────


@pytest.mark.asyncio
async def test_rate_limit_retry_succeeds_after_transient_failure() -> None:
    """FIX-LIVE-D: first ``incr`` raises ConnectionError, retry succeeds → 200.

    Before this patch, a single transient Valkey hiccup mid-request would
    propagate to a 503. After the patch, the middleware retries once with
    a 50ms backoff and the user request succeeds transparently.
    """
    from api_gateway.middleware import RateLimitMiddleware

    before = _counter_value("retry_succeeded")

    valkey = AsyncMock()
    # First call raises a transient ConnectionError; second succeeds with
    # current=1 (a brand-new window). The ``side_effect`` list is consumed
    # in order — passing a list is the standard AsyncMock pattern for
    # state-machine-style mocks.
    valkey.incr = AsyncMock(side_effect=[ConnectionError("connection reset"), 1])
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")

    # Request succeeded — retry saved us. Before FIX-LIVE-D this was a 503.
    assert resp.status_code == 200, f"expected 200 after retry, got {resp.status_code}"
    # Both incr attempts ran (1 original + 1 retry).
    assert valkey.incr.call_count == 2, f"expected 2 incr attempts (original + retry), got {valkey.incr.call_count}"
    # EXPIRE ran because the retry returned current=1 (new window).
    assert valkey.expire.call_count == 1
    # The retry-success counter incremented by exactly 1.
    after = _counter_value("retry_succeeded")
    assert after - before == pytest.approx(1.0), f"retry_succeeded counter delta expected 1, got {after - before}"


# ── Test 2: transient error twice → FAIL-OPEN (200) + counter increments ──────


@pytest.mark.asyncio
async def test_rate_limit_failopen_after_retry_exhausted() -> None:
    """F-007 (2026-06-21): both attempts raise a transient error → FAIL-OPEN (200).

    This reverses the prior FIX-LIVE-D fail-CLOSED-on-transient policy. Rate
    limiting is a protective control, not a correctness invariant: a sustained
    (or momentary) Valkey blip must NOT 503 every real caller — that was the
    /v1/quotes F-007 symptom. After the retry budget is exhausted on a transient
    error the request is allowed through (200) and the degradation is counted
    under the ``fail_open_after_retry`` label so Grafana can alert on a
    *sustained* open-degradation window.
    """
    from api_gateway.middleware import RateLimitMiddleware

    before = _counter_value("fail_open_after_retry")

    valkey = AsyncMock()
    # Both attempts raise — retry budget exhausted, fail-OPEN kicks in.
    valkey.incr = AsyncMock(
        side_effect=[ConnectionError("conn refused"), ConnectionError("conn refused")],
    )
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")

    assert resp.status_code == 200, f"expected 200 fail-open after exhausted retries, got {resp.status_code}"
    # Both attempts ran — proves the retry loop iterated max_attempts times.
    assert valkey.incr.call_count == 2
    # Counter incremented with the fail-open label (NOT a 503 label).
    after = _counter_value("fail_open_after_retry")
    assert after - before == pytest.approx(1.0), f"fail_open_after_retry counter delta expected 1, got {after - before}"


# ── Test 3: non-transient (auth) error → no retry, 503 + no_retry label ───────


@pytest.mark.asyncio
async def test_rate_limit_no_retry_on_non_transient_error() -> None:
    """FIX-LIVE-D: a non-transient error (auth, programmer bug) skips retry.

    Auth failures and ResponseError won't heal in 50ms — retrying just burns
    CPU and delays the 503. The middleware fails fast and labels the counter
    ``503_no_retry`` so operators can tell apart "Valkey is misconfigured"
    from "Valkey is flapping".
    """
    from api_gateway.middleware import RateLimitMiddleware

    before = _counter_value("503_no_retry")

    valkey = AsyncMock()
    # A generic Exception subclass that is NOT in _VALKEY_TRANSIENT_EXCEPTIONS.
    # This simulates an auth error (redis.exceptions.AuthenticationError) or a
    # schema/programmer bug — any non-network failure.
    valkey.incr = AsyncMock(side_effect=RuntimeError("NOAUTH Authentication required"))
    valkey.expire = AsyncMock()

    app = _make_minimal_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=100,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/test")

    assert resp.status_code == 503, f"expected 503 on non-transient error, got {resp.status_code}"
    # CRITICAL: only ONE incr call — the retry was skipped because the
    # exception isn't in the transient-class allowlist.
    assert valkey.incr.call_count == 1, f"expected 1 incr (no retry on non-transient), got {valkey.incr.call_count}"
    # Counter labelled "503_no_retry" — distinct from the "after_retry" label.
    after = _counter_value("503_no_retry")
    assert after - before == pytest.approx(1.0), f"503_no_retry counter delta expected 1, got {after - before}"
