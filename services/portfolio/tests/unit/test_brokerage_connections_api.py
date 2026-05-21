"""Unit tests for brokerage connections API routes (PRD-0022 force-sync endpoint).

Tests POST /api/v1/brokerage-connections/{connection_id}/sync:
  - 202 for ACTIVE connection
  - 202 for ERROR connection (retry is valid)
  - 404 for unknown connection_id
  - 403 for connection owned by a different user
  - 422 for DISCONNECTED connection
  - 422 for PENDING connection

The tests override the ``get_read_uow`` dependency so no DB is required.
InternalJWTMiddleware is bypassed with ``skip_verification=True`` (set via env var)
and a test JWT carrying the desired user_id/tenant_id is sent in X-Internal-JWT,
which is the same approach used by integration test helpers.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import jwt as _jwt
import pytest
from httpx import ASGITransport, AsyncClient
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.enums import ConnectionStatus

from tests.unit.fakes import FakeUnitOfWork

# Enable skip_verification BEFORE any portfolio module imports it via Settings.
# The PORTFOLIO_ prefix applies because Settings has env_prefix="PORTFOLIO_".
os.environ["PORTFOLIO_INTERNAL_JWT_SKIP_VERIFICATION"] = "true"
os.environ.setdefault("PORTFOLIO_STORAGE_ACCESS_KEY", "minioadmin-test")
os.environ.setdefault("PORTFOLIO_STORAGE_SECRET_KEY", "minioadmin-test")

pytestmark = pytest.mark.unit

# ── Constants ─────────────────────────────────────────────────────────────────

_USER_ID = uuid.uuid4()
_TENANT_ID = uuid.uuid4()
_OTHER_USER_ID = uuid.uuid4()  # used for 403 tests

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_internal_jwt(
    user_id: uuid.UUID = _USER_ID,
    tenant_id: uuid.UUID = _TENANT_ID,
    role: str = "user",
) -> str:
    """Build a test X-Internal-JWT token.

    With ``skip_verification=True`` (set above), InternalJWTMiddleware decodes
    this token WITHOUT signature verification.  The sub/tenant_id claims are
    written to request.state so _require_user_headers() can extract them.
    """
    payload = {
        "iss": "worldview-gateway",
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return _jwt.encode(payload, "test-secret-not-verified", algorithm="HS256")


def _make_connection(
    *,
    connection_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    status: ConnectionStatus = ConnectionStatus.ACTIVE,
) -> BrokerageConnection:
    """Build a minimal BrokerageConnection for test seeding."""
    return BrokerageConnection(
        id=connection_id or uuid.uuid4(),
        tenant_id=tenant_id or _TENANT_ID,
        user_id=user_id or _USER_ID,
        portfolio_id=uuid.uuid4(),
        snaptrade_user_id="snap-user",
        snaptrade_user_secret="snap-secret",
        snaptrade_tos_accepted_at=None,
        status=status,
    )


class _InMemoryValkey:
    """Tiny in-memory stand-in for ValkeyClient.set_nx with TTL ignored.

    REQ-002c: the brokerage-sync trigger route uses ``set_nx(key, "1", ex=300)``
    as its only Valkey contact. We expose just that method (plus ``__init__``
    to hold the store) so the test can assert "second POST does not enqueue
    a second background task" by observing the set_nx return value over time.
    """

    def __init__(self) -> None:
        self._store: set[str] = set()
        self.set_nx_calls: list[str] = []

    async def set_nx(self, key: str, value: str, ex: int) -> bool:  # — match ValkeyClient signature
        self.set_nx_calls.append(key)
        if key in self._store:
            return False
        self._store.add(key)
        return True


def _build_test_app(uow: FakeUnitOfWork, valkey_client: _InMemoryValkey | None = None) -> Any:
    """Build a test Portfolio app with:

    - All DB I/O stubbed via ``get_read_uow`` override → FakeUnitOfWork
    - app.state.session_factory / brokerage_client / settings set to mocks so
      that ``_run_single_sync`` (background task) can construct a worker without
      hitting the real database.

    ``INTERNAL_JWT_SKIP_VERIFICATION=true`` is already set at module level so
    InternalJWTMiddleware accepts unsigned test JWTs.
    """
    from portfolio.api.dependencies import get_read_uow
    from portfolio.app import create_app

    app = create_app()

    # Override the read UoW so the route handler queries the FakeUnitOfWork
    async def _fake_read_uow() -> AsyncGenerator[FakeUnitOfWork, None]:  # type: ignore[override]
        yield uow

    app.dependency_overrides[get_read_uow] = _fake_read_uow

    # Provide minimal app.state values so _run_single_sync can construct a worker
    # (these are normally set by the lifespan; we mock them here for unit tests).
    app.state.session_factory = MagicMock()
    app.state.brokerage_client = MagicMock()
    app.state.settings = MagicMock()
    app.state.snaptrade_cipher = None
    # REQ-002c: tests that exercise the Idempotency-Key path inject an
    # in-memory Valkey stub so we can observe set_nx behaviour. The route
    # tolerates ``None`` (treats it as "Valkey unavailable, fall back to
    # no dedup") so non-idempotency tests still pass without one.
    if valkey_client is not None:
        app.state.valkey_client = valkey_client

    return app


# ── 202: ACTIVE connection ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_sync_active_connection_returns_202() -> None:
    """POST /sync on an ACTIVE connection → 202 + {"status": "syncing"}."""
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.ACTIVE)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    app = _build_test_app(uow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt()},
        )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "syncing"
    assert body["connection_id"] == str(conn_id)


# ── 202: ERROR connection ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_sync_error_connection_returns_202() -> None:
    """POST /sync on an ERROR connection → 202 (retry is valid, not blocked)."""
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.ERROR)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    app = _build_test_app(uow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt()},
        )

    assert resp.status_code == 202


# ── 404: unknown connection_id ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_sync_unknown_connection_returns_404() -> None:
    """POST /sync with a connection_id not in the tenant → 404."""
    uow = FakeUnitOfWork()  # empty — no connections

    app = _build_test_app(uow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{uuid.uuid4()}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt()},
        )

    assert resp.status_code == 404


# ── 403: connection owned by a different user ──────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_sync_different_user_returns_403() -> None:
    """POST /sync for a connection belonging to _OTHER_USER_ID while authenticated
    as _USER_ID → 403 (tenant isolation enforced at the route layer).
    """
    conn_id = uuid.uuid4()
    # Connection belongs to _OTHER_USER_ID; JWT claims _USER_ID
    conn = _make_connection(
        connection_id=conn_id,
        user_id=_OTHER_USER_ID,  # different owner
        tenant_id=_TENANT_ID,  # same tenant — so get() finds it
        status=ConnectionStatus.ACTIVE,
    )

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    # JWT carries _USER_ID — NOT the owner of the connection
    app = _build_test_app(uow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt(user_id=_USER_ID, tenant_id=_TENANT_ID)},
        )

    assert resp.status_code == 403


# ── 422: DISCONNECTED connection ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_sync_disconnected_connection_returns_422() -> None:
    """POST /sync on a DISCONNECTED connection → 422 (user revoked access)."""
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.DISCONNECTED)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    app = _build_test_app(uow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt()},
        )

    assert resp.status_code == 422
    body = resp.json()
    assert "not active" in body.get("detail", "").lower()


# ── 422: PENDING connection ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_sync_pending_connection_returns_422() -> None:
    """POST /sync on a PENDING connection → 422 (OAuth flow not yet completed)."""
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.PENDING)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    app = _build_test_app(uow)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt()},
        )

    assert resp.status_code == 422
    body = resp.json()
    assert "not active" in body.get("detail", "").lower()


# ── REQ-002c: idempotent POST /brokerage-connections/{id}/sync ───────────────


@pytest.mark.asyncio
async def test_trigger_sync_idempotency_key_first_call_acquires_lock() -> None:
    """REQ-002c — first POST with an Idempotency-Key returns 202 + status="syncing"
    and writes the Valkey dedup key.
    """
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.ACTIVE)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    valkey = _InMemoryValkey()
    app = _build_test_app(uow, valkey_client=valkey)
    key = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={
                "X-Internal-JWT": _make_internal_jwt(),
                "Idempotency-Key": key,
            },
        )

    assert resp.status_code == 202
    assert resp.json()["status"] == "syncing"
    # Valkey set_nx was called once with the expected key shape.
    assert len(valkey.set_nx_calls) == 1
    assert valkey.set_nx_calls[0] == f"brokerage_sync_trigger:{_TENANT_ID}:{conn_id}:{key}"


@pytest.mark.asyncio
async def test_trigger_sync_idempotency_key_replay_returns_already_queued() -> None:
    """REQ-002c — second POST with the same key returns 202 + status="already_queued"
    and does NOT enqueue a second background task.
    """
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.ACTIVE)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    valkey = _InMemoryValkey()
    app = _build_test_app(uow, valkey_client=valkey)
    key = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp1 = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt(), "Idempotency-Key": key},
        )
        resp2 = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt(), "Idempotency-Key": key},
        )

    assert resp1.status_code == 202
    assert resp1.json()["status"] == "syncing"
    assert resp2.status_code == 202
    body = resp2.json()
    assert body["status"] == "already_queued"
    assert body["idempotency_key"] == key
    # Valkey saw both attempts; only the first acquired the lock.
    assert len(valkey.set_nx_calls) == 2


@pytest.mark.asyncio
async def test_trigger_sync_invalid_idempotency_key_returns_422() -> None:
    """REQ-002c — non-UUID Idempotency-Key value → 422."""
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.ACTIVE)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    valkey = _InMemoryValkey()
    app = _build_test_app(uow, valkey_client=valkey)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={
                "X-Internal-JWT": _make_internal_jwt(),
                "Idempotency-Key": "not-a-uuid",
            },
        )

    assert resp.status_code == 422
    # No Valkey calls — validation happens before the dedup write.
    assert valkey.set_nx_calls == []


@pytest.mark.asyncio
async def test_trigger_sync_no_idempotency_key_is_backcompat() -> None:
    """REQ-002c — missing Idempotency-Key header keeps original behaviour: 202
    + status="syncing" and no Valkey contact at all.
    """
    conn_id = uuid.uuid4()
    conn = _make_connection(connection_id=conn_id, status=ConnectionStatus.ACTIVE)

    uow = FakeUnitOfWork()
    await uow.brokerage_connections.save(conn)

    valkey = _InMemoryValkey()
    app = _build_test_app(uow, valkey_client=valkey)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/brokerage-connections/{conn_id}/sync",
            headers={"X-Internal-JWT": _make_internal_jwt()},
        )

    assert resp.status_code == 202
    assert resp.json()["status"] == "syncing"
    # No header → no Valkey contact.
    assert valkey.set_nx_calls == []
