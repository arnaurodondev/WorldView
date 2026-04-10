"""Integration tests — alert fan-out end-to-end with real DB.

Tests:
  - mock S1 returns watchers → alert + pending row written to DB
  - fan-out creates outbox event
  - backfill events are suppressed
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alert.domain.enums import AlertSeverity, AlertType
from alert.infrastructure.db.models import AlertModel, OutboxEventModel
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
from sqlalchemy import func, select, text

if TYPE_CHECKING:
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _signal_event(entity_id: str, is_backfill: bool = False) -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "event_type": "nlp.signal.detected",
        "occurred_at": "2026-03-29T10:00:00+00:00",
        "subject_entity_id": entity_id,
        "claimer_entity_id": None,
        "is_backfill": is_backfill,
        "correlation_id": None,
    }


@pytest.mark.integration
async def test_fanout_creates_alert_in_db(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """Fan-out end-to-end: mock S1 returns user → alert + pending row in DB."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": entity_id,
            "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
        }
    )

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result = await fanout.execute(_signal_event(entity_id), "nlp.signal.detected.v1")

    assert result.suppressed is False
    assert result.watchers_count == 1
    assert result.alert_id is not None

    # Verify alert row in DB
    stmt = select(AlertModel).where(AlertModel.alert_id == result.alert_id)
    row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert str(row.entity_id) == entity_id
    assert row.alert_type == str(AlertType.SIGNAL)


@pytest.mark.integration
async def test_fanout_creates_pending_row_in_db(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """Fan-out creates a pending_alerts row for each watcher."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": entity_id,
            "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
        }
    )

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result = await fanout.execute(_signal_event(entity_id), "nlp.signal.detected.v1")

    assert result.pending_count == 1

    # Verify pending row
    pending_repo = PendingAlertRepository(db_session)
    pending = await pending_repo.list_by_user(UUID(user_id), limit=10)
    assert len(pending) >= 1
    pending_ids = [str(p.alert_id) for p in pending]
    assert str(result.alert_id) in pending_ids


@pytest.mark.integration
async def test_fanout_creates_outbox_event(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """Fan-out appends an outbox event for each watcher."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": entity_id,
            "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
        }
    )

    # Count outbox events before
    count_before = (await db_session.execute(select(func.count()).select_from(OutboxEventModel))).scalar_one()

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result = await fanout.execute(_signal_event(entity_id), "nlp.signal.detected.v1")

    assert result.suppressed is False

    count_after = (await db_session.execute(select(func.count()).select_from(OutboxEventModel))).scalar_one()
    assert count_after == count_before + 1


@pytest.mark.integration
async def test_fanout_suppresses_backfill(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """Backfill events are suppressed — no alert written to DB."""
    entity_id = str(uuid4())

    count_before = (await db_session.execute(select(func.count()).select_from(AlertModel))).scalar_one()

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result = await fanout.execute(_signal_event(entity_id, is_backfill=True), "nlp.signal.detected.v1")

    assert result.suppressed is True
    assert result.suppression_reason == "backfill"

    count_after = (await db_session.execute(select(func.count()).select_from(AlertModel))).scalar_one()
    assert count_after == count_before  # no new alerts


@pytest.mark.integration
async def test_fanout_no_watchers_writes_nothing(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """When S1 returns no watchers, nothing is written to DB."""
    entity_id = str(uuid4())

    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_json({"entity_id": entity_id, "watchers": []})

    count_before = (await db_session.execute(select(func.count()).select_from(AlertModel))).scalar_one()

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result = await fanout.execute(_signal_event(entity_id), "nlp.signal.detected.v1")

    assert result.suppressed is False
    assert result.watchers_count == 0

    count_after = (await db_session.execute(select(func.count()).select_from(AlertModel))).scalar_one()
    assert count_after == count_before


# ── Severity integration tests (PRD-0021 Wave A-4) ───────────────────────────


@pytest.mark.integration
async def test_alert_severity_stored_in_db(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """Alert with CRITICAL market_impact_score (0.9) is stored with severity='critical' in DB."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": entity_id,
            "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
        }
    )

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result = await fanout.execute(
        _signal_event(entity_id),
        "nlp.signal.detected.v1",
        market_impact_score=0.9,  # above CRITICAL threshold of 0.85
    )

    assert result.suppressed is False
    assert result.alert_id is not None

    stmt = select(AlertModel).where(AlertModel.alert_id == result.alert_id)
    row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert row.severity == str(AlertSeverity.CRITICAL)


@pytest.mark.integration
async def test_pending_alerts_returns_severity(
    integration_app: Any,
    integration_client: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """GET /api/v1/alerts/pending includes a severity field on each returned alert."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_id}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": entity_id,
            "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
        }
    )

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result = await fanout.execute(
        _signal_event(entity_id),
        "nlp.signal.detected.v1",
        market_impact_score=0.7,  # HIGH (≥0.65)
    )
    assert result.suppressed is False

    resp = await integration_client.get(f"/api/v1/alerts/pending?user_id={user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    item = next(a for a in data["alerts"] if str(a["alert_id"]) == str(result.alert_id))
    assert item["severity"] == "high"


@pytest.mark.integration
async def test_pending_alerts_min_severity_filter(
    integration_app: Any,
    integration_client: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """?min_severity=high returns only HIGH and CRITICAL alerts from DB."""
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    # Create LOW alert
    entity_low = str(uuid4())
    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_low}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": entity_low,
            "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
        }
    )

    # Create HIGH alert
    entity_high = str(uuid4())
    httpserver.expect_request(
        f"/internal/v1/watchlists/by-entity/{entity_high}",
        method="GET",
    ).respond_with_json(
        {
            "entity_id": entity_high,
            "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
        }
    )

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    result_low = await fanout.execute(
        _signal_event(entity_low),
        "nlp.signal.detected.v1",
        market_impact_score=0.1,  # LOW
    )
    result_high = await fanout.execute(
        _signal_event(entity_high),
        "nlp.signal.detected.v1",
        market_impact_score=0.75,  # HIGH
    )
    assert result_low.suppressed is False
    assert result_high.suppressed is False

    resp = await integration_client.get(f"/api/v1/alerts/pending?user_id={user_id}&min_severity=high")
    assert resp.status_code == 200
    data = resp.json()

    returned_alert_ids = {a["alert_id"] for a in data["alerts"]}
    # HIGH alert should be present
    assert str(result_high.alert_id) in returned_alert_ids
    # LOW alert should be absent
    assert str(result_low.alert_id) not in returned_alert_ids
    # All returned items must have severity >= high
    for item in data["alerts"]:
        assert item["severity"] in ("high", "critical")


@pytest.mark.integration
async def test_db_migration_existing_rows_default_low(
    db_session: Any,
) -> None:
    """Rows inserted without an explicit severity column value default to 'low' (server_default)."""
    from common.ids import new_uuid7  # type: ignore[import-untyped]

    alert_id = new_uuid7()
    entity_id = new_uuid7()
    source_event_id = new_uuid7()
    dedup_key = f"test-default-severity-{alert_id}"

    # Insert without setting severity — relies on server_default='low'
    await db_session.execute(
        text(
            "INSERT INTO alerts"
            " (alert_id, entity_id, alert_type, source_event_id, source_topic, payload, dedup_key)"
            " VALUES (:alert_id, :entity_id, :alert_type, :source_event_id,"
            " :source_topic, cast(:payload AS jsonb), :dedup_key)"
        ),
        {
            "alert_id": str(alert_id),
            "entity_id": str(entity_id),
            "alert_type": "SIGNAL",
            "source_event_id": str(source_event_id),
            "source_topic": "nlp.signal.detected.v1",
            "payload": "{}",
            "dedup_key": dedup_key,
        },
    )
    await db_session.flush()

    stmt = select(AlertModel).where(AlertModel.alert_id == alert_id)
    row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert row is not None
    assert row.severity == "low"
