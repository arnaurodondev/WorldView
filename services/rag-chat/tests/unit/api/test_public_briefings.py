"""Unit tests for GET /api/v1/briefings/* (PLAN-0029 T-2-01).

Tests follow the same pattern as ``test_briefings.py``: create the app via
``create_app()`` with ``internal_jwt_skip_verification=True``, mock the
briefing use case and Valkey client, and send HTTP requests via ``httpx.AsyncClient``.

InternalJWTMiddleware has no public key in unit tests (no lifespan), so it
decodes JWTs without signature verification when ``skip_verification=True``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_USER_ID = UUID("00000000-0000-0000-0000-000000000099")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000088")

# Mock return value from GenerateBriefingUseCase.execute() (email path)
_BRIEFING_RESULT = {
    "narrative": "Market overview for today.",
    "risk_summary": {"concentration_score": 0.0},
    "citations": [],
    "generated_at": "2026-04-19T12:00:00+00:00",
}

# Mock return value from GenerateBriefingUseCase.execute_public_morning()
# NOTE: execute_public_morning() returns 'content' (not 'narrative') — the route
# maps content → narrative when building the PublicBriefingResponse.
_MORNING_RESULT = {
    "content": "Morning market overview for today.",
    "risk_summary": {"concentration_score": 0.0},
    "entity_mentions": [],
    "citations": [],
    "generated_at": "2026-04-19T12:00:00+00:00",
}

# JWT token for authenticated requests — decoded without verification in unit tests
_JWT_TOKEN = _jwt.encode(
    {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
    "secret",
    algorithm="HS256",
)
_JWT_HEADERS = {"X-Internal-JWT": _JWT_TOKEN}


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
    valkey_get_result: str | bytes | None = None,
) -> object:
    """Create test app with mocked briefing UC and Valkey client.

    Args:
        settings: Service settings with skip_verification=True.
        uc_result: If an Exception, mock UC raises it; otherwise mock returns it.
        valkey_get_result: If set, mock Valkey.get() returns this value (cache hit).
    """
    app = create_app(settings)

    # Mock the GenerateBriefingUseCase — all three UC methods must be AsyncMock:
    # - execute_public_morning(): called by GET /api/v1/briefings/morning
    # - execute_public_instrument(): called by GET /api/v1/briefings/instrument/{id}
    # - execute(): kept for completeness (email briefing path, not called by public routes)
    mock_uc = MagicMock()
    if isinstance(uc_result, Exception):
        mock_uc.execute = AsyncMock(side_effect=uc_result)
        mock_uc.execute_public_morning = AsyncMock(side_effect=uc_result)
        mock_uc.execute_public_instrument = AsyncMock(side_effect=uc_result)
    else:
        instrument_result = uc_result or _BRIEFING_RESULT
        mock_uc.execute = AsyncMock(return_value=instrument_result)
        mock_uc.execute_public_morning = AsyncMock(return_value=_MORNING_RESULT)
        mock_uc.execute_public_instrument = AsyncMock(return_value=instrument_result)

    app.state.briefing_uc = mock_uc
    # chat_orchestrator is not used by briefing routes — set a dummy to avoid attr errors
    app.state.chat_orchestrator = MagicMock()

    # Mock the Valkey client
    mock_valkey = MagicMock()
    if valkey_get_result is not None:
        mock_valkey.get = AsyncMock(return_value=valkey_get_result)
    else:
        mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    app.state.valkey = mock_valkey

    return app


# ── Morning briefing — happy path ─────────────────────────────────────────────


async def test_morning_briefing_returns_200(settings: RagChatSettings) -> None:
    """Valid JWT -> 200 with narrative, cached=False (cache miss -> generate)."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert "narrative" in body
    assert body["cached"] is False
    assert body["entity_id"] is None


async def test_morning_briefing_calls_use_case(settings: RagChatSettings) -> None:
    """Verify execute_public_morning() is called (not execute()) on cache miss.

    The morning route now calls execute_public_morning(user_id, tenant_id, internal_jwt)
    which uses BriefingContextGatherer to assemble context from upstream services.
    The old execute() (email brief path) must NOT be called by this route.
    """
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    # execute_public_morning must be called exactly once
    app.state.briefing_uc.execute_public_morning.assert_awaited_once()
    # execute() (email path) must NOT be called by the morning route
    app.state.briefing_uc.execute.assert_not_awaited()


async def test_morning_briefing_writes_cache(settings: RagChatSettings) -> None:
    """After generating, the result is written to Valkey with 24h TTL."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    # Valkey.set should have been called with the cache key and 24h TTL
    app.state.valkey.set.assert_awaited_once()
    call_args = app.state.valkey.set.call_args
    assert call_args.kwargs.get("ex") == 86400


# ── Morning briefing — cached ─────────────────────────────────────────────────


async def test_morning_briefing_cached(settings: RagChatSettings) -> None:
    """When Valkey returns cached data, the response has cached=True and skips UC."""
    cached_data = json.dumps(
        {
            "narrative": "Cached morning brief.",
            "risk_summary": {},
            "citations": [],
            "generated_at": "2026-04-19T08:00:00+00:00",
            "cached": False,
            "entity_id": None,
        }
    )
    app = _make_app(settings, valkey_get_result=cached_data)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is True
    assert body["narrative"] == "Cached morning brief."
    # Use case should NOT have been called (cache hit)
    app.state.briefing_uc.execute.assert_not_awaited()


async def test_morning_briefing_cached_bytes(settings: RagChatSettings) -> None:
    """Valkey may return bytes — verify decoding works correctly."""
    cached_data = json.dumps(
        {
            "narrative": "Bytes cached brief.",
            "risk_summary": {},
            "citations": [],
            "generated_at": "2026-04-19T08:00:00+00:00",
            "cached": False,
            "entity_id": None,
        }
    ).encode("utf-8")
    app = _make_app(settings, valkey_get_result=cached_data)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["narrative"] == "Bytes cached brief."
    assert resp.json()["cached"] is True


# ── Morning briefing — auth ───────────────────────────────────────────────────


async def test_morning_briefing_requires_auth(settings: RagChatSettings) -> None:
    """No X-Internal-JWT header -> 401 (enforced by InternalJWTMiddleware)."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning")
    assert resp.status_code == 401


# ── Morning briefing — error handling ─────────────────────────────────────────


async def test_morning_briefing_generation_failure_503(settings: RagChatSettings) -> None:
    """ProviderUnavailableError from UC -> 503."""
    from rag_chat.domain.errors import ProviderUnavailableError

    app = _make_app(settings, uc_result=ProviderUnavailableError("All down"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 503


async def test_morning_briefing_rate_limit_429(settings: RagChatSettings) -> None:
    """RateLimitExceededError from UC -> 429."""
    from rag_chat.domain.errors import RateLimitExceededError

    app = _make_app(settings, uc_result=RateLimitExceededError("Too many briefings"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 429


async def test_morning_briefing_unexpected_error_503(settings: RagChatSettings) -> None:
    """Unexpected exception from UC -> 503 (catch-all)."""
    app = _make_app(settings, uc_result=RuntimeError("Unexpected boom"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 503


# ── Instrument briefing — happy path ──────────────────────────────────────────


async def test_instrument_briefing_returns_200(settings: RagChatSettings) -> None:
    """Valid JWT + entity_id -> 200 with entity_id in response."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/instrument/entity-123", headers=_JWT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["entity_id"] == "entity-123"
    assert body["cached"] is False


async def test_instrument_briefing_calls_use_case_with_entity(settings: RagChatSettings) -> None:
    """Verify the UC receives entity_id via execute_public_instrument().

    The instrument briefing route calls execute_public_instrument(entity_id=...)
    (not execute()) — it delegates entity-focused context gathering to the UC.
    """
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/briefings/instrument/my-entity", headers=_JWT_HEADERS)
    call_kwargs = app.state.briefing_uc.execute_public_instrument.call_args.kwargs
    assert call_kwargs["entity_id"] == "my-entity"


# ── Instrument briefing — cached ──────────────────────────────────────────────


async def test_instrument_briefing_cached(settings: RagChatSettings) -> None:
    """Cached instrument briefing returns cached=True and correct entity_id."""
    cached_data = json.dumps(
        {
            "narrative": "Cached instrument brief.",
            "risk_summary": {},
            "citations": [],
            "generated_at": "2026-04-19T08:00:00+00:00",
            "cached": False,
            "entity_id": "entity-456",
        }
    )
    app = _make_app(settings, valkey_get_result=cached_data)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/instrument/entity-456", headers=_JWT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is True
    assert body["entity_id"] == "entity-456"
    app.state.briefing_uc.execute.assert_not_awaited()


# ── Instrument briefing — auth ────────────────────────────────────────────────


async def test_instrument_briefing_requires_auth(settings: RagChatSettings) -> None:
    """No X-Internal-JWT header -> 401."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/instrument/entity-123")
    assert resp.status_code == 401


# ── Instrument briefing — error handling ──────────────────────────────────────


async def test_instrument_briefing_generation_failure_503(settings: RagChatSettings) -> None:
    """ProviderUnavailableError from UC -> 503."""
    from rag_chat.domain.errors import ProviderUnavailableError

    app = _make_app(settings, uc_result=ProviderUnavailableError("All down"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/instrument/entity-123", headers=_JWT_HEADERS)
    assert resp.status_code == 503
