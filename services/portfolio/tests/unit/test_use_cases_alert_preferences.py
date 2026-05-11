"""Unit tests for alert preference use cases."""

from __future__ import annotations

from uuid import uuid4

import pytest
from portfolio.application.use_cases.alert_preferences import (
    GetAlertPreferencesUseCase,
    RemoveEntitySuppressionCommand,
    RemoveEntitySuppressionUseCase,
    SetEntitySuppressionCommand,
    SetEntitySuppressionUseCase,
    UpsertAlertPreferenceCommand,
    UpsertAlertPreferenceUseCase,
)
from portfolio.domain.enums import AlertType
from portfolio.domain.errors import AlertPreferenceNotFoundError, ValidationError

from .fakes import FakeUnitOfWork

pytestmark = pytest.mark.unit


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def tenant_id():  # type: ignore[no-untyped-def]
    return uuid4()


@pytest.fixture
def user_id():  # type: ignore[no-untyped-def]
    return uuid4()


# ── GetAlertPreferencesUseCase ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_alert_preferences_returns_defaults_when_empty(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    uc = GetAlertPreferencesUseCase()
    prefs, suppressions = await uc.execute(user_id, tenant_id, uow)

    assert len(suppressions) == 0
    # All AlertType values should be present with enabled=True by default
    pref_map = {p.alert_type: p for p in prefs}
    for alert_type in AlertType:
        assert alert_type in pref_map
        assert pref_map[alert_type].enabled is True


@pytest.mark.asyncio
async def test_get_alert_preferences_returns_existing_rows(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    # Pre-insert a disabled preference for SIGNAL
    upsert_uc = UpsertAlertPreferenceUseCase()
    await upsert_uc.execute(
        UpsertAlertPreferenceCommand(user_id=user_id, tenant_id=tenant_id, alert_type="signal", enabled=False),
        uow,
    )

    get_uc = GetAlertPreferencesUseCase()
    prefs, _ = await get_uc.execute(user_id, tenant_id, uow)

    pref_map = {p.alert_type: p for p in prefs}
    assert pref_map[AlertType.SIGNAL].enabled is False
    # Others default to enabled=True
    assert pref_map[AlertType.CONTRADICTION].enabled is True


# ── UpsertAlertPreferenceUseCase ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_preference_persists_enabled_false(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    uc = UpsertAlertPreferenceUseCase()
    pref = await uc.execute(
        UpsertAlertPreferenceCommand(user_id=user_id, tenant_id=tenant_id, alert_type="contradiction", enabled=False),
        uow,
    )
    assert pref.enabled is False
    assert pref.alert_type == AlertType.CONTRADICTION

    stored = await uow.alert_preferences.get_by_user(user_id, tenant_id)
    assert any(p.alert_type == AlertType.CONTRADICTION and not p.enabled for p in stored)


@pytest.mark.asyncio
async def test_upsert_invalid_alert_type_raises(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    uc = UpsertAlertPreferenceUseCase()
    with pytest.raises(ValidationError):
        await uc.execute(
            UpsertAlertPreferenceCommand(user_id=user_id, tenant_id=tenant_id, alert_type="not_a_type", enabled=True),
            uow,
        )


# ── SetEntitySuppressionUseCase ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_entity_suppression(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    entity_id = uuid4()
    uc = SetEntitySuppressionUseCase()
    suppression = await uc.execute(
        SetEntitySuppressionCommand(user_id=user_id, tenant_id=tenant_id, entity_id=entity_id),
        uow,
    )
    assert suppression.entity_id == entity_id
    stored = await uow.entity_suppressions.get(user_id, entity_id)
    assert stored is not None


# ── RemoveEntitySuppressionUseCase ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remove_entity_suppression_not_found_raises(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    uc = RemoveEntitySuppressionUseCase()
    with pytest.raises(AlertPreferenceNotFoundError):
        await uc.execute(
            RemoveEntitySuppressionCommand(user_id=user_id, tenant_id=tenant_id, entity_id=uuid4()),
            uow,
        )


# ── N-004: Edge case tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_alert_preferences_mixed_defaults(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    """When ONE preference exists (SIGNAL disabled), GetAlertPreferencesUseCase returns ALL
    AlertType values with the persisted one having enabled=False and all others enabled=True."""
    upsert_uc = UpsertAlertPreferenceUseCase()
    await upsert_uc.execute(
        UpsertAlertPreferenceCommand(user_id=user_id, tenant_id=tenant_id, alert_type="signal", enabled=False),
        uow,
    )

    get_uc = GetAlertPreferencesUseCase()
    prefs, _ = await get_uc.execute(user_id, tenant_id, uow)

    # All AlertType values must be present
    assert len(prefs) == len(AlertType)

    pref_map = {p.alert_type: p for p in prefs}
    for alert_type in AlertType:
        assert alert_type in pref_map, f"Missing alert_type: {alert_type}"

    # The persisted preference must have enabled=False
    assert pref_map[AlertType.SIGNAL].enabled is False

    # All other alert types must default to enabled=True
    for alert_type in AlertType:
        if alert_type != AlertType.SIGNAL:
            assert pref_map[alert_type].enabled is True, f"Expected enabled=True for {alert_type}"


@pytest.mark.asyncio
async def test_remove_entity_suppression_happy_path(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    """Successful removal: create suppression, remove it, verify it is gone."""
    entity_id = uuid4()

    # (a) Create suppression
    set_uc = SetEntitySuppressionUseCase()
    await set_uc.execute(
        SetEntitySuppressionCommand(user_id=user_id, tenant_id=tenant_id, entity_id=entity_id),
        uow,
    )
    assert await uow.entity_suppressions.get(user_id, entity_id) is not None

    # (b) Remove suppression
    remove_uc = RemoveEntitySuppressionUseCase()
    await remove_uc.execute(
        RemoveEntitySuppressionCommand(user_id=user_id, tenant_id=tenant_id, entity_id=entity_id),
        uow,
    )

    # (c) Verify it is gone — get returns None
    assert await uow.entity_suppressions.get(user_id, entity_id) is None


@pytest.mark.asyncio
async def test_set_entity_suppression_multiple_independent(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    """Set suppression for entity_A and entity_B, remove entity_A, verify entity_B still exists."""
    entity_a = uuid4()
    entity_b = uuid4()

    set_uc = SetEntitySuppressionUseCase()
    remove_uc = RemoveEntitySuppressionUseCase()

    # (a) Set suppression for both entities
    await set_uc.execute(
        SetEntitySuppressionCommand(user_id=user_id, tenant_id=tenant_id, entity_id=entity_a),
        uow,
    )
    await set_uc.execute(
        SetEntitySuppressionCommand(user_id=user_id, tenant_id=tenant_id, entity_id=entity_b),
        uow,
    )

    # (b) Remove entity_A
    await remove_uc.execute(
        RemoveEntitySuppressionCommand(user_id=user_id, tenant_id=tenant_id, entity_id=entity_a),
        uow,
    )

    # (c) Verify entity_A is gone but entity_B still exists
    assert await uow.entity_suppressions.get(user_id, entity_a) is None
    assert await uow.entity_suppressions.get(user_id, entity_b) is not None


@pytest.mark.asyncio
async def test_upsert_preference_all_alert_types(uow: FakeUnitOfWork, user_id, tenant_id) -> None:
    """Each AlertType can be upserted with enabled=True and enabled=False."""
    uc = UpsertAlertPreferenceUseCase()

    for alert_type in AlertType:
        for enabled_value in (True, False):
            pref = await uc.execute(
                UpsertAlertPreferenceCommand(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    alert_type=alert_type.value,
                    enabled=enabled_value,
                ),
                uow,
            )
            assert pref.alert_type == alert_type
            assert pref.enabled is enabled_value

    # Final state: all types present, each with enabled=False (last written value)
    stored = await uow.alert_preferences.get_by_user(user_id, tenant_id)
    assert len(stored) == len(AlertType)
    for pref in stored:
        assert pref.enabled is False
