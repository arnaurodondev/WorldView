"""Shared test fixtures for rag-chat service.

Unit tests use the full app created by create_app() with InternalJWTMiddleware included.
``internal_jwt_skip_verification=True`` is set so that when public_key is None (JWKS server
not running in unit tests), the middleware still decodes tokens without signature verification.
The default ``client`` fixture injects a system JWT via X-Internal-JWT header (BP-134 fix).

BP-435 (2026-05-08): sse_starlette AppStatus.should_exit_event is a class-level singleton
that stores an anyio.Event() bound to the first event loop that calls it. Subsequent tests
that run on a different asyncio event loop raise RuntimeError("bound to a different event
loop"). Fix: reset AppStatus.should_exit_event to None before each test so it is
lazily re-created on the current test's event loop.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

# PLAN-0093 T-A-1-03: the new observability.assert_app_env_or_die() boot guard
# aborts startup when ``internal_jwt_skip_verification=True`` and APP_ENV is
# unset.  Several tests enable skip_verification — pin APP_ENV here BEFORE any
# settings/create_app() import so the import-time module-level Settings() in
# config.py does not trip the existing pydantic validator either.
os.environ.setdefault("APP_ENV", "test")

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry


@pytest.fixture(autouse=True)
def _reset_sse_starlette_app_status() -> None:
    """Reset sse_starlette AppStatus.should_exit_event before each test.

    WHY: AppStatus.should_exit_event is a class-level singleton that is lazily
    initialised to anyio.Event() the first time an SSE stream awaits disconnect.
    Once bound to an event loop it cannot be used in a different event loop.
    pytest-asyncio creates a NEW function-scoped event loop for each async test,
    so the stale event from the previous test raises:
      RuntimeError: <asyncio.locks.Event object> is bound to a different event loop
    Resetting to None before each test forces lazy re-creation on the current loop.
    (BP-435)
    """
    try:
        from sse_starlette.sse import AppStatus

        AppStatus.should_exit_event = None
        AppStatus.should_exit = False
    except ImportError:
        pass  # sse_starlette not installed; nothing to reset


def _make_system_jwt() -> str:
    """HS256 JWT with role=system for unit tests.

    InternalJWTMiddleware decodes without signature verification when public_key is None
    (JWKS server not running in unit test environment).
    """
    payload = {
        "iss": "worldview-gateway",
        "sub": "unit-test-system",
        "tenant_id": "",
        "role": "system",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "unit-test-secret", algorithm="HS256")


_SYSTEM_JWT = _make_system_jwt()
_INTERNAL_HEADERS: dict[str, str] = {"X-Internal-JWT": _SYSTEM_JWT}


@pytest.fixture
def settings() -> RagChatSettings:
    """Minimal settings suitable for unit tests (no real infra required)."""
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        log_json=False,
        log_level="WARNING",
        # WARNING: TEST-ONLY. Never use skip_verification in integration/e2e against real services.
        internal_jwt_skip_verification=True,
    )


@pytest.fixture
def app(settings: RagChatSettings):  # type: ignore[return]
    return create_app(settings)


@pytest.fixture
async def client(app):  # type: ignore[return]
    """Authenticated client with X-Internal-JWT header (system role)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=_INTERNAL_HEADERS) as ac:
        yield ac


@pytest.fixture
async def unauthenticated_client(app):  # type: ignore[return]
    """Client without X-Internal-JWT — used to test InternalJWTMiddleware 401 behaviour."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> CollectorRegistry:
    """Provide an isolated Prometheus CollectorRegistry for tests.

    QA-008 (BP-425): tests that assert on Prometheus metrics must use an isolated
    registry to prevent cross-test gauge contamination from the shared global REGISTRY.
    """
    import prometheus_client
    from prometheus_client import CollectorRegistry

    registry = CollectorRegistry()
    monkeypatch.setattr(prometheus_client, "REGISTRY", registry)
    return registry
