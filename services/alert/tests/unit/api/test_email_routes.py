"""Unit tests for email preferences and digest trigger API routes."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from alert.app import create_app
from alert.config import Settings
from alert.domain.entities import EmailPreference
from httpx import ASGITransport, AsyncClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

_USER_ID = UUID("01912345-6789-7abc-8def-0123456789ab")
_TENANT_ID = UUID("01912345-6789-7abc-8def-0123456789ac")
_ADMIN_TOKEN = "test-admin-token"  # noqa: S105


def _make_app() -> tuple[object, AsyncMock]:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost/x",
        admin_token=_ADMIN_TOKEN,
        service_name="alert-unit-test",
        log_json=False,
        s8_internal_token="test-s8-token",
        s1_internal_token="test-s1-token",
    )
    app = create_app(settings)

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.execute = AsyncMock()

    mock_factory = MagicMock()
    mock_factory.return_value = session
    app.state.session_factory = mock_factory
    app.state.read_factory = mock_factory

    from alert.infrastructure.websocket.manager import ConnectionManager

    app.state.ws_manager = ConnectionManager()
    return app, session


def _default_pref(
    *,
    weekly_digest_enabled: bool = True,
    send_day_of_week: int = 6,
    send_hour_utc: int = 8,
    email_address: str | None = None,
    last_digest_sent_at: datetime | None = None,
) -> EmailPreference:
    return EmailPreference(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        weekly_digest_enabled=weekly_digest_enabled,
        send_day_of_week=send_day_of_week,
        send_hour_utc=send_hour_utc,
        email_address=email_address,
        last_digest_sent_at=last_digest_sent_at,
    )


_GET_UC_PATH = "alert.api.email_routes.GetEmailPreferencesUseCase"
_UPD_UC_PATH = "alert.api.email_routes.UpdateEmailPreferencesUseCase"
_REPO_PATH = "alert.infrastructure.db.repositories.email_preference.EmailPreferenceRepository"


# ── GET /api/v1/email/preferences ────────────────────────────────────────────


class TestGetEmailPreferences:
    @pytest.mark.unit
    async def test_returns_200_with_preferences(self) -> None:
        app, _ = _make_app()
        pref = _default_pref()

        with (
            patch(_REPO_PATH),
            patch(_GET_UC_PATH) as mock_uc_cls,
        ):
            mock_uc = AsyncMock()
            mock_uc.execute = AsyncMock(return_value=pref)
            mock_uc_cls.return_value = mock_uc

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/email/preferences",
                    headers={"X-Tenant-ID": str(_TENANT_ID), "X-User-ID": str(_USER_ID)},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == str(_USER_ID)
        assert body["weekly_digest_enabled"] is True
        assert body["send_day_of_week"] == 6
        assert body["send_hour_utc"] == 8

    @pytest.mark.unit
    async def test_missing_tenant_header_returns_401(self) -> None:
        app, _ = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/email/preferences",
                headers={"X-User-ID": str(_USER_ID)},
            )

        assert resp.status_code == 401

    @pytest.mark.unit
    async def test_missing_user_header_returns_401(self) -> None:
        app, _ = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/email/preferences",
                headers={"X-Tenant-ID": str(_TENANT_ID)},
            )

        assert resp.status_code == 401

    @pytest.mark.unit
    async def test_invalid_uuid_header_returns_401(self) -> None:
        app, _ = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/email/preferences",
                headers={"X-Tenant-ID": "not-a-uuid", "X-User-ID": str(_USER_ID)},
            )

        assert resp.status_code == 401

    @pytest.mark.unit
    async def test_last_digest_sent_at_null_in_response(self) -> None:
        app, _ = _make_app()
        pref = _default_pref(last_digest_sent_at=None)

        with (
            patch(_REPO_PATH),
            patch(_GET_UC_PATH) as mock_uc_cls,
        ):
            mock_uc = AsyncMock()
            mock_uc.execute = AsyncMock(return_value=pref)
            mock_uc_cls.return_value = mock_uc

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get(
                    "/api/v1/email/preferences",
                    headers={"X-Tenant-ID": str(_TENANT_ID), "X-User-ID": str(_USER_ID)},
                )

        assert resp.status_code == 200
        assert resp.json()["last_digest_sent_at"] is None


# ── PUT /api/v1/email/preferences ────────────────────────────────────────────


class TestUpdateEmailPreferences:
    @pytest.mark.unit
    async def test_returns_200_with_updated_preferences(self) -> None:
        app, _ = _make_app()
        updated = _default_pref(weekly_digest_enabled=False, send_day_of_week=1)

        with (
            patch(_REPO_PATH),
            patch(_UPD_UC_PATH) as mock_uc_cls,
        ):
            mock_uc = AsyncMock()
            mock_uc.execute = AsyncMock(return_value=updated)
            mock_uc_cls.return_value = mock_uc

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.put(
                    "/api/v1/email/preferences",
                    json={
                        "weekly_digest_enabled": False,
                        "send_day_of_week": 1,
                        "send_hour_utc": None,
                        "email_address": None,
                    },
                    headers={"X-Tenant-ID": str(_TENANT_ID), "X-User-ID": str(_USER_ID)},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["weekly_digest_enabled"] is False
        assert body["send_day_of_week"] == 1

    @pytest.mark.unit
    async def test_missing_auth_headers_returns_401(self) -> None:
        app, _ = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/email/preferences",
                json={"weekly_digest_enabled": True, "email_address": None},
            )

        assert resp.status_code == 401

    @pytest.mark.unit
    async def test_invalid_send_day_pydantic_returns_422(self) -> None:
        """send_day_of_week=7 is caught by Pydantic schema validation (ge=0, le=6)."""
        app, _ = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/v1/email/preferences",
                json={"send_day_of_week": 7, "email_address": None},
                headers={"X-Tenant-ID": str(_TENANT_ID), "X-User-ID": str(_USER_ID)},
            )

        assert resp.status_code == 422

    @pytest.mark.unit
    async def test_use_case_value_error_returns_400(self) -> None:
        """A ValueError raised by the use case (e.g. cross-field constraint) maps to 400."""
        app, _ = _make_app()

        with (
            patch(_REPO_PATH),
            patch(_UPD_UC_PATH) as mock_uc_cls,
        ):
            mock_uc = AsyncMock()
            mock_uc.execute = AsyncMock(side_effect=ValueError("custom domain constraint violated"))
            mock_uc_cls.return_value = mock_uc

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.put(
                    "/api/v1/email/preferences",
                    json={"send_day_of_week": 1, "email_address": None},
                    headers={"X-Tenant-ID": str(_TENANT_ID), "X-User-ID": str(_USER_ID)},
                )

        assert resp.status_code == 400
        assert "domain constraint" in resp.json()["detail"]

    @pytest.mark.unit
    async def test_use_case_receives_correct_user_and_tenant(self) -> None:
        app, _ = _make_app()
        pref = _default_pref()

        with (
            patch(_REPO_PATH),
            patch(_UPD_UC_PATH) as mock_uc_cls,
        ):
            mock_uc = AsyncMock()
            mock_uc.execute = AsyncMock(return_value=pref)
            mock_uc_cls.return_value = mock_uc

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.put(
                    "/api/v1/email/preferences",
                    json={"email_address": None},
                    headers={"X-Tenant-ID": str(_TENANT_ID), "X-User-ID": str(_USER_ID)},
                )

        call_args = mock_uc.execute.call_args
        assert call_args[0][0] == _USER_ID
        assert call_args[0][1] == _TENANT_ID


# ── POST /admin/email/digest/trigger ─────────────────────────────────────────


class TestTriggerDigest:
    @pytest.mark.unit
    async def test_returns_202_with_job_id(self) -> None:
        app, _ = _make_app()
        user_id = uuid4()
        tenant_id = uuid4()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/email/digest/trigger",
                json={"user_id": str(user_id), "tenant_id": str(tenant_id)},
                headers={"X-Admin-Token": _ADMIN_TOKEN},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "queued"
        UUID(body["job_id"])  # must be valid UUID

    @pytest.mark.unit
    async def test_missing_admin_token_returns_401(self) -> None:
        app, _ = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/email/digest/trigger",
                json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
            )

        assert resp.status_code == 401

    @pytest.mark.unit
    async def test_wrong_admin_token_returns_401(self) -> None:
        app, _ = _make_app()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/email/digest/trigger",
                json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
                headers={"X-Admin-Token": "wrong-token"},
            )

        assert resp.status_code == 401

    @pytest.mark.unit
    async def test_job_id_is_unique_per_call(self) -> None:
        app, _ = _make_app()
        user_id = uuid4()
        tenant_id = uuid4()
        job_ids: set[str] = set()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for _ in range(3):
                resp = await client.post(
                    "/admin/email/digest/trigger",
                    json={"user_id": str(user_id), "tenant_id": str(tenant_id)},
                    headers={"X-Admin-Token": _ADMIN_TOKEN},
                )
                assert resp.status_code == 202
                job_ids.add(resp.json()["job_id"])

        assert len(job_ids) == 3  # all unique
