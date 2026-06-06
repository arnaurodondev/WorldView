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
# PLAN-0062-W4: added confidence + lead fields to the mock return value so the
# route can propagate them without a KeyError.
_MORNING_RESULT = {
    "content": "Morning market overview for today.",
    "risk_summary": {"concentration_score": 0.0},
    "entity_mentions": [],
    "citations": [],
    "generated_at": "2026-04-19T12:00:00+00:00",
    "confidence": 0.85,
    "lead": "Markets opened higher on strong jobs data.",
    "sections": [],
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
    """After generating, the result is written to Valkey under BOTH fresh + lastgood keys.

    PLAN-0094 W2 added the second ``briefing:morning:lastgood:{user_id}`` write so a
    future regeneration failure has a known-good payload to fall back on.
    """
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    # Valkey.set should have been called twice — once for fresh, once for lastgood.
    assert app.state.valkey.set.await_count == 2
    keys_written = [c.args[0] for c in app.state.valkey.set.await_args_list]
    # Both keys are present.  We check the prefixes rather than the exact key so the
    # test does not couple to the test user_id.
    assert any(k.startswith("briefing:morning:v2:") for k in keys_written)
    assert any(k.startswith("briefing:morning:lastgood:") for k in keys_written)
    # Fresh key uses _CACHE_TTL=86400; lastgood uses _LASTGOOD_TTL=604800.
    fresh_call = next(c for c in app.state.valkey.set.await_args_list if "v2" in c.args[0])
    assert fresh_call.kwargs.get("ex") == 86400


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


async def test_instrument_briefing_entity_not_found_404(settings: RagChatSettings) -> None:
    """EntityNotFoundError from UC -> 404 (not 503).

    WHY this test: before this fix, a wrong entity_id (e.g. a market-data instrument_id
    instead of a KG entity_id) caused S7 to return empty nodes, which triggered
    EntityNotFoundError in BriefingContextGatherer.gather_instrument_context().
    That exception fell through to the catch-all `except Exception` handler in
    the route and returned 503 ("Briefing generation unavailable").

    After the fix: EntityNotFoundError is caught explicitly and mapped to 404
    so the frontend can distinguish "entity doesn't exist" from a real server error.
    """
    from rag_chat.domain.errors import EntityNotFoundError

    app = _make_app(
        settings,
        uc_result=EntityNotFoundError("Entity 00000000-0000-0000-0000-000000000999 not found"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/briefings/instrument/00000000-0000-0000-0000-000000000999",
            headers=_JWT_HEADERS,
        )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ── PLAN-0062-W4 — confidence + lead propagation (T-W4-C-01) ──────────────────


async def test_morning_briefing_propagates_confidence(settings: RagChatSettings) -> None:
    """The route must propagate confidence from the UC result into the response body."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    # WHY: confidence=0.85 is set in _MORNING_RESULT mock; the route must pass it through
    assert "confidence" in body
    assert 0.0 <= body["confidence"] <= 1.0


async def test_morning_briefing_propagates_lead(settings: RagChatSettings) -> None:
    """The route must propagate lead from the UC result into the response body."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    body = resp.json()
    assert "lead" in body
    # The mock returns "Markets opened higher on strong jobs data." as the lead
    assert body["lead"] == "Markets opened higher on strong jobs data."


async def test_morning_briefing_v2_cache_key(settings: RagChatSettings) -> None:
    """Fresh cache key must use v2 format (not legacy v1) — PLAN-0062-W4 cache bump.

    PLAN-0094 W2: the route now writes TWO keys (fresh + lastgood); we assert
    the fresh key — looked up by the next request — is the v2 variant.
    """
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    # Inspect every key the route wrote — at least one must start with "briefing:morning:v2:".
    keys = [c.args[0] for c in app.state.valkey.set.await_args_list if c.args]
    assert any(k.startswith("briefing:morning:v2:") for k in keys)


async def test_instrument_briefing_v2_cache_key(settings: RagChatSettings) -> None:
    """Instrument cache key must use v2 format — PLAN-0062-W4 cache bump."""
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/briefings/instrument/entity-999", headers=_JWT_HEADERS)
    set_call = app.state.valkey.set.call_args
    actual_key = set_call.args[0] if set_call.args else ""
    assert actual_key.startswith("briefing:instrument:v2:")


async def test_stale_v1_cache_key_falls_through_to_generation(settings: RagChatSettings) -> None:
    """If the old v1 cache key has data but v2 does not, the route generates a new brief.

    This simulates the post-deploy scenario: old cache had "briefing:morning:{user_id}"
    but the new code reads "briefing:morning:v2:{user_id}" — Valkey returns None for
    the v2 key, so the UC is called (cache miss → generate).
    """
    # Valkey.get always returns None (cache miss for v2 key)
    app = _make_app(settings, valkey_get_result=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)
    assert resp.status_code == 200
    # UC must have been called (not served from cache)
    app.state.briefing_uc.execute_public_morning.assert_awaited_once()
    assert resp.json()["cached"] is False


async def test_morning_briefing_confidence_default_on_missing_uc_field(
    settings: RagChatSettings,
) -> None:
    """Route defaults confidence to 1.0 when UC result lacks the field."""
    from unittest.mock import AsyncMock, MagicMock

    from rag_chat.app import create_app

    app = create_app(settings)
    mock_uc = MagicMock()
    # UC result WITHOUT confidence field — simulates old UC code
    mock_uc.execute_public_morning = AsyncMock(
        return_value={
            "content": "Brief text.",
            "risk_summary": {},
            "entity_mentions": [],
            "citations": [],
            "generated_at": "2026-05-03T10:00:00+00:00",
            "sections": [],
            # No 'confidence' or 'lead' keys
        }
    )
    mock_uc.execute = AsyncMock()
    app.state.briefing_uc = mock_uc
    app.state.chat_orchestrator = MagicMock()
    mock_valkey = MagicMock()
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    app.state.valkey = mock_valkey

    import jwt as _jwt

    token = _jwt.encode(
        {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
        "secret",
        algorithm="HS256",
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers={"X-Internal-JWT": token})
    body = resp.json()
    # Default confidence=1.0 when not in UC result
    assert body["confidence"] == 1.0
    assert body["lead"] is None


# ── BP-322 — cache serialization round-trip ───────────────────────────────────


async def test_cache_write_uses_model_dump_json(settings: RagChatSettings) -> None:
    """Cache write must use model_dump_json() — NOT json.dumps(..., default=str).

    WHY: json.dumps(..., default=str) stringifies BriefSection/BriefBullet Pydantic
    objects to their Python repr (BP-322), which cannot be re-deserialized on read.
    model_dump_json() serialises nested models to proper JSON dicts.
    """
    app = _make_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    set_call = app.state.valkey.set.call_args
    # Second positional arg is the serialized payload
    cached_payload = set_call.args[1] if len(set_call.args) > 1 else ""
    # model_dump_json produces valid JSON — must be parseable
    import json

    parsed = json.loads(cached_payload)
    # sections must be dicts, not Python repr strings like "BriefSection(title=...)"
    for sec in parsed.get("sections", []):
        assert isinstance(sec, dict), f"Section serialized as non-dict (BP-322): {type(sec)}"


async def test_morning_briefing_sets_context_var_jwt(settings: RagChatSettings) -> None:
    """get_morning_briefing must call set_current_jwt(internal_jwt) before the use case.

    WHY: BaseUpstreamClient._get()/_post() reads get_current_jwt() to propagate
    X-Internal-JWT to S6/S7 calls.  If the ContextVar is not explicitly set in
    the route (before the UC call), code paths that bypass InternalJWTMiddleware
    (unit tests, background tasks) leave the ContextVar as None → S6 gets no JWT
    header → 401 on every embedding/news call in briefings.
    """
    from rag_chat.infrastructure.clients.auth_context import get_current_jwt

    # Capture the JWT value that was set in the ContextVar at UC call time
    captured: list[str | None] = []

    async def _side_effect(**kwargs: object) -> dict:
        # Record the ContextVar state at the moment the UC is invoked
        captured.append(get_current_jwt())
        return _MORNING_RESULT

    app = _make_app(settings)
    app.state.briefing_uc.execute_public_morning = _side_effect  # type: ignore[assignment]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 200
    # ContextVar must have been set to the JWT token before the UC was called
    assert len(captured) == 1
    assert captured[0] == _JWT_TOKEN


async def test_instrument_briefing_sets_context_var_jwt(settings: RagChatSettings) -> None:
    """get_instrument_briefing must call set_current_jwt(internal_jwt) before the use case.

    Same rationale as test_morning_briefing_sets_context_var_jwt — ensures that
    execute_public_instrument() (which has no internal_jwt parameter of its own)
    can still propagate the JWT to S6/S7 via the ContextVar.
    """
    from rag_chat.infrastructure.clients.auth_context import get_current_jwt

    captured: list[str | None] = []

    _INSTRUMENT_RESULT = {
        "content": "Instrument briefing text.",
        "risk_summary": {},
        "citations": [],
        "generated_at": "2026-04-19T12:00:00+00:00",
        "confidence": 0.9,
        "lead": "Stock surged on earnings beat.",
        "sections": [],
    }

    async def _side_effect(**kwargs: object) -> dict:
        captured.append(get_current_jwt())
        return _INSTRUMENT_RESULT

    app = _make_app(settings)
    app.state.briefing_uc.execute_public_instrument = _side_effect  # type: ignore[assignment]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/instrument/entity-abc", headers=_JWT_HEADERS)

    assert resp.status_code == 200
    assert len(captured) == 1
    assert captured[0] == _JWT_TOKEN


async def test_cache_read_round_trip_with_w4_sections(settings: RagChatSettings) -> None:
    """Cache hit with W4 BriefBullet sections must deserialise correctly (BP-322 regression guard)."""
    from rag_chat.api.schemas import BriefBullet, BriefCitation, BriefSection, PublicBriefingResponse

    # Simulate a cache value written by model_dump_json() containing W4 bullet format
    w4_brief = PublicBriefingResponse(
        narrative="## LEAD\nTest lead [c1].\n---\n## DETAILS\n### Section\n- Bullet [c1]",
        risk_summary={},
        citations=[],
        generated_at="2026-05-03T10:00:00+00:00",
        cached=False,
        sections=[
            BriefSection(
                title="Test Section",
                bullets=[
                    BriefBullet(
                        text="Market moved higher on strong data",
                        citations=[
                            BriefCitation(
                                document_id="01900000-0000-7000-0000-000000000001",
                                snippet="Article headline — Article summary excerpt",
                                url="https://example.com/article/1",
                                source_type="article",
                                title="Article headline",
                            )
                        ],
                    )
                ],
            )
        ],
        confidence=0.85,
        lead="Test lead [c1].",
    )
    cached_json = w4_brief.model_dump_json()

    app = _make_app(settings, valkey_get_result=cached_json)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["cached"] is True
    assert len(body["sections"]) == 1
    assert body["sections"][0]["title"] == "Test Section"
    # Bullets must be dicts with citations (not strings)
    bullet = body["sections"][0]["bullets"][0]
    assert isinstance(bullet, dict)
    assert bullet["text"] == "Market moved higher on strong data"
    assert len(bullet["citations"]) == 1
    assert bullet["citations"][0]["source_type"] == "article"
    # UC must NOT have been called (cache hit)
    app.state.briefing_uc.execute_public_morning.assert_not_awaited()


# ── PLAN-0094 W2: handler fallback path (fresh → lastgood → on-demand) ───────


def _make_app_with_keyed_valkey(
    settings: RagChatSettings,
    *,
    fresh_value: str | bytes | None = None,
    lastgood_value: str | bytes | None = None,
    uc_result: dict | Exception | None = None,  # type: ignore[type-arg]
) -> object:
    """Build a test app whose Valkey.get distinguishes fresh vs lastgood keys.

    WHY this helper exists: the default ``_make_app`` returns the same value for
    every ``valkey.get`` call, so it cannot model the W2 lookup chain where the
    fresh key misses but the lastgood key hits.  This helper installs a
    side_effect that branches on the key prefix.
    """
    app = create_app(settings)

    mock_uc = MagicMock()
    if isinstance(uc_result, Exception):
        mock_uc.execute_public_morning = AsyncMock(side_effect=uc_result)
    else:
        mock_uc.execute_public_morning = AsyncMock(return_value=uc_result or _MORNING_RESULT)
    mock_uc.execute = AsyncMock(return_value=_BRIEFING_RESULT)
    mock_uc.execute_public_instrument = AsyncMock(return_value=_BRIEFING_RESULT)
    app.state.briefing_uc = mock_uc
    app.state.chat_orchestrator = MagicMock()

    mock_valkey = MagicMock()

    async def _get_side_effect(key: str) -> str | bytes | None:
        # WHY two prefixes (not exact key): we don't want the test to couple to
        # the test user_id format — the handler uses ``f"briefing:morning:v2:{user_id}"``
        # and ``f"briefing:morning:lastgood:{user_id}"``.
        if key.startswith("briefing:morning:v2:"):
            return fresh_value
        if key.startswith("briefing:morning:lastgood:"):
            return lastgood_value
        return None

    mock_valkey.get = AsyncMock(side_effect=_get_side_effect)
    mock_valkey.set = AsyncMock()
    app.state.valkey = mock_valkey
    return app


def _make_brief_json(*, narrative: str, generated_at: str = "2026-05-25T08:00:00+00:00") -> str:
    """Helper to serialise a minimal PublicBriefingResponse for Valkey seeds."""
    from rag_chat.api.schemas import PublicBriefingResponse

    return PublicBriefingResponse(
        narrative=narrative,
        risk_summary={},
        citations=[],
        generated_at=generated_at,
        cached=False,
        entity_id=None,
    ).model_dump_json()


async def test_handler_returns_fresh_when_fresh_cache_hit(settings: RagChatSettings) -> None:
    """Fresh key hit → is_stale=False, UC NOT called, no background regen."""
    fresh = _make_brief_json(narrative="Fresh brief.")
    app = _make_app_with_keyed_valkey(settings, fresh_value=fresh, lastgood_value=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["narrative"] == "Fresh brief."
    assert body["is_stale"] is False
    assert body["cached"] is True
    # UC must NOT have been called — fresh hit short-circuits.
    app.state.briefing_uc.execute_public_morning.assert_not_awaited()  # type: ignore[attr-defined]


async def test_handler_returns_lastgood_with_stale_flag(settings: RagChatSettings) -> None:
    """No fresh + lastgood present → is_stale=True, served_stale counter +1."""
    from rag_chat.application.metrics.prometheus import rag_brief_served_stale_total

    before = rag_brief_served_stale_total._value.get()

    stale = _make_brief_json(narrative="Yesterday's brief.", generated_at="2026-05-24T08:00:00+00:00")
    app = _make_app_with_keyed_valkey(settings, fresh_value=None, lastgood_value=stale)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["narrative"] == "Yesterday's brief."
    assert body["is_stale"] is True
    assert body["generated_at"] == "2026-05-24T08:00:00+00:00"
    # Stale-serve counter incremented.
    assert rag_brief_served_stale_total._value.get() == before + 1


async def test_handler_falls_back_to_on_demand_when_no_cache(settings: RagChatSettings) -> None:
    """No fresh + no lastgood (cold user) → on-demand generation, is_stale=False."""
    app = _make_app_with_keyed_valkey(settings, fresh_value=None, lastgood_value=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert body["is_stale"] is False
    # Used the on-demand path: UC was called once.
    app.state.briefing_uc.execute_public_morning.assert_awaited_once()  # type: ignore[attr-defined]


async def test_handler_does_not_blockingly_regenerate_when_stale_served(
    settings: RagChatSettings,
) -> None:
    """Stale serve → response returns BEFORE the background regen completes.

    We measure this by asserting the response comes back even though the UC
    mock's ``execute_public_morning`` does NOT immediately resolve — the
    handler must not block on the background task.
    """
    import asyncio as _asyncio

    stale = _make_brief_json(narrative="Stale.")
    app = _make_app_with_keyed_valkey(settings, fresh_value=None, lastgood_value=stale)

    # Make the UC's background regen "hang" for a long time.  If the handler
    # blocked on it, the request would timeout.
    async def _slow(**_kw: object) -> dict[str, object]:
        # Sleep longer than the test timeout — we want the handler to NOT
        # wait on this.  `asyncio.sleep` cancels cleanly when the background
        # task is GC'd at test exit, avoiding the "coroutine never awaited"
        # warning that `asyncio.Event.wait` would emit.
        await _asyncio.sleep(60)
        return {"content": "(never)", "generated_at": "2026-05-25T00:00:00+00:00"}

    app.state.briefing_uc.execute_public_morning = AsyncMock(side_effect=_slow)  # type: ignore[attr-defined]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=2.0) as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    # Despite the UC hanging, the response came back quickly with the stale brief.
    assert resp.status_code == 200
    assert resp.json()["is_stale"] is True


async def test_handler_503_when_on_demand_fails_for_cold_user(settings: RagChatSettings) -> None:
    """Cold user (no fresh, no lastgood) + UC raises → 503 (existing behaviour preserved)."""
    from rag_chat.domain.errors import ProviderUnavailableError

    app = _make_app_with_keyed_valkey(
        settings,
        fresh_value=None,
        lastgood_value=None,
        uc_result=ProviderUnavailableError("All providers down"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 503


# ── F-CR-003 regression — JWT contextvar leak in stale-serve background regen ──


async def test_stale_serve_does_not_leak_bg_jwt_into_parent_context(
    settings: RagChatSettings,
) -> None:
    """F-CR-003 — set_current_jwt(bg_jwt) before asyncio.create_task leaked the
    background JWT into the parent request's Context.  The fix passes bg_jwt
    as an explicit arg to the coroutine and only sets the ContextVar inside
    the background task's own Context copy.

    Regression assertion: AFTER the handler returns (i.e. after the stale
    serve schedules the background regen), the parent test scope's
    ContextVar must be unchanged from its prior state.
    """
    import asyncio as _asyncio

    from rag_chat.infrastructure.clients.auth_context import get_current_jwt, set_current_jwt

    # Seed the parent Context with a known sentinel BEFORE invoking the handler.
    # If the handler leaks bg_jwt into this Context, the post-handler check
    # below will see the leaked JWT instead of the sentinel.
    sentinel = "PARENT-CTX-SENTINEL"  # — test sentinel, not a real secret
    set_current_jwt(sentinel)

    stale = _make_brief_json(narrative="Stale brief.")
    app = _make_app_with_keyed_valkey(settings, fresh_value=None, lastgood_value=stale)

    # Make the UC mock return immediately so the background task completes
    # quickly (we don't want a hanging task affecting GC during teardown).
    async def _fast_uc(**_kw: object) -> dict[str, object]:
        return {
            "content": "regen content",
            "risk_summary": {},
            "citations": [],
            "sections": [],
            "generated_at": "2026-05-26T08:00:00+00:00",
            "confidence": 1.0,
            "lead": None,
        }

    app.state.briefing_uc.execute_public_morning = AsyncMock(side_effect=_fast_uc)  # type: ignore[attr-defined]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 200
    assert resp.json()["is_stale"] is True

    # Give the background task a moment to run so we exercise the entire path.
    await _asyncio.sleep(0.05)

    # The parent Context's JWT must still be our sentinel — never replaced
    # by bg_jwt from the handler.  Pre-fix this would have been _JWT_TOKEN.
    assert get_current_jwt() == sentinel


async def test_background_regen_uses_bg_jwt_inside_task_context(
    settings: RagChatSettings,
) -> None:
    """F-CR-003 — the background regen coroutine MUST see bg_jwt via the
    ContextVar inside its own task context (so BaseUpstreamClient picks it up).

    Positive complement to the leak test: the JWT lives in the task's Context
    (correct), not the parent's Context (the bug).
    """
    from rag_chat.infrastructure.clients.auth_context import get_current_jwt

    captured_inside_task: list[str | None] = []

    async def _capturing_uc(**_kw: object) -> dict[str, object]:
        captured_inside_task.append(get_current_jwt())
        return {
            "content": "ok",
            "risk_summary": {},
            "citations": [],
            "sections": [],
            "generated_at": "2026-05-26T08:00:00+00:00",
            "confidence": 1.0,
            "lead": None,
        }

    stale = _make_brief_json(narrative="Stale.")
    app = _make_app_with_keyed_valkey(settings, fresh_value=None, lastgood_value=stale)
    app.state.briefing_uc.execute_public_morning = AsyncMock(side_effect=_capturing_uc)  # type: ignore[attr-defined]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning", headers=_JWT_HEADERS)

    assert resp.status_code == 200

    # Give the bg task time to run.
    import asyncio as _asyncio

    await _asyncio.sleep(0.05)

    # The bg task observed the JWT inside its own Context — the explicit-arg
    # pattern works (the handler did NOT leak via the parent Context).
    assert captured_inside_task == [_JWT_TOKEN]
