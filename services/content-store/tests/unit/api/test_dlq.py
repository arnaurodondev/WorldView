"""Unit tests for DLQ admin endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from content_store.api.dependencies import get_dlq_use_case
from content_store.application.ports.repositories import DLQEntryData

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

_ADMIN_TOKEN = "test-admin-token"  # noqa: S105
_HEADERS = {"X-Admin-Token": _ADMIN_TOKEN}


def _make_dlq_entry(**overrides) -> DLQEntryData:
    defaults = {
        "dlq_id": uuid4(),
        "original_event_id": uuid4(),
        "topic": "content.article.stored.v1",
        "error_detail": "Serialization error",
        "status": "failed",
        "created_at": datetime.now(tz=UTC),
        "resolved_at": None,
        "resolution_note": None,
    }
    defaults.update(overrides)
    return DLQEntryData(**defaults)


def _make_use_case_override(mock_uc):
    """Return a FastAPI dependency override that returns the mock use case."""

    def override():
        return mock_uc

    return override


# ── Auth ─────────────────────────────────────────────────────────────────────


async def test_dlq_requires_admin_token(client):
    resp = await client.get("/admin/dlq")
    assert resp.status_code == 401


async def test_dlq_rejects_wrong_token(client):
    resp = await client.get("/admin/dlq", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


# ── List ─────────────────────────────────────────────────────────────────────


async def test_list_dlq_empty(app, client):
    mock_uc = AsyncMock()
    mock_uc.list_open.return_value = ([], 0)
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.get("/admin/dlq", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["entries"] == []
    finally:
        app.dependency_overrides.clear()


async def test_list_dlq_returns_entries(app, client):
    entry = _make_dlq_entry()
    mock_uc = AsyncMock()
    mock_uc.list_open.return_value = ([entry], 1)
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.get("/admin/dlq", headers=_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["entries"][0]["topic"] == "content.article.stored.v1"
    finally:
        app.dependency_overrides.clear()


# ── Get by ID ────────────────────────────────────────────────────────────────


async def test_get_dlq_entry_not_found(app, client):
    mock_uc = AsyncMock()
    mock_uc.get_by_id.return_value = None
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.get(f"/admin/dlq/{uuid4()}", headers=_HEADERS)
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_get_dlq_entry_found(app, client):
    entry = _make_dlq_entry()
    mock_uc = AsyncMock()
    mock_uc.get_by_id.return_value = entry
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.get(f"/admin/dlq/{entry.dlq_id}", headers=_HEADERS)
        assert resp.status_code == 200
        assert resp.json()["error_detail"] == "Serialization error"
    finally:
        app.dependency_overrides.clear()


# ── Retry ────────────────────────────────────────────────────────────────────


async def test_retry_not_found(app, client):
    mock_uc = AsyncMock()
    mock_uc.get_by_id.return_value = None
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.post(f"/admin/dlq/{uuid4()}/retry", headers=_HEADERS)
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_retry_requeues(app, client):
    entry = _make_dlq_entry()
    new_id = uuid4()
    mock_uc = AsyncMock()
    mock_uc.get_by_id.return_value = entry
    mock_uc.requeue.return_value = new_id
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.post(f"/admin/dlq/{entry.dlq_id}/retry", headers=_HEADERS)
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "requeued"
        assert body["new_event_id"] == str(new_id)
    finally:
        app.dependency_overrides.clear()


# ── Resolve ──────────────────────────────────────────────────────────────────


async def test_resolve_not_found(app, client):
    mock_uc = AsyncMock()
    mock_uc.get_by_id.return_value = None
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.post(
            f"/admin/dlq/{uuid4()}/resolve",
            json={"note": "fixed"},
            headers=_HEADERS,
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_resolve_marks_resolved(app, client):
    entry = _make_dlq_entry()
    mock_uc = AsyncMock()
    mock_uc.get_by_id.return_value = entry
    mock_uc.mark_resolved = AsyncMock()
    app.dependency_overrides[get_dlq_use_case] = _make_use_case_override(mock_uc)
    try:
        resp = await client.post(
            f"/admin/dlq/{entry.dlq_id}/resolve",
            json={"note": "manually fixed"},
            headers=_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"
    finally:
        app.dependency_overrides.clear()
