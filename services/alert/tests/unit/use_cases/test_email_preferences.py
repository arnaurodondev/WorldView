"""Unit tests for GetEmailPreferencesUseCase and UpdateEmailPreferencesUseCase."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from alert.application.use_cases.email_preferences import (
    _UNSET,
    GetEmailPreferencesUseCase,
    UpdateEmailPreferencesUseCase,
)
from alert.domain.entities import EmailPreference

pytestmark = pytest.mark.unit

# ── Fixtures ──────────────────────────────────────────────────────────────────

_USER_ID = UUID("01912345-6789-7abc-8def-0123456789ab")
_TENANT_ID = UUID("01912345-6789-7abc-8def-0123456789ac")


def _default_pref() -> EmailPreference:
    return EmailPreference(user_id=_USER_ID, tenant_id=_TENANT_ID)


def _make_repo(existing: EmailPreference | None = None) -> AsyncMock:
    repo = AsyncMock()
    repo.get_by_user = AsyncMock(return_value=existing)
    repo.upsert = AsyncMock()
    return repo


# ── GetEmailPreferencesUseCase ────────────────────────────────────────────────


class TestGetEmailPreferencesUseCase:
    @pytest.mark.unit
    async def test_returns_existing_preference(self) -> None:
        pref = _default_pref()
        repo = _make_repo(existing=pref)

        result = await GetEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID)

        assert result is pref
        repo.get_by_user.assert_called_once_with(_USER_ID, _TENANT_ID)
        repo.upsert.assert_not_called()

    @pytest.mark.unit
    async def test_creates_defaults_when_no_row(self) -> None:
        repo = _make_repo(existing=None)

        result = await GetEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID)

        assert result.user_id == _USER_ID
        assert result.tenant_id == _TENANT_ID
        assert result.weekly_digest_enabled is True
        assert result.send_day_of_week == 6
        assert result.send_hour_utc == 8
        repo.upsert.assert_called_once()

    @pytest.mark.unit
    async def test_upserted_default_matches_returned_entity(self) -> None:
        repo = _make_repo(existing=None)

        result = await GetEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID)

        upserted = repo.upsert.call_args[0][0]
        assert upserted.user_id == result.user_id
        assert upserted.tenant_id == result.tenant_id

    @pytest.mark.unit
    async def test_existing_custom_preferences_preserved(self) -> None:
        custom = EmailPreference(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            weekly_digest_enabled=False,
            send_day_of_week=1,
            send_hour_utc=9,
            email_address="custom@example.com",
        )
        repo = _make_repo(existing=custom)

        result = await GetEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID)

        assert result.weekly_digest_enabled is False
        assert result.send_day_of_week == 1
        assert result.send_hour_utc == 9
        assert result.email_address == "custom@example.com"


# ── UpdateEmailPreferencesUseCase ─────────────────────────────────────────────


class TestUpdateEmailPreferencesUseCase:
    @pytest.mark.unit
    async def test_update_weekly_digest_enabled(self) -> None:
        repo = _make_repo(existing=_default_pref())

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, weekly_digest_enabled=False)

        assert result.weekly_digest_enabled is False
        repo.upsert.assert_called_once()

    @pytest.mark.unit
    async def test_update_send_day_of_week(self) -> None:
        repo = _make_repo(existing=_default_pref())

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, send_day_of_week=0)

        assert result.send_day_of_week == 0

    @pytest.mark.unit
    async def test_update_send_hour_utc(self) -> None:
        repo = _make_repo(existing=_default_pref())

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, send_hour_utc=22)

        assert result.send_hour_utc == 22

    @pytest.mark.unit
    async def test_update_email_address(self) -> None:
        repo = _make_repo(existing=_default_pref())

        result = await UpdateEmailPreferencesUseCase(repo).execute(
            _USER_ID, _TENANT_ID, email_address="new@example.com"
        )

        assert result.email_address == "new@example.com"

    @pytest.mark.unit
    async def test_clear_email_address_with_none(self) -> None:
        existing = EmailPreference(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            email_address="old@example.com",
        )
        repo = _make_repo(existing=existing)

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, email_address=None)

        assert result.email_address is None

    @pytest.mark.unit
    async def test_unset_email_address_leaves_existing(self) -> None:
        existing = EmailPreference(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            email_address="keep@example.com",
        )
        repo = _make_repo(existing=existing)

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, email_address=_UNSET)

        assert result.email_address == "keep@example.com"

    @pytest.mark.unit
    async def test_invalid_day_raises_value_error(self) -> None:
        repo = _make_repo(existing=_default_pref())

        with pytest.raises(ValueError, match="send_day_of_week"):
            await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, send_day_of_week=7)

    @pytest.mark.unit
    async def test_invalid_hour_raises_value_error(self) -> None:
        repo = _make_repo(existing=_default_pref())

        with pytest.raises(ValueError, match="send_hour_utc"):
            await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, send_hour_utc=24)

    @pytest.mark.unit
    async def test_no_existing_row_creates_defaults_then_updates(self) -> None:
        repo = _make_repo(existing=None)

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, weekly_digest_enabled=False)

        assert result.user_id == _USER_ID
        assert result.weekly_digest_enabled is False
        repo.upsert.assert_called_once()

    @pytest.mark.unit
    async def test_created_at_preserved_on_update(self) -> None:
        original_time = datetime(2026, 1, 1, tzinfo=UTC)
        existing = EmailPreference(
            user_id=_USER_ID,
            tenant_id=_TENANT_ID,
            created_at=original_time,
        )
        repo = _make_repo(existing=existing)

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID, weekly_digest_enabled=False)

        assert result.created_at == original_time

    @pytest.mark.unit
    async def test_no_changes_still_upserts(self) -> None:
        """Calling execute with no updates still persists (idempotent upsert)."""
        repo = _make_repo(existing=_default_pref())

        await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, _TENANT_ID)

        repo.upsert.assert_called_once()

    @pytest.mark.unit
    async def test_ownership_tenant_mismatch_uses_supplied_tenant(self) -> None:
        """user_id from path/header governs the upsert PK."""
        other_tenant = UUID("01912345-6789-7abc-8def-000000000001")
        repo = _make_repo(existing=None)

        result = await UpdateEmailPreferencesUseCase(repo).execute(_USER_ID, other_tenant)

        assert result.tenant_id == other_tenant
