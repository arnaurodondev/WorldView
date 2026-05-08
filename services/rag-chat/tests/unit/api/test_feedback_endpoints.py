"""Unit tests for POST /api/v1/briefings/feedback/* endpoints (PLAN-0066 Wave C T-W10-C-02).

Tests verify:
  - test_bullet_feedback_returns_201: valid POST /feedback/bullet → 201 with id + created_at
  - test_brief_feedback_returns_201:  valid POST /feedback/brief  → 201 with id + created_at
  - test_feedback_rejects_unknown_brief: brief_id not owned by user → 404
  - test_bullet_feedback_invalid_reaction: reaction="meh" → 422 (Literal validation)

WHY dependency_overrides for UoW: the POST endpoints call uow.session to construct
BriefFeedbackUseCase. In unit tests we inject a mock UoW that exposes a mock session
and a mock commit(), avoiding any real DB connection.

WHY mock BriefFeedbackUseCase at the route level: the route tests focus on HTTP
contract (status codes, response shape, auth). They do not test the use case logic
(that's covered in a separate test_brief_diff.py / use-case layer test). Mocking
the use case keeps the tests fast and isolated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from rag_chat.app import create_app
from rag_chat.domain.errors import BriefNotFoundError
from rag_chat.infrastructure.config.settings import RagChatSettings

pytestmark = pytest.mark.unit

_USER_ID = UUID("00000000-0000-0000-0000-000000000099")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000088")
_BRIEF_ID = UUID("00000000-0000-0000-0000-000000000001")
_FEEDBACK_ID = UUID("00000000-0000-0000-0000-000000000099")
_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)

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


def _make_mock_session() -> MagicMock:
    """Create a mock AsyncSession that accepts close() calls."""
    session = MagicMock()
    session.close = AsyncMock()
    return session


def _make_app(
    settings: RagChatSettings,
    feedback_side_effect: Exception | None = None,
    feedback_return: tuple | None = None,
) -> object:
    """Create a test app with mocked write UoW and BriefFeedbackUseCase.

    Args:
        settings:           Service settings with skip_verification=True.
        feedback_side_effect: If set, the mocked use case methods raise this exception.
        feedback_return:    (feedback_id, created_at) for successful use case calls.
    """
    from rag_chat.api.dependencies import get_uow

    app = create_app(settings)

    # Minimal app.state mocks so the other routes don't crash during startup
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
    app.state.read_factory = lambda: _make_mock_session()
    app.state.write_factory = lambda: _make_mock_session()

    # Build a mock UoW with a mock session property and commit()
    return_val = feedback_return or (_FEEDBACK_ID, _NOW)

    mock_uow = MagicMock()
    mock_uow.commit = AsyncMock()

    # The session is exposed via uow.session (added in Wave C)
    mock_session = MagicMock()
    mock_uow.session = mock_session

    # Mock __aenter__ / __aexit__ so the route's `async with` works
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=False)

    # Patch BriefFeedbackUseCase at module level to avoid real DB calls
    if feedback_side_effect is not None:
        submit_mock = AsyncMock(side_effect=feedback_side_effect)
    else:
        submit_mock = AsyncMock(return_value=return_val)

    app._mock_submit = submit_mock  # type: ignore[attr-defined]

    # Override the write UoW DI dependency
    async def _mock_uow_dep():  # type: ignore[return]
        yield mock_uow

    app.dependency_overrides[get_uow] = _mock_uow_dep

    return app


# ── test_bullet_feedback_returns_201 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_bullet_feedback_returns_201(settings: RagChatSettings) -> None:
    """POST /briefings/feedback/bullet with valid payload → 201 with id + created_at.

    WHY: verifies the happy path: valid reaction, valid brief_id, authenticated user.
    The route must return 201 with a FeedbackResponse shape.
    """
    app = _make_app(settings)

    with patch(
        "rag_chat.application.use_cases.brief_feedback.BriefFeedbackUseCase.submit_bullet_feedback",
        new_callable=AsyncMock,
        return_value=(_FEEDBACK_ID, _NOW),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/briefings/feedback/bullet",
                json={
                    "brief_id": str(_BRIEF_ID),
                    "section_idx": 0,
                    "bullet_idx": 1,
                    "reaction": "helpful",
                },
                headers=_JWT_HEADERS,
            )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "id" in body
    assert "created_at" in body
    # id must be a non-empty string (UUID format)
    assert len(body["id"]) == 36


# ── test_brief_feedback_returns_201 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_brief_feedback_returns_201(settings: RagChatSettings) -> None:
    """POST /briefings/feedback/brief with valid star rating → 201 with id + created_at.

    WHY: verifies the whole-brief feedback happy path. Reaction must be one of
    "1"-"5"; the route must return 201 with a FeedbackResponse shape.
    """
    app = _make_app(settings)

    with patch(
        "rag_chat.application.use_cases.brief_feedback.BriefFeedbackUseCase.submit_brief_feedback",
        new_callable=AsyncMock,
        return_value=(_FEEDBACK_ID, _NOW),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/briefings/feedback/brief",
                json={
                    "brief_id": str(_BRIEF_ID),
                    "reaction": "4",
                },
                headers=_JWT_HEADERS,
            )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "id" in body
    assert "created_at" in body


# ── test_feedback_rejects_unknown_brief ───────────────────────────────────────


@pytest.mark.asyncio
async def test_feedback_rejects_unknown_brief(settings: RagChatSettings) -> None:
    """POST /feedback/bullet with a brief_id not owned by the user → 404.

    WHY: IDOR protection. BriefFeedbackUseCase raises BriefNotFoundError when the
    brief doesn't exist or belongs to another user. The route must convert this to
    HTTP 404 — not 403, to avoid leaking that the brief exists for another user.
    """
    app = _make_app(settings)

    with patch(
        "rag_chat.application.use_cases.brief_feedback.BriefFeedbackUseCase.submit_bullet_feedback",
        new_callable=AsyncMock,
        side_effect=BriefNotFoundError("Brief not found for user"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/briefings/feedback/bullet",
                json={
                    "brief_id": str(UUID("00000000-0000-0000-0000-000000000099")),
                    "section_idx": 0,
                    "bullet_idx": 0,
                    "reaction": "unhelpful",
                },
                headers=_JWT_HEADERS,
            )

    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert "Brief not found" in body.get("detail", "")


# ── test_bullet_feedback_invalid_reaction ─────────────────────────────────────


@pytest.mark.asyncio
async def test_bullet_feedback_invalid_reaction(settings: RagChatSettings) -> None:
    """POST /feedback/bullet with reaction='meh' → 422 (Literal validation failure).

    WHY: the BulletFeedbackRequest schema uses Literal["helpful", "unhelpful"].
    FastAPI validates Pydantic models before the route body runs, so an invalid
    reaction value must produce HTTP 422 Unprocessable Entity without reaching
    the use case at all.
    """
    app = _make_app(settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/briefings/feedback/bullet",
            json={
                "brief_id": str(_BRIEF_ID),
                "section_idx": 0,
                "bullet_idx": 0,
                "reaction": "meh",  # not in Literal["helpful", "unhelpful"]
            },
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 422, resp.text
