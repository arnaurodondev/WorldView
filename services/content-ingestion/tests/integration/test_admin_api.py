"""Integration tests for the S4 admin API endpoints (T-A-4-04).

Validates CRUD operations on sources, trigger, and pipeline status
against a real PostgreSQL database via the FastAPI test client.

Requires live PostgreSQL.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.api.routes import admin, dlq, health
from content_ingestion.infrastructure.db.models import DeadLetterQueueModel
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import common.ids
import common.time

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("S4_TEST_DATABASE_URL", "postgresql").startswith("postgresql"),
        reason="Requires live PostgreSQL (set S4_TEST_DATABASE_URL)",
    ),
]

ADMIN_TOKEN = "test-admin-token-integration"  # noqa: S105


@pytest.fixture
def test_app(session_factory):
    """Create a minimal FastAPI app wired to the test DB session factory."""
    app = FastAPI()

    # Wire up app.state to match what dependencies expect
    settings = MagicMock()
    settings.admin_token = ADMIN_TOKEN
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.trigger_fn = AsyncMock()

    app.include_router(health.router, tags=["health"])
    app.include_router(admin.router)
    app.include_router(dlq.router)
    return app


@pytest.fixture
async def client(test_app):
    """Async HTTP test client."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth_headers():
    return {"X-Admin-Token": ADMIN_TOKEN}


# ── Source CRUD tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_source(client):
    """POST /api/v1/sources creates a source and returns it."""
    resp = await client.post(
        "/api/v1/sources",
        json={"name": "intg-eodhd", "source_type": "eodhd", "config": {"symbols": ["AAPL"]}, "enabled": True},
        headers=_auth_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "intg-eodhd"
    assert data["source_type"] == "eodhd"
    assert data["enabled"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_list_sources(client):
    """GET /api/v1/sources returns created sources."""
    # Create two sources
    await client.post(
        "/api/v1/sources",
        json={"name": "list-src-1", "source_type": "eodhd"},
        headers=_auth_headers(),
    )
    await client.post(
        "/api/v1/sources",
        json={"name": "list-src-2", "source_type": "finnhub"},
        headers=_auth_headers(),
    )

    resp = await client.get("/api/v1/sources", headers=_auth_headers())
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    names = {s["name"] for s in sources}
    assert "list-src-1" in names
    assert "list-src-2" in names


@pytest.mark.asyncio
async def test_update_source(client):
    """PUT /api/v1/sources/{id} updates source fields."""
    create_resp = await client.post(
        "/api/v1/sources",
        json={"name": "update-me", "source_type": "newsapi", "enabled": True},
        headers=_auth_headers(),
    )
    source_id = create_resp.json()["id"]

    update_resp = await client.put(
        f"/api/v1/sources/{source_id}",
        json={"enabled": False},
        headers=_auth_headers(),
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_trigger_source(client):
    """POST /api/v1/sources/{id}/trigger returns 202 and fires trigger_fn."""
    create_resp = await client.post(
        "/api/v1/sources",
        json={"name": "trigger-me", "source_type": "eodhd"},
        headers=_auth_headers(),
    )
    source_id = create_resp.json()["id"]

    trigger_resp = await client.post(
        f"/api/v1/sources/{source_id}/trigger",
        headers=_auth_headers(),
    )
    assert trigger_resp.status_code == 202
    assert trigger_resp.json()["status"] == "triggered"


@pytest.mark.asyncio
async def test_trigger_nonexistent_source_returns_404(client):
    """POST /api/v1/sources/{id}/trigger for missing source → 404."""
    fake_id = common.ids.new_uuid7()
    resp = await client.post(
        f"/api/v1/sources/{fake_id}/trigger",
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_pipeline_status(client):
    """GET /api/v1/status returns pipeline status summary."""
    # Create a source first
    await client.post(
        "/api/v1/sources",
        json={"name": "status-src", "source_type": "eodhd"},
        headers=_auth_headers(),
    )

    resp = await client.get("/api/v1/status", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert "sources" in data
    assert "outbox_pending" in data
    assert "dlq_count" in data
    assert data["outbox_pending"] >= 0
    assert data["dlq_count"] >= 0


# ── Auth tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_admin_token_returns_401(client):
    """Requests without X-Admin-Token are rejected."""
    resp = await client.get("/api/v1/sources")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_admin_token_returns_401(client):
    """Requests with wrong X-Admin-Token are rejected."""
    resp = await client.get("/api/v1/sources", headers={"X-Admin-Token": "wrong-token"})
    assert resp.status_code == 401


# ── DLQ API tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dlq_list_empty(client):
    """GET /admin/dlq returns empty list when no DLQ entries exist."""
    resp = await client.get("/admin/dlq", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_dlq_lifecycle(client, session_factory):
    """Full DLQ lifecycle: create entry → list → resolve."""
    # Seed a DLQ entry directly in the DB
    dlq_id = common.ids.new_uuid7()
    event_id = common.ids.new_uuid7()

    async with session_factory() as session:
        session.add(
            DeadLetterQueueModel(
                dlq_id=dlq_id,
                original_event_id=event_id,
                topic="content.article.raw.v1",
                payload_avro=b"fake-avro-bytes",
                error_detail="Test error",
                status="failed",
            )
        )
        await session.commit()

    # List DLQ entries
    resp = await client.get("/admin/dlq", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["entries"][0]["dlq_id"] == str(dlq_id)

    # Get single entry
    resp = await client.get(f"/admin/dlq/{dlq_id}", headers=_auth_headers())
    assert resp.status_code == 200
    assert resp.json()["error_detail"] == "Test error"

    # Resolve
    resp = await client.post(
        f"/admin/dlq/{dlq_id}/resolve",
        json={"note": "Fixed manually"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"

    # Verify resolved — no longer in open list
    resp = await client.get("/admin/dlq", headers=_auth_headers())
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_dlq_retry_creates_outbox_event(client, session_factory):
    """POST /admin/dlq/{id}/retry requeues entry to outbox."""
    from content_ingestion.infrastructure.db.models import OutboxEventModel
    from sqlalchemy import func, select

    dlq_id = common.ids.new_uuid7()
    event_id = common.ids.new_uuid7()

    async with session_factory() as session:
        session.add(
            DeadLetterQueueModel(
                dlq_id=dlq_id,
                original_event_id=event_id,
                topic="content.article.raw.v1",
                payload_avro=b"retry-test-bytes",
                error_detail="Retry test",
                status="failed",
            )
        )
        await session.commit()

    resp = await client.post(f"/admin/dlq/{dlq_id}/retry", headers=_auth_headers())
    assert resp.status_code == 202
    assert resp.json()["status"] == "requeued"

    # Verify new outbox event created
    async with session_factory() as session:
        count = (await session.execute(select(func.count()).select_from(OutboxEventModel))).scalar()
        assert count == 1
