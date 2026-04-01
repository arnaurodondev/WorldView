"""Integration tests — alert deduplication within the 300s window.

Tests:
  - Two fan-out calls with same entity+type in same window → second suppressed
  - Same entity+type in a different window → not suppressed
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

if TYPE_CHECKING:
    from alert.application.use_cases.alert_fanout import AlertFanoutUseCase

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _signal_event(entity_id: str) -> dict[str, Any]:
    return {
        "event_id": str(uuid4()),
        "event_type": "nlp.signal.detected",
        "occurred_at": "2026-03-29T10:00:00+00:00",
        "subject_entity_id": entity_id,
        "claimer_entity_id": None,
        "is_backfill": False,
        "correlation_id": None,
    }


@pytest.mark.integration
async def test_dedup_suppresses_second_event_in_same_window(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """Second fan-out for same entity+type in same window is deduplicated."""
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

    # First call — should succeed
    result1 = await fanout.execute(_signal_event(entity_id), "nlp.signal.detected.v1")
    assert result1.suppressed is False
    assert result1.alert_id is not None

    # Second call with same entity+type in same window (default 300s)
    result2 = await fanout.execute(_signal_event(entity_id), "nlp.signal.detected.v1")
    assert result2.suppressed is True
    assert result2.suppression_reason == "dedup"


@pytest.mark.integration
async def test_different_alert_types_not_deduped(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """SIGNAL and GRAPH_CHANGE for the same entity are not deduplicated."""
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

    signal_event = {
        "event_id": str(uuid4()),
        "event_type": "nlp.signal.detected",
        "occurred_at": "2026-03-29T10:00:00+00:00",
        "subject_entity_id": entity_id,
        "is_backfill": False,
    }
    graph_event = {
        "event_id": str(uuid4()),
        "event_type": "graph.state.changed",
        "occurred_at": "2026-03-29T10:00:00+00:00",
        "primary_entity_id": entity_id,
        "is_backfill": False,
    }

    result_signal = await fanout.execute(signal_event, "nlp.signal.detected.v1")
    result_graph = await fanout.execute(graph_event, "graph.state.changed.v1")

    assert result_signal.suppressed is False
    assert result_graph.suppressed is False


@pytest.mark.integration
async def test_different_entities_not_deduped(
    integration_app: Any,
    db_session: Any,
    httpserver: Any,
) -> None:
    """Signals for two different entities are independent."""
    entity_id_a = str(uuid4())
    entity_id_b = str(uuid4())
    user_id = str(uuid4())
    watchlist_id = str(uuid4())

    for eid in (entity_id_a, entity_id_b):
        httpserver.expect_request(
            f"/internal/v1/watchlists/by-entity/{eid}",
            method="GET",
        ).respond_with_json(
            {
                "entity_id": eid,
                "watchers": [{"user_id": user_id, "watchlist_id": watchlist_id, "alert_types": []}],
            }
        )

    fanout: AlertFanoutUseCase = integration_app.state.fanout_use_case

    result_a = await fanout.execute(_signal_event(entity_id_a), "nlp.signal.detected.v1")
    result_b = await fanout.execute(_signal_event(entity_id_b), "nlp.signal.detected.v1")

    assert result_a.suppressed is False
    assert result_b.suppressed is False
