"""Observability wiring tests for market-data (PLAN-0003 T-B-2-02)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from market_data.app import RequestIdMiddleware, create_app
from starlette.middleware.base import BaseHTTPMiddleware

pytestmark = pytest.mark.unit


@pytest.fixture
def obs_app():
    return create_app()


@pytest.fixture
async def obs_client(obs_app):
    transport = ASGITransport(app=obs_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_request_id_middleware_registered(obs_app) -> None:
    """RequestIdMiddleware should be registered on the app."""
    middleware_classes = [m.cls for m in obs_app.user_middleware if hasattr(m, "cls")]
    assert RequestIdMiddleware in middleware_classes


def test_request_id_middleware_is_pure_asgi() -> None:
    """RequestIdMiddleware must be a pure-ASGI middleware, NOT BaseHTTPMiddleware.

    BP-720 amplifier fix: BaseHTTPMiddleware runs the app in a separate anyio
    task, which breaks client-cancellation propagation and leaks DB connections
    from yield-style dependencies. The pure-ASGI form has a 3-arg __call__ and
    does not subclass BaseHTTPMiddleware.
    """
    assert not issubclass(RequestIdMiddleware, BaseHTTPMiddleware)
    # Pure-ASGI contract: constructed with a single ASGI app, callable with
    # (scope, receive, send).
    call = RequestIdMiddleware.__call__
    assert call.__code__.co_argcount == 4  # self, scope, receive, send


async def test_request_id_generated_when_missing(obs_client) -> None:
    """Missing X-Request-ID should be generated."""
    response = await obs_client.get("/healthz")
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


async def test_request_id_preserved_when_present(obs_client) -> None:
    """Existing X-Request-ID should be echoed back."""
    custom_id = "test-market-data-req-id"
    response = await obs_client.get("/healthz", headers={"X-Request-ID": custom_id})
    assert response.headers["x-request-id"] == custom_id


# ── Pure-ASGI middleware unit tests (BP-720 amplifier) ──────────────────────────


async def test_request_id_header_injected_on_response_start() -> None:
    """The middleware injects X-Request-ID on the http.response.start frame."""
    captured: dict[str, list] = {}

    async def inner_app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = RequestIdMiddleware(inner_app)
    scope = {"type": "http", "headers": [(b"x-request-id", b"abc-123")]}

    async def receive():
        return {"type": "http.request"}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured["headers"] = message["headers"]

    await mw(scope, receive, send)
    hdrs = {k.decode(): v.decode() for k, v in captured["headers"]}
    assert hdrs["x-request-id"] == "abc-123"


async def test_request_id_generated_for_invalid_header() -> None:
    """A malformed X-Request-ID is replaced with a fresh ULID."""
    captured: dict[str, list] = {}

    async def inner_app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})

    mw = RequestIdMiddleware(inner_app)
    # Contains a slash → fails _VALID_REQUEST_ID_RE → regenerated.
    scope = {"type": "http", "headers": [(b"x-request-id", b"bad/id")]}

    async def receive():
        return {"type": "http.request"}

    async def send(message) -> None:
        if message["type"] == "http.response.start":
            captured["headers"] = message["headers"]

    await mw(scope, receive, send)
    hdrs = {k.decode(): v.decode() for k, v in captured["headers"]}
    assert hdrs["x-request-id"] != "bad/id"
    assert len(hdrs["x-request-id"]) > 0


async def test_request_id_passthrough_for_non_http_scope() -> None:
    """Non-HTTP scopes (websocket/lifespan) are passed through untouched."""
    called: dict[str, str] = {}

    async def inner_app(scope, receive, send) -> None:
        called["type"] = scope["type"]

    mw = RequestIdMiddleware(inner_app)
    await mw({"type": "lifespan"}, None, None)  # type: ignore[arg-type]
    assert called["type"] == "lifespan"


async def test_cancellation_drives_inner_teardown_in_loop() -> None:
    """A cancelled request runs the downstream teardown in-loop (BP-720).

    This is the crux of the fix: a pure-ASGI middleware propagates client
    cancellation directly into the app coroutine, so a yield-style DB dependency
    (``get_read_uow``) can run its ``async with`` ``__aexit__`` and return the
    connection instead of orphaning it. BaseHTTPMiddleware ran the app in a
    separate task, breaking this.
    """
    import asyncio

    teardown_ran = False

    async def inner_app(scope, receive, send) -> None:
        nonlocal teardown_ran
        try:
            await asyncio.sleep(10)  # simulate a slow read the client abandons
        finally:
            teardown_ran = True  # mirrors the yield-dependency teardown

    mw = RequestIdMiddleware(inner_app)
    scope = {"type": "http", "headers": []}

    async def receive():
        return {"type": "http.request"}

    async def send(message) -> None:
        return None

    task = asyncio.create_task(mw(scope, receive, send))
    await asyncio.sleep(0.01)  # let the task reach the sleep
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert teardown_ran, "inner teardown must run in-loop on client cancellation"
