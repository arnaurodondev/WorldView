"""Unit tests for the /api/v1/threads endpoints (T-D-4-02).

All tests use dependency_overrides to avoid requiring a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
_THREAD_ID = UUID("01950000-0000-7000-8000-000000000001")  # fake UUIDv7-like

# InternalJWTMiddleware requires X-Internal-JWT; with no public key loaded (unit tests,
# no lifespan) it decodes without signature verification and passes through.
_INTERNAL_JWT = _jwt.encode(
    {"sub": str(_USER_ID), "tenant_id": str(_TENANT_ID), "role": "user"},
    "secret",
    algorithm="HS256",
)

_AUTH_HEADERS = {
    "X-Tenant-Id": str(_TENANT_ID),
    "X-User-Id": str(_USER_ID),
    "X-Internal-JWT": _INTERNAL_JWT,
}


def _make_mock_uow() -> MagicMock:
    uow = MagicMock()
    uow.threads = MagicMock()
    uow.threads.create = AsyncMock(return_value=None)
    uow.threads.get = AsyncMock(return_value=None)
    uow.threads.list_active = AsyncMock(return_value=([], 0))
    uow.threads.soft_delete = AsyncMock(return_value=datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC))
    uow.commit = AsyncMock(return_value=None)
    return uow


def _make_thread(thread_id: UUID = _THREAD_ID) -> object:
    from rag_chat.domain.entities.conversation import ConversationThread

    now = datetime(2026, 4, 6, 10, 0, 0, tzinfo=UTC)
    return ConversationThread(
        thread_id=thread_id,
        tenant_id=_TENANT_ID,
        user_id=_USER_ID,
        created_at=now,
        updated_at=now,
        title="Test thread",
        entity_ids=(),
        messages=(),
        archived_at=None,
    )


@pytest.fixture
def mock_uow() -> MagicMock:
    return _make_mock_uow()


@pytest.fixture
def app_with_mocks(app: object, mock_uow: MagicMock) -> object:
    """App with UoW and auth dependencies overridden for unit tests."""
    from rag_chat.api.dependencies import get_auth_context, get_read_uow, get_uow

    async def override_uow():  # type: ignore[return]
        yield mock_uow

    async def override_auth() -> tuple[UUID, UUID]:
        return (_TENANT_ID, _USER_ID)

    app.dependency_overrides[get_uow] = override_uow  # type: ignore[attr-defined]
    app.dependency_overrides[get_read_uow] = override_uow  # type: ignore[attr-defined]
    app.dependency_overrides[get_auth_context] = override_auth  # type: ignore[attr-defined]
    yield app
    app.dependency_overrides.clear()  # type: ignore[attr-defined]


@pytest.fixture
def app_no_auth_override(app: object, mock_uow: MagicMock) -> object:
    """App with only UoW overridden; auth dependency is NOT overridden."""
    from rag_chat.api.dependencies import get_read_uow, get_uow

    async def override_uow():  # type: ignore[return]
        yield mock_uow

    app.dependency_overrides[get_uow] = override_uow  # type: ignore[attr-defined]
    app.dependency_overrides[get_read_uow] = override_uow  # type: ignore[attr-defined]
    yield app
    app.dependency_overrides.clear()  # type: ignore[attr-defined]


# ── POST /api/v1/threads ──────────────────────────────────────────────────────


class TestCreateThreadEndpoint:
    async def test_create_thread_endpoint(self, app_with_mocks: object) -> None:
        """POST /api/v1/threads with valid body → 201 with thread_id and created_at."""
        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/threads",
                json={"title": "My analysis", "entity_ids": []},
                headers=_AUTH_HEADERS,
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "thread_id" in data
        assert "created_at" in data
        assert data["title"] == "My analysis"


# ── GET /api/v1/threads ───────────────────────────────────────────────────────


class TestListThreadsEndpoint:
    async def test_list_threads_endpoint(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """GET /api/v1/threads → 200 with threads list and total."""
        thread = _make_thread()
        mock_uow.threads.list_active = AsyncMock(return_value=([thread], 1))

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/threads?limit=10&offset=0", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["threads"]) == 1
        assert data["threads"][0]["thread_id"] == str(_THREAD_ID)

    async def test_list_threads_empty(self, app_with_mocks: object) -> None:
        """GET /api/v1/threads with no threads → 200, total=0, threads=[]."""
        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/threads", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["threads"] == []


# ── GET /api/v1/threads/{thread_id} ──────────────────────────────────────────


class TestGetThreadEndpoint:
    async def test_get_thread_endpoint_not_found(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """GET /api/v1/threads/{id} for unknown thread → 404."""
        mock_uow.threads.get = AsyncMock(return_value=None)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 404

    async def test_get_thread_endpoint_found(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """GET /api/v1/threads/{id} for existing thread → 200 with messages list."""
        thread = _make_thread()
        mock_uow.threads.get = AsyncMock(return_value=thread)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == str(_THREAD_ID)
        assert data["messages"] == []


# ── DELETE /api/v1/threads/{thread_id} ───────────────────────────────────────


class TestDeleteThreadEndpoint:
    async def test_delete_thread_endpoint(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """DELETE /api/v1/threads/{id} for owned thread → 200 with archived_at."""

        archived_at = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
        mock_uow.threads.soft_delete = AsyncMock(return_value=archived_at)

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == str(_THREAD_ID)
        assert "archived_at" in data

    async def test_delete_thread_not_found(self, app_with_mocks: object, mock_uow: MagicMock) -> None:
        """DELETE /api/v1/threads/{id} for unknown thread → 404."""
        from rag_chat.domain.errors import ThreadNotFoundError

        mock_uow.threads.soft_delete = AsyncMock(side_effect=ThreadNotFoundError("not found"))

        transport = ASGITransport(app=app_with_mocks)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/threads/{_THREAD_ID}", headers=_AUTH_HEADERS)

        assert resp.status_code == 404


# ── Auth header enforcement ───────────────────────────────────────────────────


class TestThreadsAuthHeaders:
    async def test_threads_require_auth_headers(self, app_no_auth_override: object) -> None:
        """POST /api/v1/threads without X-Tenant-Id/X-User-Id → 401."""
        transport = ASGITransport(app=app_no_auth_override)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/threads",
                json={"title": "test"},
                # No auth headers
            )

        assert resp.status_code == 401

    async def test_list_requires_auth_headers(self, app_no_auth_override: object) -> None:
        """GET /api/v1/threads without auth headers → 401."""
        transport = ASGITransport(app=app_no_auth_override)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/threads")

        assert resp.status_code == 401
