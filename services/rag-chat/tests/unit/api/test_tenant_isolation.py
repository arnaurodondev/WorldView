"""Regression tests: cross-tenant thread isolation (PLAN-0031 Wave E-1).

Verifies that S8's thread ownership boundary is enforced at the API layer:
- Tenant B CANNOT read Tenant A's thread (→ 404)
- Tenant B CANNOT delete (write to) Tenant A's thread (→ 404)
- Tenant A CAN read their own thread (→ 200, baseline regression)

The isolation mechanism: every use case passes ``tenant_id`` from the JWT auth
context to the repository; the repository filters by ``tenant_id`` in the WHERE
clause, so a mismatched tenant sees ``None`` → ``ThreadNotFoundError`` → 404.

These tests use distinct tenant/user UUID pairs and a mock UoW whose
``threads.get`` / ``threads.soft_delete`` only returns a result when called
with the correct (owning) tenant_id. This simulates the DB-level row filter
without requiring a real database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.unit

# ── Two distinct tenants with non-overlapping UUIDs ──────────────────────────

_TENANT_A_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
_USER_A_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaab")

_TENANT_B_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
_USER_B_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbc0")

# Thread owned by Tenant A
_THREAD_ID = UUID("01950000-0000-7000-8000-000000000099")

_NOW = datetime(2026, 4, 21, 10, 0, 0, tzinfo=UTC)


# ── JWT helpers ──────────────────────────────────────────────────────────────


def _jwt_for(tenant_id: UUID, user_id: UUID) -> str:
    """Build an HS256 JWT for the given tenant/user.

    InternalJWTMiddleware decodes without signature verification when
    public_key is None (unit test environment), so HS256 with any secret works.
    """
    return _jwt.encode(
        {"sub": str(user_id), "tenant_id": str(tenant_id), "role": "user"},
        "test-secret",
        algorithm="HS256",
    )


_JWT_TENANT_A = _jwt_for(_TENANT_A_ID, _USER_A_ID)
_JWT_TENANT_B = _jwt_for(_TENANT_B_ID, _USER_B_ID)

_HEADERS_A = {"X-Internal-JWT": _JWT_TENANT_A}
_HEADERS_B = {"X-Internal-JWT": _JWT_TENANT_B}


# ── Thread factory ───────────────────────────────────────────────────────────


def _make_thread_for_tenant_a() -> Any:
    """Create a ConversationThread owned by Tenant A."""
    from rag_chat.domain.entities.conversation import ConversationThread

    return ConversationThread(
        thread_id=_THREAD_ID,
        tenant_id=_TENANT_A_ID,
        user_id=_USER_A_ID,
        created_at=_NOW,
        updated_at=_NOW,
        title="Tenant A's private thread",
        entity_ids=(),
        messages=(),
        archived_at=None,
    )


# ── Mock UoW that enforces tenant-scoped returns ─────────────────────────────


def _make_tenant_scoped_uow() -> MagicMock:
    """Build a mock UoW whose ``threads.get`` and ``threads.soft_delete`` only
    return a result when called with Tenant A's credentials (simulating the
    DB-level ``WHERE tenant_id = :tid`` filter).
    """
    uow = MagicMock()
    thread = _make_thread_for_tenant_a()

    # --- threads.get(thread_id, user_id, tenant_id=...) ---
    # Returns the thread only if tenant_id matches Tenant A; otherwise None.
    async def _scoped_get(
        thread_id: UUID,
        user_id: UUID,
        tenant_id: UUID | None = None,
    ) -> Any:
        if tenant_id == _TENANT_A_ID and user_id == _USER_A_ID and thread_id == _THREAD_ID:
            return thread
        return None

    uow.threads = MagicMock()
    uow.threads.get = AsyncMock(side_effect=_scoped_get)
    uow.threads.list_active = AsyncMock(return_value=([], 0))

    # --- threads.soft_delete(thread_id, user_id, tenant_id) ---
    # Returns archived_at only for Tenant A; raises ThreadNotFoundError for others.
    from rag_chat.domain.errors import ThreadNotFoundError

    async def _scoped_soft_delete(
        thread_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> datetime:
        if tenant_id == _TENANT_A_ID and user_id == _USER_A_ID and thread_id == _THREAD_ID:
            return _NOW
        raise ThreadNotFoundError(f"Thread {thread_id} not found")

    uow.threads.soft_delete = AsyncMock(side_effect=_scoped_soft_delete)
    uow.commit = AsyncMock(return_value=None)
    return uow


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def tenant_scoped_uow() -> MagicMock:
    return _make_tenant_scoped_uow()


@pytest.fixture
def app_tenant_scoped(app: object, tenant_scoped_uow: MagicMock) -> object:
    """App with tenant-scoped mock UoW; auth is NOT overridden — the real
    ``get_auth_context`` dependency reads tenant_id/user_id from the JWT
    in the ``X-Internal-JWT`` header (set by InternalJWTMiddleware).
    """
    from rag_chat.api.dependencies import get_read_uow, get_uow

    async def override_uow():  # type: ignore[return]
        yield tenant_scoped_uow

    app.dependency_overrides[get_uow] = override_uow  # type: ignore[attr-defined]
    app.dependency_overrides[get_read_uow] = override_uow  # type: ignore[attr-defined]
    yield app
    app.dependency_overrides.clear()  # type: ignore[attr-defined]


# ── Tests ────────────────────────────────────────────────────────────────────


class TestCrossTenantThreadIsolation:
    """Verify that S8 threads are isolated by tenant_id at the API layer.

    The underlying mechanism: ``GetThreadUseCase`` / ``DeleteThreadUseCase``
    pass ``tenant_id`` (from JWT auth context) to the repository, which
    filters ``WHERE tenant_id = :tid``. A mismatched tenant gets None
    back → ``ThreadNotFoundError`` → HTTP 404. The 404 (not 403) is
    intentional: it prevents an attacker from enumerating thread IDs
    belonging to other tenants.
    """

    async def test_cross_tenant_thread_read_denied(self, app_tenant_scoped: object) -> None:
        """Tenant B cannot read Tenant A's thread — must receive 404."""
        transport = ASGITransport(app=app_tenant_scoped)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Tenant B tries to read Tenant A's thread
            resp = await client.get(
                f"/api/v1/threads/{_THREAD_ID}",
                headers=_HEADERS_B,
            )

        # 404 (not 403) — prevents thread ID enumeration
        assert resp.status_code == 404

    async def test_cross_tenant_message_write_denied(self, app_tenant_scoped: object) -> None:
        """Tenant B cannot delete (write to) Tenant A's thread — must receive 404.

        This tests the write path: ``DeleteThreadUseCase`` also enforces
        tenant_id filtering via ``soft_delete(thread_id, user_id, tenant_id)``.
        """
        transport = ASGITransport(app=app_tenant_scoped)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Tenant B tries to delete Tenant A's thread
            resp = await client.delete(
                f"/api/v1/threads/{_THREAD_ID}",
                headers=_HEADERS_B,
            )

        assert resp.status_code == 404

    async def test_same_tenant_thread_access_allowed(self, app_tenant_scoped: object) -> None:
        """Tenant A can read their own thread — baseline regression."""
        transport = ASGITransport(app=app_tenant_scoped)  # type: ignore[arg-type]
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Tenant A reads their own thread
            resp = await client.get(
                f"/api/v1/threads/{_THREAD_ID}",
                headers=_HEADERS_A,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == str(_THREAD_ID)
        assert data["title"] == "Tenant A's private thread"
