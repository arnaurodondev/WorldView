"""Unit tests for notification preferences use cases.

W1-BACKEND: covers GetNotificationPreferencesUseCase (returns defaults for
new tenant) and UpdateNotificationPreferencesUseCase (persists changes and
merges partial updates).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from portfolio.application.use_cases.notification_preferences import (
    GetNotificationPreferencesUseCase,
    UpdateNotificationPreferencesCommand,
    UpdateNotificationPreferencesUseCase,
)

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


# ── GetNotificationPreferencesUseCase ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_notification_preferences_returns_defaults_for_new_tenant(
    uow: FakeUnitOfWork,
) -> None:
    """GetNotificationPreferences returns all-True defaults when no row exists.

    WHY: the frontend must never receive a 404 or null for this endpoint.
    On first load (before the user has touched settings) the backend must
    return a valid payload with application-layer defaults.
    """
    tenant_id = uuid4()
    uc = GetNotificationPreferencesUseCase()
    prefs = await uc.execute(tenant_id, uow)

    # All four toggles default to True.
    assert prefs.price_alerts is True
    assert prefs.news_alerts is True
    assert prefs.movers_alerts is True
    assert prefs.contradiction_alerts is True
    # Tenant ID is preserved in the defaults object.
    assert prefs.tenant_id == tenant_id
    # No row was persisted — this is a read-only use case.
    stored = await uow.notification_preferences.get(tenant_id)
    assert stored is None, "Get use case must NOT persist defaults to the DB"


@pytest.mark.asyncio
async def test_get_notification_preferences_returns_stored_values(
    uow: FakeUnitOfWork,
) -> None:
    """GetNotificationPreferences returns the stored values when a row exists."""
    tenant_id = uuid4()
    # Seed a row with some toggles disabled.
    update_uc = UpdateNotificationPreferencesUseCase()
    await update_uc.execute(
        UpdateNotificationPreferencesCommand(
            tenant_id=tenant_id,
            price_alerts=False,
            news_alerts=True,
            movers_alerts=False,
            contradiction_alerts=True,
        ),
        uow,
    )

    get_uc = GetNotificationPreferencesUseCase()
    prefs = await get_uc.execute(tenant_id, uow)

    assert prefs.price_alerts is False
    assert prefs.news_alerts is True
    assert prefs.movers_alerts is False
    assert prefs.contradiction_alerts is True


# ── UpdateNotificationPreferencesUseCase ──────────────────────────────────────


@pytest.mark.asyncio
async def test_update_notification_preferences_persists_changes(
    uow: FakeUnitOfWork,
) -> None:
    """UpdateNotificationPreferences writes all four fields and commits."""
    tenant_id = uuid4()
    uc = UpdateNotificationPreferencesUseCase()
    prefs = await uc.execute(
        UpdateNotificationPreferencesCommand(
            tenant_id=tenant_id,
            price_alerts=False,
            news_alerts=False,
            movers_alerts=True,
            contradiction_alerts=False,
        ),
        uow,
    )

    # Returned entity reflects the requested values.
    assert prefs.price_alerts is False
    assert prefs.news_alerts is False
    assert prefs.movers_alerts is True
    assert prefs.contradiction_alerts is False

    # Stored in the repository (idempotent — second read returns same values).
    stored = await uow.notification_preferences.get(tenant_id)
    assert stored is not None
    assert stored.price_alerts is False
    assert stored.movers_alerts is True

    # UoW was committed once.
    assert uow.commit_count == 1


@pytest.mark.asyncio
async def test_update_notification_preferences_partial_update_merges_over_defaults(
    uow: FakeUnitOfWork,
) -> None:
    """Partial update (only some fields set) merges over existing defaults.

    WHY: the frontend sends a PATCH with only the changed field. The
    unchanged fields must retain their previous values, not reset to an
    arbitrary fallback.
    """
    tenant_id = uuid4()
    uc = UpdateNotificationPreferencesUseCase()

    # Only update price_alerts — the rest should stay at default (True).
    prefs = await uc.execute(
        UpdateNotificationPreferencesCommand(
            tenant_id=tenant_id,
            price_alerts=False,
            # news_alerts, movers_alerts, contradiction_alerts all None → keep defaults
        ),
        uow,
    )

    assert prefs.price_alerts is False
    # Defaults retained for the untouched fields.
    assert prefs.news_alerts is True
    assert prefs.movers_alerts is True
    assert prefs.contradiction_alerts is True


@pytest.mark.asyncio
async def test_update_notification_preferences_partial_update_over_existing_row(
    uow: FakeUnitOfWork,
) -> None:
    """Partial update merges over an existing persisted row (not just defaults)."""
    tenant_id = uuid4()
    uc = UpdateNotificationPreferencesUseCase()

    # First write: all False.
    await uc.execute(
        UpdateNotificationPreferencesCommand(
            tenant_id=tenant_id,
            price_alerts=False,
            news_alerts=False,
            movers_alerts=False,
            contradiction_alerts=False,
        ),
        uow,
    )

    # Second write: only flip news_alerts back to True.
    prefs = await uc.execute(
        UpdateNotificationPreferencesCommand(
            tenant_id=tenant_id,
            news_alerts=True,
            # price_alerts, movers_alerts, contradiction_alerts all None
        ),
        uow,
    )

    # Only news_alerts changed; others remain False (from previous write).
    assert prefs.price_alerts is False
    assert prefs.news_alerts is True
    assert prefs.movers_alerts is False
    assert prefs.contradiction_alerts is False
