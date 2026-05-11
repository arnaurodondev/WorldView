"""Unit tests for POST /api/v1/chat/entity-context route (PLAN-0074 Wave F, T-F-02).

Mirrors the pattern from tests/unit/api/test_chat.py:
  - Mocks entity_context_chat_uc on app.state.
  - Uses AuthContextDep and UoWDep overrides.
  - Verifies 200, 429, 400, 503, and 401 responses.
  - Verifies SSE stream from the /stream variant.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000020")
_USER_ID = UUID("00000000-0000-0000-0000-000000000021")
_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000030")

_INTERNAL_JWT = _jwt.encode(
    {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
    "secret",
    algorithm="HS256",
)
_AUTH_HEADERS = {"X-Internal-JWT": _INTERNAL_JWT}


def _mock_uow() -> MagicMock:
    uow = MagicMock()
    uow.threads = MagicMock()
    uow.messages = MagicMock()
    uow.messages.create = AsyncMock(return_value=None)
    uow.threads.update_last_msg = AsyncMock(return_value=None)
    uow.commit = AsyncMock(return_value=None)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    return uow


def _mock_entity_uc(stream: bool = False) -> MagicMock:
    """Mock EntityContextChatUseCase for sync or stream tests."""
    uc = MagicMock()

    thread_id = str(uuid4())
    message_id = str(uuid4())

    uc.execute_sync = AsyncMock(
        return_value={
            "answer": "Apple revenue was $120B in Q3 2025.",
            "citations": [{"ref": 1, "title": "Apple 10-K 2025"}],
            "contradictions": [],
            "thread_id": thread_id,
            "message_id": message_id,
            "intent": "FACTUAL_LOOKUP",
            "provider": "deepinfra",
            "latency_ms": 800,
        }
    )

    async def _stream_events(entity_id, question, tenant_id, user_id, jwt_token, thread_id, include_graph_context, uow):  # type: ignore[no-untyped-def]
        yield {"event": "status", "data": json.dumps({"step": "loading_context"})}
        yield {"event": "token", "data": json.dumps({"text": "Apple revenue"})}
        yield {"event": "citations", "data": json.dumps([])}
        yield {"event": "contradictions", "data": json.dumps([])}
        yield {
            "event": "metadata",
            "data": json.dumps(
                {
                    "thread_id": thread_id or str(uuid4()),
                    "message_id": str(uuid4()),
                    "intent": "FACTUAL_LOOKUP",
                    "provider": "deepinfra",
                    "latency_ms": 800,
                }
            ),
        }
        yield {"event": "done", "data": json.dumps({"type": "done"})}

    uc.execute_streaming = _stream_events
    return uc


@pytest.fixture
def settings() -> RagChatSettings:
    return RagChatSettings(
        database_url="postgresql+asyncpg://fake:fake@localhost:5432/fake_rag_db",
        s1_internal_token="test-token",
        log_json=False,
        log_level="WARNING",
        internal_jwt_skip_verification=True,
    )


@pytest.fixture
def app_with_entity_uc(settings: RagChatSettings):  # type: ignore[return]
    """App with entity_context_chat_uc, orchestrator, auth, and UoW mocked."""
    from rag_chat.api.dependencies import get_auth_context, get_uow

    app = create_app(settings)

    # Both orchestrators needed (lifespan may read them before app.state overrides).
    app.state.chat_orchestrator = MagicMock()
    app.state.entity_context_chat_uc = _mock_entity_uc()

    uow = _mock_uow()

    async def _override_uow():  # type: ignore[return]
        yield uow

    async def _override_auth() -> tuple[UUID, UUID]:
        return (_TENANT_ID, _USER_ID)

    app.dependency_overrides[get_uow] = _override_uow
    app.dependency_overrides[get_auth_context] = _override_auth

    # write_factory mock needed for SSE stream variant.
    mock_session = MagicMock()
    mock_session.close = AsyncMock(return_value=None)
    app.state.write_factory = MagicMock(return_value=mock_session)

    yield app
    app.dependency_overrides.clear()


@pytest.fixture
def app_no_auth(settings: RagChatSettings):  # type: ignore[return]
    """App with entity_context_chat_uc but NO auth override."""
    app = create_app(settings)
    app.state.chat_orchestrator = MagicMock()
    app.state.entity_context_chat_uc = _mock_entity_uc()
    yield app


# ── T1: 200 response with answer ─────────────────────────────────────────────


async def test_entity_context_chat_200(app_with_entity_uc) -> None:  # type: ignore[no-untyped-def]
    """POST /api/v1/chat/entity-context returns 200 with answer."""
    transport = ASGITransport(app=app_with_entity_uc)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/entity-context",
            json={"entity_id": str(_ENTITY_ID), "question": "What is Apple revenue?"},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "answer" in body
    assert body["answer"] != ""
    assert "citations" in body


# ── T2: SSE stream from /entity-context/stream ───────────────────────────────


async def test_entity_context_chat_stream_sse(app_with_entity_uc) -> None:  # type: ignore[no-untyped-def]
    """POST /api/v1/chat/entity-context/stream returns text/event-stream."""
    transport = ASGITransport(app=app_with_entity_uc)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/entity-context/stream",
            json={"entity_id": str(_ENTITY_ID), "question": "Apple Q3 earnings?"},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


# ── T3: Missing auth -> 401 ───────────────────────────────────────────────────


async def test_entity_context_chat_missing_auth_401(app_no_auth) -> None:  # type: ignore[no-untyped-def]
    """No X-Internal-JWT -> 401."""
    transport = ASGITransport(app=app_no_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/entity-context",
            json={"entity_id": str(_ENTITY_ID), "question": "test"},
        )
    assert resp.status_code == 401


# ── T4: rate limit -> 429 ────────────────────────────────────────────────────


async def test_entity_context_chat_rate_limit_429(settings: RagChatSettings) -> None:
    """Rate limit exceeded -> 429."""
    from rag_chat.api.dependencies import get_auth_context, get_uow
    from rag_chat.domain.errors import RateLimitExceededError

    uc = MagicMock()
    uc.execute_sync = AsyncMock(side_effect=RateLimitExceededError("too many"))

    app = create_app(settings)
    app.state.chat_orchestrator = MagicMock()
    app.state.entity_context_chat_uc = uc

    uow = _mock_uow()

    async def _override_uow():  # type: ignore[return]
        yield uow

    async def _override_auth() -> tuple[UUID, UUID]:
        return (_TENANT_ID, _USER_ID)

    app.dependency_overrides[get_uow] = _override_uow
    app.dependency_overrides[get_auth_context] = _override_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/entity-context",
            json={"entity_id": str(_ENTITY_ID), "question": "test"},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 429
    app.dependency_overrides.clear()


# ── T5: Provider down -> 503 ─────────────────────────────────────────────────


async def test_entity_context_chat_provider_down_503(settings: RagChatSettings) -> None:
    """ProviderUnavailableError -> 503."""
    from rag_chat.api.dependencies import get_auth_context, get_uow
    from rag_chat.domain.errors import ProviderUnavailableError

    uc = MagicMock()
    uc.execute_sync = AsyncMock(side_effect=ProviderUnavailableError("all down"))

    app = create_app(settings)
    app.state.chat_orchestrator = MagicMock()
    app.state.entity_context_chat_uc = uc

    uow = _mock_uow()

    async def _override_uow():  # type: ignore[return]
        yield uow

    async def _override_auth() -> tuple[UUID, UUID]:
        return (_TENANT_ID, _USER_ID)

    app.dependency_overrides[get_uow] = _override_uow
    app.dependency_overrides[get_auth_context] = _override_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/entity-context",
            json={"entity_id": str(_ENTITY_ID), "question": "test"},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 503
    app.dependency_overrides.clear()


# ── T6: Empty question -> 422 (Pydantic validation) ──────────────────────────


async def test_entity_context_chat_empty_question_422(app_with_entity_uc) -> None:  # type: ignore[no-untyped-def]
    """Empty question fails Pydantic validation -> 422."""
    transport = ASGITransport(app=app_with_entity_uc)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/entity-context",
            json={"entity_id": str(_ENTITY_ID), "question": "   "},
            headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 422
