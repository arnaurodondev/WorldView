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


# ─────────────────────────────────────────────────────────────────────────────
# PLAN-0049 T-A-1-02 — enrichment column round-trip (F-QA-01)
# Pin that title / ticker / entity_name / signal_label survive the
# Alert → AlertModel → _to_entity round-trip. A typo in `save()` or
# `_to_entity()` would otherwise only surface in production.
# ─────────────────────────────────────────────────────────────────────────────


class TestAlertRepositoryEnrichmentColumns:
    @pytest.mark.unit
    async def test_save_persists_all_enrichment_columns(self) -> None:
        """AlertModel receives all four enrichment columns from Alert."""
        alert = _make_alert()
        alert.title = "Apple Inc.: Bullish guidance"
        alert.ticker = "AAPL"
        alert.entity_name = "Apple Inc."
        alert.signal_label = "Bullish guidance"

        captured: list = []

        mock_session = AsyncMock()
        mock_session.add = MagicMock(side_effect=lambda m: captured.append(m))
        mock_session.flush = AsyncMock()

        repo = AlertRepository(session=mock_session)
        await repo.save(alert)

        assert captured, "AlertModel was not added to the session"
        model = captured[0]
        assert model.title == "Apple Inc.: Bullish guidance"
        assert model.ticker == "AAPL"
        assert model.entity_name == "Apple Inc."
        assert model.signal_label == "Bullish guidance"

    @pytest.mark.unit
    async def test_save_persists_null_enrichment_columns(self) -> None:
        """When Alert has None defaults for all enrichment fields, the model rows them as None."""
        alert = _make_alert()  # defaults to None for all four

        captured: list = []
        mock_session = AsyncMock()
        mock_session.add = MagicMock(side_effect=lambda m: captured.append(m))
        mock_session.flush = AsyncMock()

        repo = AlertRepository(session=mock_session)
        await repo.save(alert)

        model = captured[0]
        assert model.title is None
        assert model.ticker is None
        assert model.entity_name is None
        assert model.signal_label is None

    @pytest.mark.unit
    async def test_to_entity_round_trips_enrichment_columns(self) -> None:
        """_to_entity reads all four enrichment columns back into Alert."""
        from alert.infrastructure.db.models import AlertModel

        row = AlertModel(
            alert_id=uuid4(),
            entity_id=uuid4(),
            alert_type="SIGNAL",
            source_event_id=uuid4(),
            source_topic="nlp.signal.detected.v1",
            payload={},
            dedup_key="z1",
            severity="low",
            tenant_id=None,
            created_at=datetime.now(UTC),
            title="Apple Inc.: Bullish guidance",
            ticker="AAPL",
            entity_name="Apple Inc.",
            signal_label="Bullish guidance",
        )

        entity = AlertRepository._to_entity(row)

        assert entity.title == "Apple Inc.: Bullish guidance"
        assert entity.ticker == "AAPL"
        assert entity.entity_name == "Apple Inc."
        assert entity.signal_label == "Bullish guidance"

    @pytest.mark.unit
    async def test_to_entity_round_trips_null_enrichment_columns(self) -> None:
        """Legacy rows (NULL enrichment columns) round-trip cleanly to None."""
        from alert.infrastructure.db.models import AlertModel

        row = AlertModel(
            alert_id=uuid4(),
            entity_id=uuid4(),
            alert_type="SIGNAL",
            source_event_id=uuid4(),
            source_topic="nlp.signal.detected.v1",
            payload={},
            dedup_key="z2",
            severity="low",
            tenant_id=None,
            created_at=datetime.now(UTC),
            title=None,
            ticker=None,
            entity_name=None,
            signal_label=None,
        )

        entity = AlertRepository._to_entity(row)

        assert entity.title is None
        assert entity.ticker is None
        assert entity.entity_name is None
        assert entity.signal_label is None
