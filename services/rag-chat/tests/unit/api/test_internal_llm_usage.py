"""Unit tests for POST /internal/v1/llm-usage (PLAN-0117 W4, T-A-4-02, FR-6).

Covers: happy path persists + 200 {"recorded": true}; best-effort persistence
failure → 200 {"recorded": false} (never 5xx, NFR-1); non-internal caller → 401;
invalid body → 422. The DB session is faked; the repository is patched so no
live Postgres is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000030")
_USER_ID = UUID("00000000-0000-0000-0000-000000000031")
_INTERNAL_JWT = _jwt.encode(
    {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
    "secret",
    algorithm="HS256",
)
_AUTH_HEADERS = {"X-Internal-JWT": _INTERNAL_JWT}

_VALID_BODY = {
    "model_id": "meta-llama/Meta-Llama-3.1-8B-Instruct",
    "provider": "deepinfra",
    "capability": "screener_nl_translate",
    "tokens_in": 120,
    "tokens_out": 40,
    "estimated_cost_usd": "0.00000041",
    "cost_source": "provider",
}


@pytest.fixture
def settings() -> RagChatSettings:
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        log_json=False,
        log_level="WARNING",
        internal_jwt_skip_verification=True,
    )


def _fake_write_factory(commit_raises: bool = False) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock(side_effect=RuntimeError("db down") if commit_raises else None)
    session.close = AsyncMock()
    # Expose the single session instance so tests can inspect the bind params.
    factory = MagicMock(return_value=session)
    factory.session = session
    return factory


@pytest.fixture
def authed_app(settings: RagChatSettings):  # type: ignore[return]
    from rag_chat.api.dependencies import get_auth_context

    app = create_app(settings)
    app.state.write_factory = _fake_write_factory()

    async def _override_auth() -> tuple[UUID, UUID]:
        return (_TENANT_ID, _USER_ID)

    app.dependency_overrides[get_auth_context] = _override_auth
    return app


async def test_ingest_persists_and_returns_recorded_true(authed_app) -> None:
    """Valid POST → INSERT executed + committed, 200 {"recorded": true}."""
    async with AsyncClient(transport=ASGITransport(app=authed_app), base_url="http://test") as client:
        resp = await client.post("/internal/v1/llm-usage", json=_VALID_BODY, headers=_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"recorded": True}
    session = authed_app.state.write_factory.session
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()
    # The INSERT bind params carry provenance + JWT-fallback identity.
    params = session.execute.await_args.args[1]
    assert params["capability"] == "screener_nl_translate"
    assert params["cost_source"] == "provider"
    # Body omitted tenant/user → falls back to JWT identity (never orphaned).
    assert params["user_id"] == str(_USER_ID)
    assert params["tenant_id"] == str(_TENANT_ID)


async def test_ingest_best_effort_on_persistence_error(authed_app) -> None:
    """Persistence failure → 200 {"recorded": false}, no raise (NFR-1)."""
    authed_app.state.write_factory = _fake_write_factory(commit_raises=True)
    async with AsyncClient(transport=ASGITransport(app=authed_app), base_url="http://test") as client:
        resp = await client.post("/internal/v1/llm-usage", json=_VALID_BODY, headers=_AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == {"recorded": False}


async def test_ingest_rejects_non_internal(settings: RagChatSettings) -> None:
    """No internal JWT → 401 (InternalJWTMiddleware rejects before the route)."""
    app = create_app(settings)
    app.state.write_factory = _fake_write_factory()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/internal/v1/llm-usage", json=_VALID_BODY)  # no header
    assert resp.status_code == 401


async def test_ingest_validates_body(authed_app) -> None:
    """Missing required fields → 422."""
    async with AsyncClient(transport=ASGITransport(app=authed_app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/v1/llm-usage",
            json={"model_id": "m"},  # missing provider/capability/cost fields
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 422
