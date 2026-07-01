"""Unit tests for PLAN-0094 W1 / T-W1-02 — env-driven rate-limit sub-tiers.

Wave W1 of PLAN-0094 replaces three hard-coded rate-limit literals
(``_FINANCIAL_MUTATION_LIMIT = 20``, the IP-feedback ``120``, and the
unauthenticated ``20``) with constructor-injected values sourced from
``Settings``. These tests pin the contract:

    1. The constructor accepts the three keyword-only sub-tier limits.
    2. Each limit is honoured at request-time (429 fires once exceeded).
    3. The default for the general authenticated bucket is now ``2000``.

The fixtures mirror the existing ``test_middleware.py`` style: a minimal
FastAPI app with a single ``/test`` route, an ``AsyncMock`` Valkey that
mimics ``INCR`` counter semantics, and an optional ``InjectUserMiddleware``
when the test needs the authenticated bucket. ``AsyncMock(side_effect=...)``
with a counter dict lets us drive the rate-limit ``current`` value
deterministically across N requests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unit


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_app() -> FastAPI:
    """Minimal app with routes covering each bucket the middleware can pick.

    We expose ``/test`` (generic), ``/v1/transactions`` (financial-mutation
    when method is POST), and ``/v1/feedback/x`` (public-feedback IP bucket).
    The rate-limit middleware never looks at the response body — only the
    request path + method + ``request.state.user`` — so the handlers can
    return any 200 payload.
    """
    app = FastAPI()

    @app.get("/test")
    async def test_route() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/v1/transactions")
    async def post_tx() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/feedback/x")
    async def feedback() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/v1/portfolios/export")
    async def export_csv() -> dict[str, bool]:
        return {"ok": True}

    return app


def _make_counting_valkey() -> AsyncMock:
    """AsyncMock Valkey whose ``incr`` returns 1, 2, 3, … in call order.

    The middleware reads the returned int and compares against ``limit``;
    the per-window counter semantics of real Valkey ``INCR`` are exactly
    that. ``expire`` is a no-op so we don't fight TTL bookkeeping in tests.
    """
    valkey = AsyncMock()
    counter = {"n": 0}

    async def fake_incr(key: str) -> int:
        counter["n"] += 1
        return counter["n"]

    valkey.incr = fake_incr
    valkey.expire = AsyncMock()
    return valkey


class _InjectUserMiddleware(BaseHTTPMiddleware):
    """Helper middleware that stamps a fixed user dict on every request.

    Used by the financial-mutation test below — the financial-mutation bucket
    only fires when the rate-limit middleware sees an authenticated user
    (otherwise it would fall through to the IP bucket). The user dict shape
    matches what ``OIDCAuthMiddleware`` produces in production.
    """

    async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
        request.state.user = {"user_id": "u-fin-tester", "tenant_id": "t-1"}
        return await call_next(request)


# ── T-W1-02 tests: each sub-tier limit reads from the constructor ─────────────


@pytest.mark.asyncio
async def test_financial_mutation_limit_reads_from_constructor() -> None:
    """T-W1-02: ``financial_mutation_limit=5`` → 6th POST /v1/transactions = 429.

    Before PLAN-0094 W1 the financial-mutation cap was a module-level
    constant; this test pins the new constructor contract by passing 5 and
    asserting the 429 fires on the 6th request, never earlier.
    """
    from api_gateway.middleware import RateLimitMiddleware

    valkey = _make_counting_valkey()

    app = _make_app()
    # last-added = outermost → RateLimit runs AFTER InjectUser so it sees the
    # stamped user dict and routes the request into the financial-mutation
    # bucket. Order matters: swap them and the test would 429 on the IP
    # bucket (limit=20) instead of the financial-mutation bucket (limit=5).
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=2000,
        financial_mutation_limit=5,
        unauthenticated_limit=20,
        public_feedback_limit=120,
    )
    app.add_middleware(_InjectUserMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = [(await client.post("/v1/transactions")).status_code for _ in range(6)]

    # First 5 requests = under the cap. 6th = the cap exceeded, 429 fires.
    # ``status == 429`` is asserted on the LAST request only — the previous
    # five must all be 200. A single 429 earlier in the list would mean the
    # middleware is double-counting or the constructor wiring is wrong.
    assert statuses[:5] == [200] * 5, f"expected 5x200 then 429, got {statuses}"
    assert statuses[5] == 429, f"expected 429 on 6th request, got {statuses[5]}"


@pytest.mark.asyncio
async def test_unauthenticated_limit_reads_from_constructor() -> None:
    """T-W1-02: ``unauthenticated_limit=3`` → 4th unauth request = 429.

    No user is stamped on the request, so the middleware falls through to
    the IP bucket. With the cap at 3, the 4th call must 429.
    """
    from api_gateway.middleware import RateLimitMiddleware

    valkey = _make_counting_valkey()

    app = _make_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=2000,
        financial_mutation_limit=20,
        unauthenticated_limit=3,
        public_feedback_limit=120,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = [(await client.get("/test")).status_code for _ in range(4)]

    assert statuses[:3] == [200, 200, 200], f"expected 3x200, got {statuses}"
    assert statuses[3] == 429, f"expected 429 on 4th request, got {statuses[3]}"


@pytest.mark.asyncio
async def test_public_feedback_limit_reads_from_constructor() -> None:
    """T-W1-02: ``public_feedback_limit=2`` → 3rd /v1/feedback/* = 429.

    Public-feedback paths get a separate IP bucket (key prefix ``rl:v1:ip-fb:``)
    that does NOT share the unauthenticated bucket — proven by setting
    ``unauthenticated_limit=20`` while ``public_feedback_limit=2``. If the
    middleware ever routed feedback into the unauth bucket the 3rd request
    would be a 200, not a 429.
    """
    from api_gateway.middleware import RateLimitMiddleware

    valkey = _make_counting_valkey()

    app = _make_app()
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=2000,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=2,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = [(await client.get("/v1/feedback/x")).status_code for _ in range(3)]

    assert statuses[:2] == [200, 200], f"expected 2x200 then 429, got {statuses}"
    assert statuses[2] == 429, f"expected 429 on 3rd request, got {statuses[2]}"


@pytest.mark.asyncio
async def test_export_tier_uses_daily_window_and_limit() -> None:
    """Export tier: 1/day limit + its OWN (daily) Valkey window.

    Export endpoints (GET /*/export) are a heavy full-table CSV scan and a
    data-harvesting surface, so they get a dedicated bucket limited per DAY,
    not per minute. This pins two things at once:
      1. ``export_limit=1`` → the 2nd export in the window is a 429.
      2. the export bucket's TTL is ``export_window_seconds`` (86400), NOT the
         shared 60s ``window_seconds`` — otherwise "1 per day" would silently
         reset every minute and the cap would be meaningless.
    """
    from api_gateway.middleware import RateLimitMiddleware

    valkey = _make_counting_valkey()

    app = _make_app()
    # RateLimit added last (outermost) so it runs after InjectUser and sees an
    # authenticated user — the export bucket is a per-user tier, so without a
    # user the request would fall through to the IP bucket instead.
    app.add_middleware(
        RateLimitMiddleware,
        valkey_client=valkey,
        max_requests=2000,
        financial_mutation_limit=20,
        unauthenticated_limit=20,
        public_feedback_limit=120,
        export_limit=1,
        export_window_seconds=86400,
    )
    app.add_middleware(_InjectUserMiddleware)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        statuses = [(await client.get("/v1/portfolios/export")).status_code for _ in range(2)]

    assert statuses[0] == 200, f"first export should pass, got {statuses}"
    assert statuses[1] == 429, f"second export should 429 (1/day cap), got {statuses}"
    # The export bucket must TTL over a DAY, not 60s. ``expire`` is called with
    # ``(key, window)`` when the counter is first created (current == 1).
    assert valkey.expire.await_count >= 1, "expire must be set on the fresh export key"
    key, window = valkey.expire.await_args_list[0].args
    assert window == 86400, f"export bucket must use the daily window, got {window}s"
    assert key.startswith("rl:v1:export:"), f"expected export bucket key, got {key}"


def test_default_export_limit_is_one_per_day() -> None:
    """The env-driven export tier defaults to 1 request / 86400s (1 per day)."""
    from api_gateway.config import Settings

    assert Settings.model_fields["rate_limit_export_requests"].default == 1
    assert Settings.model_fields["rate_limit_export_window_seconds"].default == 86400


def test_default_user_bucket_is_2000() -> None:
    """T-W1-01: ``Settings().rate_limit_requests`` defaults to 2000.

    PLAN-0094 W1 bumps the authenticated default from 1000 → 2000 because
    multi-panel workspaces routinely burst past 1000/min during normal use.
    The check uses ``Settings.model_construct(...)`` to skip env-var loading
    (production ``.env`` files may override the default) and inspect the
    field default value pinned by the class.
    """
    from api_gateway.config import Settings

    # ``model_fields`` exposes the FieldInfo for each field including the
    # declared default. We read it directly instead of instantiating
    # ``Settings()`` because instantiating requires the no-default OIDC
    # fields (issuer, client_id, …) to be set, and that's noise here.
    assert Settings.model_fields["rate_limit_requests"].default == 2000
