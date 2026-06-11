"""Unit tests for POST /api/v1/briefings/morning/generate (force-regenerate).

Backs the dashboard "Regenerate" button. Contract:
  - ALWAYS regenerates — bypasses the staleness/cache check entirely
    (Valkey.get must NOT gate the UC call).
  - 202 + {"status": "queued", "generated_at": ...} on success.
  - Writes BOTH the fresh cache key AND the lastgood key after generation.
  - Shares the brief_gen_rate:{user_id}:{hour} 60/hr bucket with the
    instrument lazy-generate endpoint → 429 + Retry-After on excess.
  - ProviderUnavailableError → 503; generic failure → 503.
  - Valkey down → fail-open (generation still proceeds).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from fastapi import FastAPI
from rag_chat.app import create_app
from rag_chat.domain.errors import ProviderUnavailableError
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_USER_ID = "00000000-0000-0000-0000-000000000099"
_TENANT_ID = "00000000-0000-0000-0000-000000000088"

_UC_RESULT = {
    "content": "Markets opened mixed; your portfolio is up 0.4%.",
    "risk_summary": {"concentration_score": 0.2},
    "citations": [],
    "generated_at": "2026-06-10T06:00:00+00:00",
    "confidence": 0.9,
    "lead": "Quiet macro morning.",
    "sections": [],
    "summary": None,
    "summary_paragraph": "Quiet macro morning; tech leads.",
}

_JWT_TOKEN = _jwt.encode(
    {"sub": _USER_ID, "tenant_id": _TENANT_ID, "user_id": _USER_ID, "role": "user"},
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
    valkey_get_result: bytes | None = None,
    valkey_incr_count: int = 1,
    valkey_available: bool = True,
) -> FastAPI:
    """Create test app with mocked briefing UC and Valkey client."""
    app = create_app(settings)

    mock_uc = MagicMock()
    result = uc_result if uc_result is not None else _UC_RESULT
    if isinstance(result, Exception):
        mock_uc.execute_public_morning = AsyncMock(side_effect=result)
    else:
        mock_uc.execute_public_morning = AsyncMock(return_value=result)
    app.state.briefing_uc = mock_uc
    app.state.chat_orchestrator = MagicMock()

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


async def _post(app: FastAPI) -> object:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/briefings/morning/generate", headers=_JWT_HEADERS)


@pytest.mark.asyncio
async def test_generate_returns_202_queued(settings: RagChatSettings) -> None:
    """Happy path: 202 + status='queued' + generated_at echoed from the UC result."""
    app = _make_app(settings)
    resp = await _post(app)

    assert resp.status_code == 202  # type: ignore[attr-defined]
    payload = resp.json()  # type: ignore[attr-defined]
    assert payload["status"] == "queued"
    assert payload["generated_at"] == _UC_RESULT["generated_at"]
    app.state.briefing_uc.execute_public_morning.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_bypasses_cache_check(settings: RagChatSettings) -> None:
    """FORCE semantics: even with a warm cache, the UC is still invoked.

    This is the whole point of the endpoint — the GET route would have
    served the cached brief; the Regenerate button must not.
    """
    app = _make_app(settings, valkey_get_result=b'{"narrative": "stale cached brief"}')
    resp = await _post(app)

    assert resp.status_code == 202  # type: ignore[attr-defined]
    app.state.briefing_uc.execute_public_morning.assert_awaited_once()
    # The route must never even read the brief cache key (only the rate counter).
    app.state.valkey.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_writes_fresh_and_lastgood_keys(settings: RagChatSettings) -> None:
    """After regeneration BOTH cache keys are written so the follow-up GET serves fresh."""
    app = _make_app(settings)
    await _post(app)

    set_calls = app.state.valkey.set.await_args_list
    keys = [c.args[0] for c in set_calls]
    assert f"briefing:morning:v2:{_USER_ID}" in keys
    assert f"briefing:morning:lastgood:{_USER_ID}" in keys
    # Fresh key carries the 24h TTL; lastgood the 7-day TTL.
    ttls = {c.args[0]: c.kwargs.get("ex") for c in set_calls}
    assert ttls[f"briefing:morning:v2:{_USER_ID}"] == 86400
    assert ttls[f"briefing:morning:lastgood:{_USER_ID}"] == 7 * 86400


@pytest.mark.asyncio
async def test_generate_rate_limit_exceeded_returns_429(settings: RagChatSettings) -> None:
    """Counter over 60 → 429 with a Retry-After header; UC never called."""
    app = _make_app(settings, valkey_incr_count=61)
    resp = await _post(app)

    assert resp.status_code == 429  # type: ignore[attr-defined]
    assert "Retry-After" in resp.headers  # type: ignore[attr-defined]
    app.state.briefing_uc.execute_public_morning.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_provider_unavailable_returns_503(settings: RagChatSettings) -> None:
    """All LLM providers down → 503 (matches instrument-generate semantics)."""
    app = _make_app(settings, uc_result=ProviderUnavailableError("all providers down"))
    resp = await _post(app)
    assert resp.status_code == 503  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_generate_valkey_down_fails_open(settings: RagChatSettings) -> None:
    """Valkey down → rate-limit fails open; generation still completes with 202."""
    app = _make_app(settings, valkey_available=False)
    resp = await _post(app)

    assert resp.status_code == 202  # type: ignore[attr-defined]
    app.state.briefing_uc.execute_public_morning.assert_awaited_once()
