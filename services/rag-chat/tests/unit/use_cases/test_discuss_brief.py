"""Unit tests for POST /api/v1/briefings/chat/discuss (PLAN-0066 Wave D T-W10-D-01).

Tests verify:
  - 201 response with valid JWT and a seeded brief → thread_id + seeded_with_brief_id
  - 422 when no brief exists in the archive

WHY test at the route level (not use-case level): the core logic is in the route
handler (fetching the brief, calling CreateThreadUseCase, returning IDs). The use
case itself is already tested in test_thread_use_cases.py. Route-level tests verify
the HTTP contract and the wiring between archive + use case + response shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
_BRIEF_ID = UUID("00000000-0000-0000-0000-000000000001")
_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)

# JWT token decoded without verification (internal_jwt_skip_verification=True)
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


def _make_user_brief_record() -> object:
    """Build a UserBriefRecord for use in mock archive returns."""
    from rag_chat.application.ports.brief_archive import UserBriefRecord

    return UserBriefRecord(
        id=_BRIEF_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        entity_id=None,
        generated_at=_NOW,
        headline="Markets rally on AI optimism.",
        lead="Tech stocks lead gains.",
        sections_json=[],
        citations_json=[{"title": "AI Rally", "url": "https://example.com", "snippet": "Markets up."}],
        confidence=0.88,
        source_version="v2",
    )


def _build_app(
    settings: RagChatSettings,
    archive_records: list | None = None,
) -> object:
    """Build a test app with fully mocked infra + archive dependency override.

    WHY override get_brief_archive_dep: the discuss endpoint uses BriefArchiveRepositoryDep
    which calls read_factory() under the hood. Overriding the dependency directly avoids
    needing a real DB session while still exercising the full route handler logic.

    WHY also mock write_factory: CreateThreadUseCase calls uow.threads.create() and
    uow.commit(). We override get_uow to yield a fully-mocked UoW that records calls
    without hitting the DB.
    """
    from rag_chat.api.dependencies import get_brief_archive_dep, get_uow

    app = create_app(settings)

    # ── App state: brief UC, chat orchestrator, valkey ────────────────────────
    mock_uc = MagicMock()
    mock_uc.execute_public_morning = AsyncMock(
        return_value={
            "content": "Morning brief.",
            "risk_summary": {},
            "entity_mentions": [],
            "citations": [],
            "generated_at": _NOW.isoformat(),
            "confidence": 0.8,
            "lead": None,
            "sections": [],
        }
    )
    mock_uc.execute_public_instrument = AsyncMock(
        return_value={
            "content": "Instrument brief.",
            "risk_summary": None,
            "entity_mentions": [],
            "citations": [],
            "generated_at": _NOW.isoformat(),
            "confidence": 0.8,
            "lead": None,
            "sections": [],
        }
    )
    app.state.briefing_uc = mock_uc
    app.state.chat_orchestrator = MagicMock()
    mock_valkey = MagicMock()
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    app.state.valkey = mock_valkey

    # ── Archive mock ──────────────────────────────────────────────────────────
    mock_archive = MagicMock()
    mock_archive.get_latest = AsyncMock(return_value=archive_records or [])
    mock_archive.get_history = AsyncMock(return_value=([], 0))
    mock_archive.get_by_id = AsyncMock(return_value=None)

    async def _mock_archive_dep():  # type: ignore[return]
        yield mock_archive

    app.dependency_overrides[get_brief_archive_dep] = _mock_archive_dep

    # ── UoW mock: create mock thread so the route can return thread_id ────────
    from rag_chat.domain.entities.conversation import ConversationThread

    _mock_thread = ConversationThread(
        thread_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        created_at=_NOW,
        updated_at=_NOW,
        title=None,
        entity_ids=(),
        messages=(),
        archived_at=None,
        seed_brief_id=_BRIEF_ID,
    )

    mock_uow = MagicMock()
    mock_uow.threads = MagicMock()
    mock_uow.threads.create = AsyncMock(return_value=None)
    mock_uow.commit = AsyncMock(return_value=None)
    # __aenter__ / __aexit__ for async context manager protocol
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    # Patch CreateThreadUseCase.execute so it returns the mock thread
    # without needing the UoW repository to be fully wired.
    async def _fake_create_execute(_uow: object, **_kwargs: object) -> ConversationThread:
        return _mock_thread

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "rag_chat.application.use_cases.create_thread.CreateThreadUseCase.execute",
            _fake_create_execute,
        )

    async def _mock_uow_dep():  # type: ignore[return]
        yield mock_uow

    app.dependency_overrides[get_uow] = _mock_uow_dep
    app.state.write_factory = lambda: MagicMock()
    app.state.read_factory = lambda: MagicMock()

    # Store the mock thread for assertions
    app.state._test_mock_thread = _mock_thread  # type: ignore[attr-defined]

    return app


# ── T-W10-D-01: 201 with seed ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discuss_creates_thread_with_seed(settings: RagChatSettings) -> None:
    """POST /api/v1/briefings/chat/discuss with a brief available → 201 with thread_id.

    The route must:
      1. Call archive.get_latest() to fetch the most-recent morning brief.
      2. Call CreateThreadUseCase.execute() with seed_brief_id set to the brief's ID.
      3. Return 201 with thread_id + seeded_with_brief_id.
    """
    from rag_chat.api.dependencies import get_brief_archive_dep, get_uow

    app = create_app(settings)

    # Shared mock thread for assertions
    from rag_chat.domain.entities.conversation import ConversationThread

    _mock_thread = ConversationThread(
        thread_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        created_at=_NOW,
        updated_at=_NOW,
        seed_brief_id=_BRIEF_ID,
    )

    # Brief archive returns our sample record
    mock_archive = MagicMock()
    mock_archive.get_latest = AsyncMock(return_value=[_make_user_brief_record()])
    mock_archive.get_history = AsyncMock(return_value=([], 0))
    mock_archive.get_by_id = AsyncMock(return_value=None)

    async def _mock_archive_dep():  # type: ignore[return]
        yield mock_archive

    # UoW mock
    mock_uow = MagicMock()
    mock_uow.threads = MagicMock()
    mock_uow.threads.create = AsyncMock(return_value=None)
    mock_uow.commit = AsyncMock(return_value=None)
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    async def _mock_uow_dep():  # type: ignore[return]
        yield mock_uow

    # Patch briefing UC + valkey
    mock_uc = MagicMock()
    mock_uc.execute_public_morning = AsyncMock(
        return_value={
            "content": "",
            "risk_summary": {},
            "citations": [],
            "generated_at": _NOW.isoformat(),
            "confidence": 0.8,
            "lead": None,
            "sections": [],
        }
    )
    mock_uc.execute_public_instrument = AsyncMock(
        return_value={
            "content": "",
            "risk_summary": None,
            "citations": [],
            "generated_at": _NOW.isoformat(),
            "confidence": 0.8,
            "lead": None,
            "sections": [],
        }
    )
    app.state.briefing_uc = mock_uc
    app.state.chat_orchestrator = MagicMock()
    mock_valkey = MagicMock()
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    app.state.valkey = mock_valkey
    app.state.write_factory = lambda: MagicMock()
    app.state.read_factory = lambda: MagicMock()

    app.dependency_overrides[get_brief_archive_dep] = _mock_archive_dep
    app.dependency_overrides[get_uow] = _mock_uow_dep

    # Patch CreateThreadUseCase.execute to capture the call and return mock thread
    captured_kwargs: dict = {}

    async def _fake_execute(_self: object, _uow: object, **kwargs: object) -> ConversationThread:
        captured_kwargs.update(kwargs)
        return _mock_thread

    import rag_chat.application.use_cases.create_thread as _uc_module

    original = _uc_module.CreateThreadUseCase.execute
    _uc_module.CreateThreadUseCase.execute = _fake_execute  # type: ignore[method-assign]

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/briefings/chat/discuss",
                json={"brief_type": "morning"},
                headers=_JWT_HEADERS,
            )
    finally:
        _uc_module.CreateThreadUseCase.execute = original  # type: ignore[method-assign]

    # ── Assertions ────────────────────────────────────────────────────────────
    assert resp.status_code == 201, resp.text
    body = resp.json()

    # Response shape
    assert "thread_id" in body
    assert "seeded_with_brief_id" in body
    assert body["thread_id"] == str(_mock_thread.thread_id)
    assert body["seeded_with_brief_id"] == str(_BRIEF_ID)

    # CreateThreadUseCase must have been called with seed_brief_id
    assert captured_kwargs.get("seed_brief_id") == _BRIEF_ID

    # Archive must have been called to fetch the brief
    mock_archive.get_latest.assert_called_once()


# ── T-W10-D-01: 422 when no brief ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discuss_fails_when_no_brief(settings: RagChatSettings) -> None:
    """POST /api/v1/briefings/chat/discuss with no brief in archive → 422.

    WHY 422: the route cannot proceed without a brief to seed the thread.
    A 404 would imply the endpoint itself doesn't exist; 422 signals
    "request valid but pre-condition not met" (brief must be generated first).
    """
    from rag_chat.api.dependencies import get_brief_archive_dep, get_uow

    app = create_app(settings)

    # Archive returns empty list — no briefs generated yet
    mock_archive = MagicMock()
    mock_archive.get_latest = AsyncMock(return_value=[])
    mock_archive.get_history = AsyncMock(return_value=([], 0))
    mock_archive.get_by_id = AsyncMock(return_value=None)

    async def _mock_archive_dep():  # type: ignore[return]
        yield mock_archive

    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    async def _mock_uow_dep():  # type: ignore[return]
        yield mock_uow

    mock_uc = MagicMock()
    mock_uc.execute_public_morning = AsyncMock(
        return_value={
            "content": "",
            "risk_summary": {},
            "citations": [],
            "generated_at": _NOW.isoformat(),
            "confidence": 0.8,
            "lead": None,
            "sections": [],
        }
    )
    mock_uc.execute_public_instrument = AsyncMock(
        return_value={
            "content": "",
            "risk_summary": None,
            "citations": [],
            "generated_at": _NOW.isoformat(),
            "confidence": 0.8,
            "lead": None,
            "sections": [],
        }
    )
    app.state.briefing_uc = mock_uc
    app.state.chat_orchestrator = MagicMock()
    mock_valkey = MagicMock()
    mock_valkey.get = AsyncMock(return_value=None)
    mock_valkey.set = AsyncMock()
    app.state.valkey = mock_valkey
    app.state.write_factory = lambda: MagicMock()
    app.state.read_factory = lambda: MagicMock()

    app.dependency_overrides[get_brief_archive_dep] = _mock_archive_dep
    app.dependency_overrides[get_uow] = _mock_uow_dep

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/briefings/chat/discuss",
            json={"brief_type": "morning"},
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 422, resp.text
    body = resp.json()
    # FastAPI wraps HTTPException detail in {"detail": ...}
    assert "No" in body.get("detail", "")
