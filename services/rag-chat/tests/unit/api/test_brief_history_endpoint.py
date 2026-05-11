"""Unit tests for GET /api/v1/briefings/morning/history (PLAN-0066 Wave B T-W10-B-03).

Tests verify:
  - 200 response with valid JWT and mocked archive
  - 401 without auth header
  - 422 validation error when page_size > 50 (Query constraint)

WHY mock read_factory: the history endpoint uses get_brief_archive_dep which
calls request.app.state.read_factory() to create a session. In unit tests we
patch read_factory with a callable that returns an AsyncMock session so no real
DB connection is needed.
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


def _make_mock_session() -> MagicMock:
    """Create a mock AsyncSession that accepts close() calls."""
    session = MagicMock()
    session.close = AsyncMock()
    return session


def _make_app_with_archive(
    settings: RagChatSettings,
    archive_records: list | None = None,
    archive_total: int = 0,
) -> object:
    """Create a test app with mocked read_factory and BriefArchiveRepository.

    WHY patch get_brief_archive_dep: the dependency calls read_factory() to create
    a session, then constructs BriefArchiveRepository(session=session). In unit
    tests we don't have a real DB, so we inject a mock archive directly via
    dependency_overrides.

    Args:
        settings: service settings with skip_verification=True.
        archive_records: list of UserBriefRecord objects the mock archive returns.
        archive_total: total row count returned by get_history().
    """
    from rag_chat.api.dependencies import get_brief_archive_dep

    app = create_app(settings)

    # Mock briefing UC + valkey so the other routes don't crash during app setup
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

    # Build the mock archive
    mock_archive = MagicMock()
    mock_archive.get_history = AsyncMock(return_value=(archive_records or [], archive_total))
    mock_archive.get_latest = AsyncMock(return_value=[])
    mock_archive.get_by_id = AsyncMock(return_value=None)

    # Override the DI dependency so the route receives the mock archive
    async def _mock_archive_dep():  # type: ignore[return]
        yield mock_archive

    app.dependency_overrides[get_brief_archive_dep] = _mock_archive_dep

    # read_factory must be callable (session = read_factory()) — set a no-op mock
    # so the DI dependency doesn't crash if it's called before the override.
    app.state.read_factory = lambda: _make_mock_session()

    return app


# ── T-W10-B-03: 200 with valid JWT ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_endpoint_returns_200(settings: RagChatSettings) -> None:
    """GET /api/v1/briefings/morning/history with valid JWT → 200 with pagination envelope."""
    from rag_chat.application.ports.brief_archive import UserBriefRecord

    # Create two sample records to return from the mock archive
    records = [
        UserBriefRecord(
            id=_BRIEF_ID,
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            brief_type="morning",
            entity_id=None,
            generated_at=_NOW,
            headline="Markets steady amid AI rally.",
            lead="Tech stocks led gains.",
            sections_json=[],
            citations_json=[],
            confidence=0.85,
            source_version="v2",
        )
    ]

    app = _make_app_with_archive(settings, archive_records=records, archive_total=1)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/briefings/morning/history",
            headers=_JWT_HEADERS,
        )

    assert resp.status_code == 200
    body = resp.json()

    # Verify pagination envelope shape
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert body["total"] == 1
    assert body["page"] == 0
    assert body["page_size"] == 10

    # Verify item fields
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(_BRIEF_ID)
    assert item["headline"] == "Markets steady amid AI rally."
    assert item["lead"] == "Tech stocks led gains."
    assert item["confidence"] == 0.85
    assert "generated_at" in item


# ── T-W10-B-03: 401 without auth header ──────────────────────────────────────


@pytest.mark.asyncio
async def test_history_requires_auth(settings: RagChatSettings) -> None:
    """GET /api/v1/briefings/morning/history without X-Internal-JWT → 401.

    WHY: InternalJWTMiddleware sets request.state.user_id from the JWT. The route
    calls _extract_user_id() which raises 401 when user_id is absent.
    """
    app = _make_app_with_archive(settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/briefings/morning/history")
        # WHY 401: no X-Internal-JWT header → user_id not in request.state
        assert resp.status_code == 401


# ── T-W10-B-03: page_size > 50 → 422 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_page_size_capped_at_50(settings: RagChatSettings) -> None:
    """page_size=100 → 422 (Query(le=50) constraint violated).

    WHY: FastAPI's Query(le=50) rejects values > 50 before the route body runs,
    returning 422 Unprocessable Entity. This prevents runaway queries.
    """
    app = _make_app_with_archive(settings)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/briefings/morning/history?page_size=100",
            headers=_JWT_HEADERS,
        )
        assert resp.status_code == 422
