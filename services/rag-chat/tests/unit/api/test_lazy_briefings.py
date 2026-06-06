"""Unit tests for POST /api/v1/briefings/instrument/{entity_id}/generate (W5-B-6).

Covers T-S8-05 — lazy-generate endpoint:
  - Cache hit → 200 + status="cached" (skips UC call)
  - Cache miss + rate limit not exceeded → 202 + status="queued"
  - Rate limit exceeded (>60/hr) → 429 + Retry-After header
  - UC raises ProviderUnavailableError → 503
  - UC raises EntityNotFoundError → 404
  - Valkey unavailable → fail-open (generation proceeds)
  - Cache key uses entity_id only (no user_id suffix, Δ12)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from fastapi import FastAPI
from rag_chat.api.schemas import PublicBriefingResponse
from rag_chat.app import create_app
from rag_chat.domain.errors import EntityNotFoundError, ProviderUnavailableError
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_ENTITY_ID = "ent-00000000-0000-0000-0000-000000000001"
_USER_ID = "00000000-0000-0000-0000-000000000099"
_TENANT_ID = "00000000-0000-0000-0000-000000000088"

# Minimal UC result that matches what execute_public_instrument returns.
_UC_RESULT = {
    "content": "AAPL is trading near all-time highs.",
    "risk_summary": {"concentration_score": 0.2},
    "citations": [],
    "generated_at": "2026-05-21T12:00:00+00:00",
    "confidence": 0.9,
    "lead": "Apple Inc. momentum continues.",
    "sections": [],
}

# JWT token for X-Internal-JWT header (skip_verification=True in unit tests).
_JWT_TOKEN = _jwt.encode(
    {"sub": _USER_ID, "tenant_id": _TENANT_ID, "user_id": _USER_ID, "role": "user"},
    "secret",
    algorithm="HS256",
)
_JWT_HEADERS = {"X-Internal-JWT": _JWT_TOKEN}


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def settings() -> RagChatSettings:
    """Minimal settings for unit tests — no real infra required."""
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="s1-token",
        log_json=False,
        log_level="WARNING",
        internal_jwt_skip_verification=True,
    )


def _make_app(
    settings: RagChatSettings,
    uc_result: dict | Exception | None = None,  # type: ignore[type-arg]
    valkey_get_result: bytes | None = None,
    valkey_incr_count: int = 1,
    valkey_available: bool = True,
) -> FastAPI:
    """Create test app with mocked briefing UC and Valkey client.

    Args:
        settings: Settings with skip_verification=True.
        uc_result: If Exception, UC raises it; otherwise used as execute_public_instrument return.
        valkey_get_result: If set, Valkey.get() returns this (cache hit).
        valkey_incr_count: Valkey.incr() return value (rate-limit counter).
        valkey_available: If False, Valkey raises ConnectionError (fail-open test).
    """
    app = create_app(settings)

    # ── Mock briefing UC ──────────────────────────────────────────────────────
    mock_uc = MagicMock()
    result = uc_result if uc_result is not None else _UC_RESULT
    if isinstance(result, Exception):
        mock_uc.execute_public_instrument = AsyncMock(side_effect=result)
        mock_uc.execute_public_morning = AsyncMock(side_effect=result)
        mock_uc.execute = AsyncMock(side_effect=result)
    else:
        mock_uc.execute_public_instrument = AsyncMock(return_value=result)
        mock_uc.execute_public_morning = AsyncMock(return_value=result)
        mock_uc.execute = AsyncMock(return_value=result)
    app.state.briefing_uc = mock_uc
    app.state.chat_orchestrator = MagicMock()

    # ── Mock Valkey ───────────────────────────────────────────────────────────
    mock_valkey = AsyncMock()
    if not valkey_available:
        err = ConnectionError("Valkey unavailable")
        mock_valkey.get = AsyncMock(side_effect=err)
        mock_valkey.incr = AsyncMock(side_effect=err)
        mock_valkey.expire = AsyncMock(side_effect=err)
        mock_valkey.set = AsyncMock(side_effect=err)
    else:
        mock_valkey.get = AsyncMock(return_value=valkey_get_result)
        mock_valkey.incr = AsyncMock(return_value=valkey_incr_count)
        mock_valkey.expire = AsyncMock()
        mock_valkey.set = AsyncMock()
    app.state.valkey = mock_valkey

    return app


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_cache_hit_returns_200(settings: RagChatSettings) -> None:
    """When Valkey has a cached brief, POST returns 200 + status='cached' without calling the UC."""
    # Build a valid cached PublicBriefingResponse blob.
    cached_resp = PublicBriefingResponse(
        narrative="Cached instrument brief.",
        generated_at="2026-05-21T08:00:00+00:00",
        entity_id=_ENTITY_ID,
        cached=True,
    )
    app = _make_app(settings, valkey_get_result=cached_resp.model_dump_json().encode("utf-8"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "cached"
    assert payload["entity_id"] == _ENTITY_ID
    # UC must NOT be called when cache is warm.
    app.state.briefing_uc.execute_public_instrument.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_cache_miss_returns_202(settings: RagChatSettings) -> None:
    """On cache miss, UC is called and response is 202 + status='queued'."""
    app = _make_app(settings, valkey_get_result=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 202
    payload = resp.json()
    assert payload["status"] == "queued"
    assert payload["entity_id"] == _ENTITY_ID
    assert payload["brief_id"] is None
    app.state.briefing_uc.execute_public_instrument.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_writes_cache_after_generation(settings: RagChatSettings) -> None:
    """After generation, the new brief is cached in Valkey with 24h TTL."""
    app = _make_app(settings, valkey_get_result=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            headers=_JWT_HEADERS,
        )

    # Valkey.set must have been called with the correct cache key and 24h TTL.
    app.state.valkey.set.assert_awaited_once()
    call_args = app.state.valkey.set.call_args
    # WHY entity-only cache key (Δ12): dropping :user_id suffix means all users
    # share the same cached brief per instrument, saving LLM calls.
    cache_key_arg = call_args.args[0] if call_args.args else call_args.kwargs.get("key", "")
    assert f"v2:{_ENTITY_ID}" in cache_key_arg
    # Must NOT include a user_id in the key (Δ12).
    assert _USER_ID not in cache_key_arg
    # 24h TTL.
    assert call_args.kwargs.get("ex") == 86400


@pytest.mark.asyncio
async def test_generate_rate_limit_exceeded_returns_429(settings: RagChatSettings) -> None:
    """When the per-user hourly counter exceeds 60, returns 429 + Retry-After."""
    # Simulate the INCR counter returning 61 (one over the limit).
    app = _make_app(settings, valkey_get_result=None, valkey_incr_count=61)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 429
    # Retry-After header must be present.
    assert "retry-after" in resp.headers
    retry_after = int(resp.headers["retry-after"])
    # Must be between 0 and 3600 (one clock hour).
    assert 0 < retry_after <= 3600
    # UC must NOT be called when rate-limited.
    app.state.briefing_uc.execute_public_instrument.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_provider_unavailable_returns_503(settings: RagChatSettings) -> None:
    """When the UC raises ProviderUnavailableError, returns 503."""
    app = _make_app(settings, uc_result=ProviderUnavailableError("LLM offline"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_generate_entity_not_found_returns_404(settings: RagChatSettings) -> None:
    """When the UC raises EntityNotFoundError, returns 404."""
    app = _make_app(settings, uc_result=EntityNotFoundError("Entity not found"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_valkey_down_failopen(settings: RagChatSettings) -> None:
    """When Valkey is unavailable, the endpoint fails-open and still generates (202)."""
    app = _make_app(settings, valkey_available=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            headers=_JWT_HEADERS,
        )

    # Endpoint must not crash — it should still attempt generation.
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["status"] == "queued"
    app.state.briefing_uc.execute_public_instrument.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_requires_auth(settings: RagChatSettings) -> None:
    """POST without X-Internal-JWT header returns 401 (InternalJWTMiddleware)."""
    app = _make_app(settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/briefings/instrument/{_ENTITY_ID}/generate",
            # No X-Internal-JWT header.
        )

    assert resp.status_code == 401
