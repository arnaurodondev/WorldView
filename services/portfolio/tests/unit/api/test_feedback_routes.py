"""Unit tests for feedback API routes (PLAN-0052 Wave D / T-D-4-05).

Mirrors ``test_brokerage_connections.py``: spin up a minimal FastAPI
app with the feedback router, override ``get_uow`` / ``get_read_uow``
with a FakeUnitOfWork, inject ``request.state`` from headers via a
test middleware. No DB, no real JWT.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from portfolio.api.dependencies import get_read_uow, get_uow
from portfolio.api.exception_handlers import domain_error_handler
from portfolio.api.routes.feedback import router as feedback_router
from portfolio.domain.errors import DomainError

from tests.unit.fakes import FakeUnitOfWork

pytestmark = [pytest.mark.unit]


USER_ID = uuid4()
TENANT_ID = uuid4()
ADMIN_ID = uuid4()


_NIL_UUID = "00000000-0000-0000-0000-000000000000"


class _StubSettings:
    """Minimal stub for ``request.app.state.settings`` used by the anonymous
    submissions endpoint (F-Q1-04). Real Settings would pull from env vars
    which we don't want in unit tests."""

    feedback_anonymous_tenant_id: str = _NIL_UUID


def _make_app(uow: FakeUnitOfWork, *, role: str = "user", user_id: str | None = None) -> FastAPI:
    """Minimal app for feedback route tests.

    Test headers used by the inject middleware:
      X-Test-User-Id      → request.state.user_id  (omit for anon)
      X-Test-Tenant-Id    → request.state.tenant_id
      X-Test-Role         → request.state.role  (default: user)

    The system-JWT path (F-Q1-07) is exercised by passing
    ``X-Test-User-Id: system:api-gateway`` verbatim — the route's
    defensive UUID parsing must treat that as anonymous.
    """
    app = FastAPI()
    # F-Q1-04: stub settings on app.state so the anonymous list route can
    # read ``feedback_anonymous_tenant_id``.
    app.state.settings = _StubSettings()

    async def override_uow():
        yield uow

    app.dependency_overrides[get_uow] = override_uow
    app.dependency_overrides[get_read_uow] = override_uow
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.include_router(feedback_router, prefix="/api/v1/feedback")

    @app.middleware("http")
    async def inject_state(request: Request, call_next):  # type: ignore[no-untyped-def]
        # Headers populate request.state the same way InternalJWTMiddleware would
        # in production. Empty values mean "anonymous" / "no role" — the routes
        # branch on these.
        request.state.user_id = request.headers.get("X-Test-User-Id", "")
        request.state.tenant_id = request.headers.get("X-Test-Tenant-Id", "")
        request.state.role = request.headers.get("X-Test-Role", "")
        return await call_next(request)

    return app


def _user_headers(*, tenant_id=TENANT_ID, user_id=USER_ID, role="user") -> dict[str, str]:
    return {
        "X-Test-Tenant-Id": str(tenant_id),
        "X-Test-User-Id": str(user_id),
        "X-Test-Role": role,
    }


def _admin_headers() -> dict[str, str]:
    return _user_headers(user_id=ADMIN_ID, role="admin")


# ── POST /submissions ────────────────────────────────────────────────────────


async def test_create_submission_redacts_bearer_in_description() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/submissions",
            json={
                "kind": "bug",
                "description": "Auth failed: Bearer abcdef0123456789ABCDEF",
            },
            headers=_user_headers(),
        )
    assert resp.status_code == 201
    body = resp.json()
    assert "abcdef0123456789ABCDEF" not in body["description"]
    assert "[REDACTED:" in body["description"]


async def test_create_submission_anonymous_with_email() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/submissions",
            json={
                "kind": "feature_request",
                "description": "Please add dark mode toggle",
                "email": "anon@example.com",
            },
            headers={"X-Test-Tenant-Id": str(TENANT_ID)},  # no user_id
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] is None
    assert body["email"] == "anon@example.com"


async def test_create_submission_anonymous_without_email_returns_422() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/submissions",
            json={"kind": "bug", "description": "Something is broken on the site"},
            headers={"X-Test-Tenant-Id": str(TENANT_ID)},
        )
    assert resp.status_code == 422


# ── GET /submissions ─────────────────────────────────────────────────────────


async def test_list_submissions_admin_sees_all_in_tenant() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Two submissions from different users in the same tenant
        for uid in (USER_ID, uuid4()):
            await client.post(
                "/api/v1/feedback/submissions",
                json={"kind": "bug", "description": "0123456789 just enough text"},
                headers=_user_headers(user_id=uid),
            )
        resp = await client.get("/api/v1/feedback/submissions", headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2


async def test_list_submissions_mine_filters_to_self() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # USER_ID submits 2; another user submits 1
        for _ in range(2):
            await client.post(
                "/api/v1/feedback/submissions",
                json={"kind": "bug", "description": "0123456789 just enough text"},
                headers=_user_headers(user_id=USER_ID),
            )
        await client.post(
            "/api/v1/feedback/submissions",
            json={"kind": "bug", "description": "0123456789 just enough text"},
            headers=_user_headers(user_id=uuid4()),
        )
        resp = await client.get(
            "/api/v1/feedback/submissions?mine=true",
            headers=_user_headers(user_id=USER_ID),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2


async def test_list_submissions_non_admin_without_mine_returns_403() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/feedback/submissions", headers=_user_headers())
    assert resp.status_code == 403


# ── PATCH / DELETE /submissions ──────────────────────────────────────────────


async def test_patch_submission_admin_succeeds() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post = await client.post(
            "/api/v1/feedback/submissions",
            json={"kind": "bug", "description": "0123456789 just enough text"},
            headers=_user_headers(),
        )
        sid = post.json()["id"]
        resp = await client.patch(
            f"/api/v1/feedback/submissions/{sid}",
            json={"status": "triaged"},
            headers=_admin_headers(),
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "triaged"


async def test_patch_submission_non_admin_returns_403() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post = await client.post(
            "/api/v1/feedback/submissions",
            json={"kind": "bug", "description": "0123456789 just enough text"},
            headers=_user_headers(),
        )
        sid = post.json()["id"]
        resp = await client.patch(
            f"/api/v1/feedback/submissions/{sid}",
            json={"status": "triaged"},
            headers=_user_headers(),
        )
    assert resp.status_code == 403


async def test_delete_submission_non_admin_returns_403() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post = await client.post(
            "/api/v1/feedback/submissions",
            json={"kind": "bug", "description": "0123456789 just enough text"},
            headers=_user_headers(),
        )
        sid = post.json()["id"]
        resp = await client.delete(f"/api/v1/feedback/submissions/{sid}", headers=_user_headers())
    assert resp.status_code == 403


# ── NPS ──────────────────────────────────────────────────────────────────────


async def test_post_nps_twice_within_30_days_returns_409() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/api/v1/feedback/nps",
            json={"score": 9},
            headers=_user_headers(),
        )
        r2 = await client.post(
            "/api/v1/feedback/nps",
            json={"score": 8},
            headers=_user_headers(),
        )
    assert r1.status_code == 201
    assert r2.status_code == 409


async def test_get_nps_aggregate_admin_only() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        non_admin = await client.get("/api/v1/feedback/nps/aggregate", headers=_user_headers())
        admin = await client.get("/api/v1/feedback/nps/aggregate", headers=_admin_headers())
    assert non_admin.status_code == 403
    assert admin.status_code == 200


# ── Feature votes ────────────────────────────────────────────────────────────


async def test_feature_vote_idempotent_returns_count_one() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        post = await client.post(
            "/api/v1/feedback/features",
            json={"title": "Dark charts", "description": "Match dark theme"},
            headers=_user_headers(),
        )
        fid = post.json()["id"]
        v1 = await client.post(f"/api/v1/feedback/features/{fid}/vote", headers=_user_headers())
        v2 = await client.post(f"/api/v1/feedback/features/{fid}/vote", headers=_user_headers())
    assert v1.status_code == 200
    assert v2.status_code == 200
    assert v1.json()["vote_count"] == 1
    assert v2.json()["vote_count"] == 1
    # F-Q1-17: symmetric assertion — the first vote should also report has_voted.
    assert v1.json()["has_voted"] is True
    assert v2.json()["has_voted"] is True


# ── Beta enrolment ───────────────────────────────────────────────────────────


async def test_get_beta_enrollment_returns_default_false() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/feedback/beta-program/enrollment",
            headers=_user_headers(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enrolled"] is False
    assert body["programs"] == []


async def test_patch_beta_enrollment_persists() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch(
            "/api/v1/feedback/beta-program/enrollment",
            json={"enrolled": True, "programs": ["ai-brief"]},
            headers=_user_headers(),
        )
    assert resp.status_code == 200
    assert resp.json()["enrolled"] is True
    assert resp.json()["programs"] == ["ai-brief"]


# ── Micro-survey ─────────────────────────────────────────────────────────────


async def test_post_micro_survey_anon_succeeds() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/micro-survey",
            json={"survey_key": "docs:/instruments/overview", "response": "positive"},
            headers={"X-Test-Tenant-Id": str(TENANT_ID)},  # anon
        )
    assert resp.status_code == 201
    assert resp.json()["response"] == "positive"


# ── F-Q1-07: anon system-JWT path (production-shaped) ───────────────────────


async def test_anonymous_submission_via_system_jwt() -> None:
    """F-Q1-07: simulate the production gateway anon path.

    In production, the gateway issues a system JWT with
    ``sub: "system:api-gateway"`` and ``tenant_id: NIL_UUID`` for
    unauthenticated calls. Before the fix, the portfolio route blindly
    called ``UUID("system:api-gateway")`` which raised ValueError → 500.
    """
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/submissions",
            json={
                "kind": "bug",
                "description": "Anonymous bug report — please investigate",
                "email": "anon@example.com",
            },
            headers={
                "X-Test-Tenant-Id": _NIL_UUID,
                "X-Test-User-Id": "system:api-gateway",  # exact production shape
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_id"] is None
    assert body["email"] == "anon@example.com"


# ── F-Q1-04: admin endpoint to list anonymous submissions ───────────────────


async def test_admin_can_list_anonymous_submissions() -> None:
    """F-Q1-04: admins query ``/submissions/anonymous`` to see anon backlog."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Anonymous user submits feedback under nil-UUID tenant.
        await client.post(
            "/api/v1/feedback/submissions",
            json={
                "kind": "bug",
                "description": "Anonymous bug from the docs page",
                "email": "anon@example.com",
            },
            headers={
                "X-Test-Tenant-Id": _NIL_UUID,
                "X-Test-User-Id": "system:api-gateway",
            },
        )
        # Admin queries the anonymous-list endpoint (auth via real tenant).
        resp = await client.get(
            "/api/v1/feedback/submissions/anonymous",
            headers=_admin_headers(),  # admin role, real tenant
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "anon@example.com"


async def test_non_admin_cannot_list_anonymous_submissions() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/feedback/submissions/anonymous",
            headers=_user_headers(),  # role=user → 403
        )
    assert resp.status_code == 403


# ── F-Q1-08: screenshot_url validator ───────────────────────────────────────


async def test_javascript_screenshot_url_rejected() -> None:
    """F-Q1-08: javascript: URLs must be rejected at schema validation."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/submissions",
            json={
                "kind": "bug",
                "description": "0123456789 some bug description",
                "screenshot_url": "javascript:alert(1)",
            },
            headers=_user_headers(),
        )
    assert resp.status_code == 422


async def test_http_screenshot_url_rejected() -> None:
    """F-Q1-08: plain http URLs must be rejected — https only."""
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/submissions",
            json={
                "kind": "bug",
                "description": "0123456789 some bug description",
                "screenshot_url": "http://evil.example.com/x.png",
            },
            headers=_user_headers(),
        )
    assert resp.status_code == 422


async def test_https_screenshot_url_accepted() -> None:
    uow = FakeUnitOfWork()
    app = _make_app(uow)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/feedback/submissions",
            json={
                "kind": "bug",
                "description": "0123456789 some bug description",
                "screenshot_url": "https://worldview-feedback-screenshots.s3.amazonaws.com/x.png",
            },
            headers=_user_headers(),
        )
    assert resp.status_code == 201
