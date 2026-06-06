"""E2E workflow tests for the Alert service (S10).

Tests the REST API endpoints (pending alerts, acknowledge, DLQ) against a live
alert_db database. All tests use ASGI transport (in-process).

Run with:
    NLP_PIPELINE_E2E_DATABASE_URL is not required.
    ALERT_E2E_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:55433/alert_db \\
    pytest services/alert/tests/e2e/ -v -m e2e
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

# PRD-0025: user_id resolves from the JWT, not query params. Seeded test data
# MUST use the JWT's user_id (E2E_USER_ID) or the GET filters them out.
from .conftest import E2E_USER_ID  # type: ignore[import]

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_alert(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID | None = None,
    alert_type: str = "SIGNAL",
    source_topic: str = "nlp.signal.detected.v1",
    dedup_key: str | None = None,
) -> uuid.UUID:
    """Insert an alert row. Returns alert_id."""
    alert_id = uuid.uuid4()
    entity_id = entity_id or uuid.uuid4()
    dedup_key = dedup_key or f"signal:{entity_id}:{uuid.uuid4().hex[:8]}"
    await session.execute(
        text("""
            INSERT INTO alerts (alert_id, entity_id, alert_type, source_event_id,
                                source_topic, payload, dedup_key, created_at)
            VALUES (:aid, :eid, :atype, :seid, :stopic, CAST(:payload AS JSONB), :dkey, :now)
        """),
        {
            "aid": str(alert_id),
            "eid": str(entity_id),
            "atype": alert_type,
            "seid": str(uuid.uuid4()),
            "stopic": source_topic,
            "payload": '{"confidence": 0.9, "signal_type": "BREAKOUT"}',
            "dkey": dedup_key,
            "now": datetime.now(tz=UTC),
        },
    )
    await session.commit()
    return alert_id


async def _seed_pending_alert(
    session: AsyncSession,
    alert_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Insert a pending_alerts row for a given user. Returns pending_id."""
    pending_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO pending_alerts (pending_id, alert_id, user_id, created_at)
            VALUES (:pid, :aid, :uid, :now)
        """),
        {
            "pid": str(pending_id),
            "aid": str(alert_id),
            "uid": str(user_id),
            "now": datetime.now(tz=UTC),
        },
    )
    await session.commit()
    return pending_id


# ── Health / observability ────────────────────────────────────────────────────


async def test_healthz_always_returns_200(e2e_client: AsyncClient) -> None:
    """GET /healthz returns 200 with status ok."""
    resp = await e2e_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_responds(e2e_client: AsyncClient) -> None:
    """GET /readyz returns 200 or 503."""
    resp = await e2e_client.get("/readyz")
    assert resp.status_code in {200, 503}


async def test_metrics_returns_prometheus_format(e2e_client: AsyncClient) -> None:
    """GET /metrics returns Prometheus text format."""
    resp = await e2e_client.get("/metrics")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "text/plain" in ct or "openmetrics" in ct or resp.text.startswith("#")


# ── GET /api/v1/alerts/pending ────────────────────────────────────────────────


async def test_pending_alerts_empty_for_new_user(e2e_client: AsyncClient) -> None:
    """GET /api/v1/alerts/pending for a brand new user returns empty list."""
    user_id = uuid.uuid4()
    resp = await e2e_client.get(f"/api/v1/alerts/pending?user_id={user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["alerts"] == []
    assert data["total"] == 0


async def test_pending_alerts_query_user_id_is_ignored(e2e_client: AsyncClient) -> None:
    """PRD-0025 update — user_id is read from the X-Internal-JWT claim, not a
    query param. Passing user_id=... in the URL is harmless (FastAPI just
    ignores unknown query args) and the endpoint resolves the user from the
    JWT context. We assert 200 + empty result, not 422.
    """
    resp = await e2e_client.get("/api/v1/alerts/pending")
    assert resp.status_code == 200
    body = resp.json()
    assert body["alerts"] == []
    assert body["total"] == 0


async def test_pending_alerts_query_user_id_value_is_ignored(e2e_client: AsyncClient) -> None:
    """Passing a bogus user_id query value does NOT trip 422 because the route
    does not declare user_id as a query param (it reads from JWT)."""
    resp = await e2e_client.get("/api/v1/alerts/pending?user_id=not-a-uuid")
    assert resp.status_code == 200


async def test_pending_alerts_pagination_validation(e2e_client: AsyncClient) -> None:
    """GET /api/v1/alerts/pending validates limit/offset boundaries."""
    user_id = uuid.uuid4()
    resp = await e2e_client.get(f"/api/v1/alerts/pending?user_id={user_id}&limit=0")
    assert resp.status_code == 422

    resp = await e2e_client.get(f"/api/v1/alerts/pending?user_id={user_id}&limit=201")
    assert resp.status_code == 422

    resp = await e2e_client.get(f"/api/v1/alerts/pending?user_id={user_id}&offset=-1")
    assert resp.status_code == 422


async def test_pending_alerts_returns_seeded_alert(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """GET /api/v1/alerts/pending returns seeded pending alert for the correct user."""
    # PRD-0025: user_id comes from JWT, so seed alerts under the JWT's user.
    user_id = uuid.UUID(E2E_USER_ID)
    entity_id = uuid.uuid4()

    alert_id = await _seed_alert(e2e_db_session, entity_id=entity_id, alert_type="SIGNAL")
    pending_id = await _seed_pending_alert(e2e_db_session, alert_id, user_id)

    resp = await e2e_client.get("/api/v1/alerts/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["alerts"]) == 1
    alert = data["alerts"][0]
    assert alert["pending_id"] == str(pending_id)
    assert alert["alert_id"] == str(alert_id)
    assert alert["entity_id"] == str(entity_id)
    assert alert["alert_type"] == "SIGNAL"
    assert "created_at" in alert


async def test_pending_alerts_tenant_isolation(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """Pending alerts for user A are NOT visible to the JWT user (isolation).

    PRD-0025: the GET endpoint resolves user_id from the JWT, not query params.
    user_a (a random uuid != E2E_USER_ID) seeds an alert; the JWT-authenticated
    GET (which acts as E2E_USER_ID) must see zero alerts.
    """
    user_a = uuid.uuid4()
    assert str(user_a) != E2E_USER_ID  # sanity — different user than the JWT

    alert_id = await _seed_alert(e2e_db_session, alert_type="SIGNAL")
    await _seed_pending_alert(e2e_db_session, alert_id, user_a)

    # JWT user is E2E_USER_ID (different from user_a); query param is ignored.
    resp = await e2e_client.get("/api/v1/alerts/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["alerts"] == []


async def test_pending_alerts_pagination_offset_and_limit(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """Pagination: limit=1 returns only first alert; offset=1 skips it."""
    # PRD-0025: seed under JWT's user_id.
    user_id = uuid.UUID(E2E_USER_ID)
    entity_id1 = uuid.uuid4()
    entity_id2 = uuid.uuid4()

    alert_id1 = await _seed_alert(
        e2e_db_session,
        entity_id=entity_id1,
        dedup_key=f"key:{uuid.uuid4().hex}",
    )
    alert_id2 = await _seed_alert(
        e2e_db_session,
        entity_id=entity_id2,
        dedup_key=f"key:{uuid.uuid4().hex}",
    )
    await _seed_pending_alert(e2e_db_session, alert_id1, user_id)
    await _seed_pending_alert(e2e_db_session, alert_id2, user_id)

    resp = await e2e_client.get("/api/v1/alerts/pending?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["alerts"]) == 1

    resp = await e2e_client.get("/api/v1/alerts/pending?limit=1&offset=1")
    assert resp.status_code == 200
    data2 = resp.json()
    assert len(data2["alerts"]) == 1
    assert data["alerts"][0]["alert_id"] != data2["alerts"][0]["alert_id"]


# ── DELETE /api/v1/alerts/{alert_id}/ack ─────────────────────────────────────


async def test_acknowledge_unknown_alert_returns_404(e2e_client: AsyncClient) -> None:
    """DELETE /api/v1/alerts/{id}/ack for unknown alert returns 404."""
    user_id = uuid.uuid4()
    resp = await e2e_client.delete(f"/api/v1/alerts/{uuid.uuid4()}/ack?user_id={user_id}")
    assert resp.status_code == 404


async def test_acknowledge_missing_user_id_query_is_ignored(e2e_client: AsyncClient) -> None:
    """DELETE /api/v1/alerts/{id}/ack without user_id query is fine.

    PRD-0025: user_id comes from the JWT, not a query param. Omitting it does
    NOT trip 422 because the route does not declare it as a query parameter.
    For an unknown alert_id the route returns 404 (alert not found).
    """
    resp = await e2e_client.delete(f"/api/v1/alerts/{uuid.uuid4()}/ack")
    assert resp.status_code == 404


async def test_acknowledge_other_users_alert_returns_404(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """DELETE /api/v1/alerts/{id}/ack for alert belonging to different user → 404.

    This verifies the anti-enumeration design: 404 (not 403) is returned when
    the alert does not belong to the requesting user.
    """
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    alert_id = await _seed_alert(e2e_db_session, dedup_key=f"key:{uuid.uuid4().hex}")
    await _seed_pending_alert(e2e_db_session, alert_id, user_a)

    # user_b tries to ack user_a's alert
    resp = await e2e_client.delete(f"/api/v1/alerts/{alert_id}/ack?user_id={user_b}")
    assert resp.status_code == 404


async def test_acknowledge_own_alert_succeeds(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """DELETE /api/v1/alerts/{id}/ack for own pending alert returns 200 and removes it.

    PRD-0025: the route resolves user_id from the JWT (E2E_USER_ID in tests),
    so the seeded pending row MUST belong to E2E_USER_ID or the route returns 404.
    """
    user_id = uuid.UUID(E2E_USER_ID)

    alert_id = await _seed_alert(e2e_db_session, dedup_key=f"key:{uuid.uuid4().hex}")
    await _seed_pending_alert(e2e_db_session, alert_id, user_id)

    resp = await e2e_client.delete(f"/api/v1/alerts/{alert_id}/ack")
    assert resp.status_code == 200
    assert resp.json()["status"] == "acknowledged"

    # The alert should no longer appear in pending (JWT user_id again).
    resp2 = await e2e_client.get("/api/v1/alerts/pending")
    data = resp2.json()
    assert data["total"] == 0


async def test_acknowledge_already_acknowledged_returns_404(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
) -> None:
    """Acknowledging an already-acknowledged alert returns 404 (idempotency via 404)."""
    user_id = uuid.uuid4()

    alert_id = await _seed_alert(e2e_db_session, dedup_key=f"key:{uuid.uuid4().hex}")
    await _seed_pending_alert(e2e_db_session, alert_id, user_id)

    # First ack succeeds
    resp = await e2e_client.delete(f"/api/v1/alerts/{alert_id}/ack?user_id={user_id}")
    assert resp.status_code == 200

    # Second ack returns 404 (already removed)
    resp2 = await e2e_client.delete(f"/api/v1/alerts/{alert_id}/ack?user_id={user_id}")
    assert resp2.status_code == 404


# ── DLQ admin endpoints ───────────────────────────────────────────────────────


async def test_dlq_list_requires_admin_token(e2e_client: AsyncClient) -> None:
    """GET /admin/dlq without X-Admin-Token → 401."""
    resp = await e2e_client.get("/admin/dlq")
    assert resp.status_code == 401


async def test_dlq_list_empty_on_clean_db(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    """GET /admin/dlq on clean DB returns empty list."""
    await e2e_db_session.execute(text("TRUNCATE dead_letter_queue CASCADE"))
    await e2e_db_session.commit()
    resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["total"] == 0


async def test_dlq_seeded_entry_visible_to_admin(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    """Seeded DLQ entry is visible via admin list endpoint."""
    await e2e_db_session.execute(text("TRUNCATE dead_letter_queue CASCADE"))
    await e2e_db_session.commit()
    dlq_id = uuid.uuid4()
    event_id = uuid.uuid4()
    await e2e_db_session.execute(
        text("""
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_avro, error_detail, status, created_at)
            VALUES (:did, :eid, 'alert.dead-letter.v1', E'\\\\x00'::bytea,
                    'unknown alert_type: INVALID', 'failed', now())
        """),
        {"did": str(dlq_id), "eid": str(event_id)},
    )
    await e2e_db_session.commit()

    resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    entry = data["entries"][0]
    assert entry["status"] == "failed"
    assert "INVALID" in entry["error_detail"]


async def test_dlq_resolve_note_too_long_returns_422(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    """POST /admin/dlq/{id}/resolve with note > 2000 chars → 422."""
    dlq_id = uuid.uuid4()
    await e2e_db_session.execute(
        text("""
            INSERT INTO dead_letter_queue
                (dlq_id, original_event_id, topic, payload_avro, status, created_at)
            VALUES (:did, :eid, 'test', E'\\\\x00'::bytea, 'failed', now())
        """),
        {"did": str(dlq_id), "eid": str(uuid.uuid4())},
    )
    await e2e_db_session.commit()

    resp = await e2e_client.post(
        f"/admin/dlq/{dlq_id}/resolve",
        json={"note": "x" * 2001},
        headers=admin_headers,
    )
    assert resp.status_code == 422


async def test_dlq_pagination(
    e2e_client: AsyncClient,
    e2e_db_session: AsyncSession,
    admin_headers: dict[str, str],
) -> None:
    """DLQ list endpoint respects limit/offset pagination."""
    # Clear any DLQ entries written by concurrent Docker services before inserting test data
    await e2e_db_session.execute(text("TRUNCATE dead_letter_queue CASCADE"))
    await e2e_db_session.commit()

    for _ in range(5):
        await e2e_db_session.execute(
            text("""
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, payload_avro, status, created_at)
                VALUES (:did, :eid, 'test', E'\\\\x00'::bytea, 'failed', now())
            """),
            {"did": str(uuid.uuid4()), "eid": str(uuid.uuid4())},
        )
    await e2e_db_session.commit()

    resp = await e2e_client.get("/admin/dlq?limit=2", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["entries"]) == 2
    assert data["total"] == 5

    resp2 = await e2e_client.get("/admin/dlq?limit=2&offset=2", headers=admin_headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["entries"]) == 2
    ids_page1 = {e["dlq_id"] for e in data["entries"]}
    ids_page2 = {e["dlq_id"] for e in data2["entries"]}
    assert ids_page1.isdisjoint(ids_page2)
