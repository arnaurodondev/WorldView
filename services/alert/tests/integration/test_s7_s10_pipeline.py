"""S7 → S10 pipeline continuity test — Milestone M7.

Validates the final hop of the intelligence pipeline:
  graph.state.changed.v1 event → AlertFanoutUseCase.execute()
  → alert row written to alert_db → pending_alerts row created

This simulates what happens when S7 emits a graph.state.changed.v1 event
and S10's IntelligenceConsumer routes it to fan-out.

Milestone M7 (from PLAN-0001-C): full pipeline validated
  S4 → S5 → S6 → S7 → S10
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alert.infrastructure.db.models import AlertModel
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
from sqlalchemy import select

if TYPE_CHECKING:
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _graph_state_changed_event(entity_id: str) -> dict[str, Any]:
    """Simulate a graph.state.changed.v1 event as emitted by S7."""
    return {
        "event_id": str(uuid4()),
        "event_type": "graph.state.changed",
        "schema_version": 1,
        "occurred_at": "2026-03-29T10:00:00+00:00",
        "primary_entity_id": entity_id,
        "change_type": "relation_added",
        "confidence_delta": 0.15,
        "is_backfill": False,
        "correlation_id": str(uuid4()),
    }


@pytest.mark.integration
async def test_s7_graph_event_creates_alert(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """M7: graph.state.changed.v1 → alert written to alert_db (pipeline continuity)."""
    entity_id = str(uuid4())
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    # S1 returns a watcher for this entity
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
    event = _graph_state_changed_event(entity_id)
    result = await fanout.execute(event, "graph.state.changed.v1")

    # M7 gate: alert must be in alert_db
    assert result.suppressed is False
    assert result.alert_id is not None

    stmt = select(AlertModel).where(AlertModel.alert_id == result.alert_id)
    alert_row = (await db_session.execute(stmt)).scalar_one_or_none()
    assert alert_row is not None, "M7: alert row missing from alert_db"
    assert str(alert_row.entity_id) == entity_id
    assert alert_row.alert_type == "GRAPH_CHANGE"
    assert alert_row.source_topic == "graph.state.changed.v1"


@pytest.mark.integration
async def test_s7_graph_event_creates_pending_alert(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """M7: graph.state.changed.v1 → pending_alerts row for the watcher user."""
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
    result = await fanout.execute(_graph_state_changed_event(entity_id), "graph.state.changed.v1")

    assert result.pending_count == 1

    pending_repo = PendingAlertRepository(db_session)
    pending = await pending_repo.list_by_user(UUID(user_id), limit=10)
    assert any(str(p.alert_id) == str(result.alert_id) for p in pending), "M7: pending_alerts row missing for user"


@pytest.mark.integration
async def test_s7_backfill_graph_event_suppressed(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """M7: backfill graph.state.changed.v1 events must be suppressed."""
    entity_id = str(uuid4())

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case
    backfill_event = {**_graph_state_changed_event(entity_id), "is_backfill": True}
    result = await fanout.execute(backfill_event, "graph.state.changed.v1")

    assert result.suppressed is True
    assert result.suppression_reason == "backfill"


@pytest.mark.integration
async def test_pipeline_api_returns_alert_after_fanout(
    integration_app: Any,
    integration_client: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """M7: after fan-out, GET /api/v1/alerts/pending returns the alert for the user."""
    from tests.integration.conftest import INTEGRATION_USER_ID

    entity_id = str(uuid4())
    # Use the JWT's sub UUID as user_id so CurrentUserIdDep can find alerts (BP-165)
    user_id = INTEGRATION_USER_ID
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
    result = await fanout.execute(_graph_state_changed_event(entity_id), "graph.state.changed.v1")
    assert result.suppressed is False

    resp = await integration_client.get(f"/api/v1/alerts/pending?user_id={user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    alert_ids = [a["alert_id"] for a in data["alerts"]]
    assert str(result.alert_id) in alert_ids, "M7: alert not visible via GET /api/v1/alerts/pending"
