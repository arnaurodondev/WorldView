"""E2E workflow tests for the content-store (S5) API.

Tests use ASGI transport backed by a real PostgreSQL database to exercise the
full HTTP → FastAPI → SQLAlchemy stack without requiring a deployed service.

Prerequisites:
    PostgreSQL must be running and reachable at CONTENT_STORE_E2E_DATABASE_URL
    (default: postgresql+asyncpg://postgres:postgres@localhost:55433/content_store_db).

All tests are skipped automatically when the database is unreachable.

Test categories:
    - Health & readiness probes
    - Prometheus metrics endpoint
    - DLQ authentication (401 without/with wrong token)
    - DLQ not-found cases (404)
    - DLQ input validation (422)
    - DLQ full workflows with seeded data
    - Readyz consumer-alive flag behaviour
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from content_store.api.dlq import router as dlq_router
from content_store.api.health import router as health_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# ── Helpers ───────────────────────────────────────────────────────────────────

_ADMIN_TOKEN = "e2e-admin-token"  # noqa: S105


def _make_dlq_payload(
    *,
    dlq_id: uuid.UUID | None = None,
    original_event_id: uuid.UUID | None = None,
    topic: str = "content.article.raw.v1",
    status: str = "failed",
    error_detail: str = "simulated dispatch error",
    payload_json: dict | None = None,
) -> dict:
    """Build a parameter dict suitable for a raw INSERT into dead_letter_queue."""
    return {
        "dlq_id": str(dlq_id or uuid.uuid4()),
        "original_event_id": str(original_event_id or uuid.uuid4()),
        "topic": topic,
        "status": status,
        "error_detail": error_detail,
        "payload_json": payload_json,
    }


async def _seed_dlq_row(session: AsyncSession, **overrides: object) -> uuid.UUID:
    """Insert one row into dead_letter_queue and return its dlq_id.

    Commits the session so the row is visible to the app's own session.
    """
    params = _make_dlq_payload(**overrides)  # type: ignore[arg-type]
    dlq_id = uuid.UUID(params["dlq_id"])
    row = {
        "dlq_id": str(dlq_id),
        "original_event_id": params["original_event_id"],
        "topic": params["topic"],
        "status": params["status"],
        "error_detail": params["error_detail"],
    }

    if params["payload_json"] is not None:
        await session.execute(
            text(
                """
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, status, error_detail, payload_json)
                VALUES
                    (:dlq_id, :original_event_id, :topic, :status, :error_detail,
                     CAST(:payload AS JSONB))
                """,
            ),
            {**row, "payload": json.dumps(params["payload_json"])},
        )
    else:
        await session.execute(
            text(
                """
                INSERT INTO dead_letter_queue
                    (dlq_id, original_event_id, topic, status, error_detail)
                VALUES
                    (:dlq_id, :original_event_id, :topic, :status, :error_detail)
                """,
            ),
            row,
        )
    await session.commit()
    return dlq_id


# ─────────────────────────────────────────────────────────────────────────────
# Health / Readiness
# ─────────────────────────────────────────────────────────────────────────────


class TestHealthEndpoints:
    """Liveness and readiness probe behaviour."""

    async def test_healthz_always_ok(self, e2e_client: AsyncClient) -> None:
        """GET /healthz must return 200 {"status": "ok"} unconditionally."""
        response = await e2e_client.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"

    async def test_readyz_with_healthy_db(self, e2e_client: AsyncClient) -> None:
        """GET /readyz returns a JSON body with at least a 'status' field.

        With a real DB and consumer_alive=True the status should be 'ok'.
        Valkey is None so the health check skips the ping (returns ok).
        """
        response = await e2e_client.get("/readyz")

        # Status is either 200 (all checks pass) or 503 (degraded).
        # With real DB + consumer_alive=True + valkey=None → 200 expected.
        assert response.status_code in {200, 503}
        body = response.json()
        assert "status" in body
        # Database check must be ok because we have a real DB
        assert body.get("database") == "ok"

    async def test_metrics_endpoint_returns_200(self, e2e_client: AsyncClient) -> None:
        """GET /metrics returns 200 with Prometheus text format content-type."""
        response = await e2e_client.get("/metrics")

        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "prometheus" in content_type


# ─────────────────────────────────────────────────────────────────────────────
# DLQ — Authentication
# ─────────────────────────────────────────────────────────────────────────────


class TestDLQAuthentication:
    """All DLQ endpoints require a valid X-Admin-Token header."""

    async def test_dlq_list_without_token_returns_401(self, e2e_client: AsyncClient) -> None:
        """GET /admin/dlq with no token → 401."""
        response = await e2e_client.get("/admin/dlq")

        assert response.status_code == 401

    async def test_dlq_list_with_wrong_token_returns_401(self, e2e_client: AsyncClient) -> None:
        """GET /admin/dlq with an incorrect token → 401."""
        response = await e2e_client.get(
            "/admin/dlq",
            headers={"X-Admin-Token": "not-the-right-token"},
        )

        assert response.status_code == 401

    async def test_dlq_list_with_valid_token_returns_200(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """GET /admin/dlq with valid token → 200, empty list when DB is clean."""
        response = await e2e_client.get("/admin/dlq", headers=admin_headers)

        assert response.status_code == 200
        body = response.json()
        assert "entries" in body
        assert "count" in body
        assert body["entries"] == []
        assert body["count"] == 0

    async def test_dlq_get_entry_without_token_returns_401(self, e2e_client: AsyncClient) -> None:
        """GET /admin/dlq/{id} with no token → 401."""
        random_id = str(uuid.uuid4())
        response = await e2e_client.get(f"/admin/dlq/{random_id}")

        assert response.status_code == 401

    async def test_dlq_retry_without_token_returns_401(self, e2e_client: AsyncClient) -> None:
        """POST /admin/dlq/{id}/retry with no token → 401."""
        random_id = str(uuid.uuid4())
        response = await e2e_client.post(f"/admin/dlq/{random_id}/retry")

        assert response.status_code == 401

    async def test_dlq_resolve_without_token_returns_401(self, e2e_client: AsyncClient) -> None:
        """POST /admin/dlq/{id}/resolve with no token → 401."""
        random_id = str(uuid.uuid4())
        response = await e2e_client.post(
            f"/admin/dlq/{random_id}/resolve",
            json={"note": "some note"},
        )

        assert response.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# DLQ — Not-Found Cases
# ─────────────────────────────────────────────────────────────────────────────


class TestDLQNotFound:
    """DLQ endpoints return 404 when the requested entry does not exist."""

    async def test_dlq_get_nonexistent_entry_returns_404(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """GET /admin/dlq/{random_uuid} → 404 when entry is absent."""
        random_id = str(uuid.uuid4())
        response = await e2e_client.get(f"/admin/dlq/{random_id}", headers=admin_headers)

        assert response.status_code == 404

    async def test_dlq_retry_nonexistent_entry_returns_404(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """POST /admin/dlq/{random_uuid}/retry → 404 when entry is absent."""
        random_id = str(uuid.uuid4())
        response = await e2e_client.post(f"/admin/dlq/{random_id}/retry", headers=admin_headers)

        assert response.status_code == 404

    async def test_dlq_resolve_nonexistent_entry_returns_404(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """POST /admin/dlq/{random_uuid}/resolve → 404 when entry is absent."""
        random_id = str(uuid.uuid4())
        response = await e2e_client.post(
            f"/admin/dlq/{random_id}/resolve",
            json={"note": "manual resolution"},
            headers=admin_headers,
        )

        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# DLQ — Resolve Endpoint Validation
# ─────────────────────────────────────────────────────────────────────────────


class TestDLQResolveValidation:
    """The resolve endpoint requires a non-empty 'note' field in the request body."""

    async def test_dlq_resolve_requires_note_field_no_body(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """POST /admin/dlq/{id}/resolve with no body → 422 Unprocessable Entity."""
        random_id = str(uuid.uuid4())
        # No JSON body at all — FastAPI cannot parse DLQResolveRequest
        response = await e2e_client.post(
            f"/admin/dlq/{random_id}/resolve",
            headers=admin_headers,
        )

        assert response.status_code == 422

    async def test_dlq_resolve_requires_note_field_empty_json(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """POST /admin/dlq/{id}/resolve with {} → 422 because 'note' is required."""
        random_id = str(uuid.uuid4())
        response = await e2e_client.post(
            f"/admin/dlq/{random_id}/resolve",
            json={},
            headers=admin_headers,
        )

        assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# DLQ — Full Workflows with Seeded Data
# ─────────────────────────────────────────────────────────────────────────────


class TestDLQWorkflows:
    """Full CRUD workflows using directly-seeded database rows."""

    async def test_dlq_full_workflow_seed_list_resolve(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
        e2e_db_session: AsyncSession,
    ) -> None:
        """Seed one DLQ row, list it, fetch it by ID, then resolve it.

        After resolution the list endpoint should report count=0 because
        list_open() only returns rows with status='failed'.
        """
        # 1. Seed a DLQ row directly via SQL
        dlq_id = await _seed_dlq_row(
            e2e_db_session,
            topic="content.article.raw.v1",
            error_detail="simulated timeout",
        )

        # 2. List → count=1
        list_resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
        assert list_resp.status_code == 200
        list_body = list_resp.json()
        assert list_body["count"] == 1
        assert len(list_body["entries"]) == 1
        assert list_body["entries"][0]["dlq_id"] == str(dlq_id)

        # 3. Get by ID → full entry returned
        get_resp = await e2e_client.get(f"/admin/dlq/{dlq_id}", headers=admin_headers)
        assert get_resp.status_code == 200
        entry = get_resp.json()
        assert entry["dlq_id"] == str(dlq_id)
        assert entry["status"] == "failed"
        assert entry["topic"] == "content.article.raw.v1"
        assert entry["error_detail"] == "simulated timeout"
        assert entry["resolved_at"] is None
        assert entry["resolution_note"] is None

        # 4. Resolve → status=resolved
        resolve_resp = await e2e_client.post(
            f"/admin/dlq/{dlq_id}/resolve",
            json={"note": "manual resolution"},
            headers=admin_headers,
        )
        assert resolve_resp.status_code == 200
        resolve_body = resolve_resp.json()
        assert resolve_body["status"] == "resolved"

        # 5. List again → count=0 (resolved entries are excluded from list_open)
        list_resp2 = await e2e_client.get("/admin/dlq", headers=admin_headers)
        assert list_resp2.status_code == 200
        assert list_resp2.json()["count"] == 0
        assert list_resp2.json()["entries"] == []

    async def test_dlq_retry_workflow(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
        e2e_db_session: AsyncSession,
    ) -> None:
        """Seed a DLQ row, retry it, and verify an outbox_events row was created.

        The retry endpoint:
          - Returns 202 {"status": "requeued", "new_event_id": "<uuid>"}
          - Creates a new row in outbox_events with status='pending'
          - Marks the DLQ row as status='resolved'
        """
        original_event_id = uuid.uuid4()
        dlq_id = await _seed_dlq_row(
            e2e_db_session,
            original_event_id=original_event_id,
            topic="content.article.raw.v1",
            payload_json={"event_type": "content.article.stored.v1", "doc_id": str(uuid.uuid4())},
        )

        # POST /retry → 202
        retry_resp = await e2e_client.post(f"/admin/dlq/{dlq_id}/retry", headers=admin_headers)
        assert retry_resp.status_code == 202
        retry_body = retry_resp.json()
        assert retry_body["status"] == "requeued"
        assert "new_event_id" in retry_body

        new_event_id = uuid.UUID(retry_body["new_event_id"])

        # White-box: verify outbox row exists
        result = await e2e_db_session.execute(
            text("SELECT id, status, topic FROM outbox_events WHERE id = :id"),
            {"id": str(new_event_id)},
        )
        row = result.mappings().one_or_none()
        assert row is not None, "Expected a new outbox_events row after retry"
        assert row["status"] == "pending"
        assert row["topic"] == "content.article.raw.v1"

        # White-box: DLQ entry is now resolved (no longer in open list)
        list_resp = await e2e_client.get("/admin/dlq", headers=admin_headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Readyz — Consumer Alive Flag
# ─────────────────────────────────────────────────────────────────────────────


class TestReadyzConsumerFlag:
    """Readyz endpoint reflects the consumer_alive state flag."""

    async def test_readyz_reports_consumer_ok_when_alive(
        self,
        e2e_client: AsyncClient,
        e2e_app: FastAPI,
    ) -> None:
        """With consumer_alive=True, readyz should include consumer=ok."""
        e2e_app.state.consumer_alive = True

        response = await e2e_client.get("/readyz")
        body = response.json()

        assert body.get("consumer") == "ok"

    async def test_readyz_reports_consumer_error_when_not_alive(
        self,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """With consumer_alive=False, readyz returns consumer=error and 503."""
        # Build a fresh app so we don't mutate the shared fixture
        app = FastAPI(title="content-store-e2e-consumer-dead")
        app.include_router(health_router)
        app.include_router(dlq_router)

        settings = MagicMock()
        settings.admin_token = _ADMIN_TOKEN

        app.state.settings = settings
        app.state.session_factory = e2e_session_factory
        app.state.valkey = None
        app.state.consumer_alive = False  # Simulate dead consumer

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=10.0) as client:
            response = await client.get("/readyz")

        assert response.status_code == 503
        body = response.json()
        assert body["consumer"] == "error"
        assert body["status"] == "degraded"


# ─────────────────────────────────────────────────────────────────────────────
# DLQ — Input Validation / Pagination
# ─────────────────────────────────────────────────────────────────────────────


class TestDLQInputValidation:
    """DLQ list endpoint validates pagination parameters via FastAPI/Pydantic."""

    async def test_dlq_resolve_with_long_note_accepted(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
        e2e_db_session: AsyncSession,
    ) -> None:
        """POST /admin/dlq/{id}/resolve with a 1000-character note is accepted.

        DLQResolveRequest.note has no explicit max_length constraint, so a long
        note must succeed (the DB column is TEXT — unlimited length).
        """
        dlq_id = await _seed_dlq_row(e2e_db_session)

        long_note = "x" * 1000
        response = await e2e_client.post(
            f"/admin/dlq/{dlq_id}/resolve",
            json={"note": long_note},
            headers=admin_headers,
        )

        # No length cap → 200
        assert response.status_code == 200
        assert response.json()["status"] == "resolved"

    async def test_dlq_list_pagination_params(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
        e2e_db_session: AsyncSession,
    ) -> None:
        """GET /admin/dlq?limit=1&offset=0 respects pagination parameters."""
        # Seed two rows so pagination is observable
        await _seed_dlq_row(e2e_db_session)
        await _seed_dlq_row(e2e_db_session)

        response = await e2e_client.get("/admin/dlq?limit=1&offset=0", headers=admin_headers)

        assert response.status_code == 200
        body = response.json()
        # Total count reflects all open entries
        assert body["count"] == 2
        # But only 1 entry is returned in this page
        assert len(body["entries"]) == 1

    async def test_dlq_list_invalid_limit_returns_422(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """GET /admin/dlq?limit=0 → 422 because limit must be ge=1."""
        response = await e2e_client.get("/admin/dlq?limit=0", headers=admin_headers)

        assert response.status_code == 422

    async def test_dlq_list_limit_too_large_returns_422(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """GET /admin/dlq?limit=1001 → 422 because limit must be le=1000."""
        response = await e2e_client.get("/admin/dlq?limit=1001", headers=admin_headers)

        assert response.status_code == 422

    async def test_dlq_list_offset_zero_is_valid(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """GET /admin/dlq?offset=0 is the minimum valid offset → 200."""
        response = await e2e_client.get("/admin/dlq?offset=0", headers=admin_headers)

        assert response.status_code == 200

    async def test_dlq_list_negative_offset_returns_422(
        self,
        e2e_client: AsyncClient,
        admin_headers: dict[str, str],
    ) -> None:
        """GET /admin/dlq?offset=-1 → 422 because offset must be ge=0."""
        response = await e2e_client.get("/admin/dlq?offset=-1", headers=admin_headers)

        assert response.status_code == 422
