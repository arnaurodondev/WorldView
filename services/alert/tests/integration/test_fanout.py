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
from alert.domain.enums import AlertType
from alert.infrastructure.db.models import AlertModel, OutboxEventModel
from alert.infrastructure.db.repositories.pending_alert import PendingAlertRepository
from sqlalchemy import func, select

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
