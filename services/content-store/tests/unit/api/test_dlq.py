"""Unit tests for DLQ admin endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from content_store.infrastructure.db.models import DeadLetterQueueModel

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_ADMIN_TOKEN = "test-admin-token"  # noqa: S105
_HEADERS = {"X-Admin-Token": _ADMIN_TOKEN}


def _make_dlq_entry(**overrides):
    defaults = {
        "dlq_id": uuid4(),
        "original_event_id": uuid4(),
        "topic": "content.article.stored.v1",
        "error_detail": "Serialization error",
        "status": "failed",
        "created_at": datetime.now(tz=UTC),
        "resolved_at": None,
        "resolution_note": None,
        "payload_avro": b"avro-bytes",
    }
    defaults.update(overrides)
    entry = DeadLetterQueueModel(**defaults)
    return entry


# ── Auth ─────────────────────────────────────────────────────────────────────


async def test_dlq_requires_admin_token(client):
    resp = await client.get("/admin/dlq")
    assert resp.status_code == 401


async def test_dlq_rejects_wrong_token(client):
    resp = await client.get("/admin/dlq", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


# ── List ─────────────────────────────────────────────────────────────────────


async def test_list_dlq_empty(app, client):
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.list_open.return_value = ([], 0)
        MockRepo.return_value = mock_repo

        resp = await client.get("/admin/dlq", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["entries"] == []


async def test_list_dlq_returns_entries(app, client):
    entry = _make_dlq_entry()
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.list_open.return_value = ([entry], 1)
        MockRepo.return_value = mock_repo

        resp = await client.get("/admin/dlq", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["entries"][0]["topic"] == "content.article.stored.v1"


# ── Get by ID ────────────────────────────────────────────────────────────────


async def test_get_dlq_entry_not_found(app, client):
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None
        MockRepo.return_value = mock_repo

        resp = await client.get(f"/admin/dlq/{uuid4()}", headers=_HEADERS)
        assert resp.status_code == 404


async def test_get_dlq_entry_found(app, client):
    entry = _make_dlq_entry()
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = entry
        MockRepo.return_value = mock_repo

        resp = await client.get(f"/admin/dlq/{entry.dlq_id}", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["error_detail"] == "Serialization error"


# ── Retry ────────────────────────────────────────────────────────────────────


async def test_retry_not_found(app, client):
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None
        MockRepo.return_value = mock_repo

        resp = await client.post(f"/admin/dlq/{uuid4()}/retry", headers=_HEADERS)
        assert resp.status_code == 404


async def test_retry_requeues(app, client):
    entry = _make_dlq_entry()
    new_id = uuid4()
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = entry
        mock_repo.requeue.return_value = new_id
        MockRepo.return_value = mock_repo

        resp = await client.post(f"/admin/dlq/{entry.dlq_id}/retry", headers=_HEADERS)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "requeued"
        assert body["new_event_id"] == str(new_id)


# ── Resolve ──────────────────────────────────────────────────────────────────


async def test_resolve_not_found(app, client):
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None
        MockRepo.return_value = mock_repo

        resp = await client.post(
            f"/admin/dlq/{uuid4()}/resolve",
            json={"note": "fixed"},
            headers=_HEADERS,
        )
        assert resp.status_code == 404


async def test_resolve_marks_resolved(app, client):
    entry = _make_dlq_entry()
    with patch("content_store.api.dlq.DLQRepository") as MockRepo:
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = entry
        mock_repo.mark_resolved = AsyncMock()
        MockRepo.return_value = mock_repo

        resp = await client.post(
            f"/admin/dlq/{entry.dlq_id}/resolve",
            json={"note": "manually fixed"},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"
