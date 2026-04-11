"""Unit tests for AlertRepository — D-2: tenant_id persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from alert.domain.entities import Alert
from alert.domain.enums import AlertSeverity, AlertType
from alert.infrastructure.db.repositories.alert import AlertRepository


def _make_alert(*, tenant_id: UUID | None = None) -> Alert:
    return Alert(
        alert_id=uuid4(),
        entity_id=uuid4(),
        alert_type=AlertType.SIGNAL,
        severity=AlertSeverity.LOW,
        source_event_id=uuid4(),
        source_topic="nlp.signal.detected.v1",
        payload={},
        dedup_key="testkey-abc",
        created_at=datetime.now(UTC),
        tenant_id=tenant_id,
    )


class TestAlertRepositoryTenantId:
    @pytest.mark.unit
    async def test_alert_saved_with_tenant_id(self) -> None:
        """AlertModel.tenant_id is populated when alert.tenant_id is set."""
        tenant_id = uuid4()
        alert = _make_alert(tenant_id=tenant_id)

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        saved_models: list = []

        def _capture_add(model: object) -> None:
            saved_models.append(model)

        mock_session.add = MagicMock(side_effect=_capture_add)

        repo = AlertRepository(session=mock_session)
        await repo.save(alert)

        assert len(saved_models) == 1
        model = saved_models[0]
        assert model.tenant_id == tenant_id

    @pytest.mark.unit
    async def test_alert_saved_with_null_tenant_id(self) -> None:
        """AlertModel.tenant_id is NULL when alert.tenant_id is None — no error raised."""
        alert = _make_alert(tenant_id=None)

        mock_session = AsyncMock()
        saved_models: list = []

        def _capture_add(model: object) -> None:
            saved_models.append(model)

        mock_session.add = MagicMock(side_effect=_capture_add)
        mock_session.flush = AsyncMock()

        repo = AlertRepository(session=mock_session)
        await repo.save(alert)  # must not raise

        assert len(saved_models) == 1
        model = saved_models[0]
        assert model.tenant_id is None

    @pytest.mark.unit
    async def test_to_entity_round_trips_tenant_id(self) -> None:
        """_to_entity maps tenant_id from AlertModel back to Alert.tenant_id."""
        from alert.infrastructure.db.models import AlertModel

        tenant_id = uuid4()
        row = AlertModel(
            alert_id=uuid4(),
            entity_id=uuid4(),
            alert_type="SIGNAL",
            source_event_id=uuid4(),
            source_topic="nlp.signal.detected.v1",
            payload={},
            dedup_key="x",
            severity="low",
            tenant_id=tenant_id,
            created_at=datetime.now(UTC),
        )

        entity = AlertRepository._to_entity(row)

        assert entity.tenant_id == tenant_id

    @pytest.mark.unit
    async def test_to_entity_round_trips_null_tenant_id(self) -> None:
        """_to_entity maps NULL tenant_id from AlertModel back to None."""
        from alert.infrastructure.db.models import AlertModel

        row = AlertModel(
            alert_id=uuid4(),
            entity_id=uuid4(),
            alert_type="SIGNAL",
            source_event_id=uuid4(),
            source_topic="nlp.signal.detected.v1",
            payload={},
            dedup_key="y",
            severity="low",
            tenant_id=None,
            created_at=datetime.now(UTC),
        )

        entity = AlertRepository._to_entity(row)

        assert entity.tenant_id is None
