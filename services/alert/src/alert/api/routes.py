"""Alert service REST and WebSocket routes.

Endpoints:
  GET  /api/v1/alerts/pending          — list unacknowledged alerts for the authenticated user
  DELETE /api/v1/alerts/{alert_id}/ack — acknowledge (mark delivered) an alert for the user
  WS   /api/v1/alerts/stream           — WebSocket real-time alert stream
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

from alert.api.dependencies import DbSessionDep
from alert.api.schemas import PendingAlertResponse, PendingAlertsResponse
from alert.application.use_cases.pending_alerts import (
    AcknowledgeAlertUseCase,
    GetPendingAlertsUseCase,
)
from observability import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/api/v1", tags=["alerts"])


# ── REST: GET /api/v1/alerts/pending ─────────────────────────────────────────


@router.get("/alerts/pending", response_model=PendingAlertsResponse)
async def get_pending_alerts(
    request: Request,
    session: DbSessionDep,
    user_id: UUID = Query(..., description="Authenticated user UUID"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PendingAlertsResponse:
    """Return paginated unacknowledged alerts for the given user.

    In production this user_id should come from a JWT/session; for the
    current deployment the caller passes it as a query parameter (S9
    API gateway will inject it from the auth token).
    """
    pairs = await GetPendingAlertsUseCase().execute(session, user_id, limit=limit, offset=offset)

    alert_responses = [
        PendingAlertResponse(
            pending_id=p.pending_id,
            alert_id=p.alert_id,
            entity_id=alert.entity_id,
            alert_type=str(alert.alert_type),
            source_topic=alert.source_topic,
            payload=alert.payload,
            created_at=p.created_at,
        )
        for p, alert in pairs
    ]

    return PendingAlertsResponse(
        alerts=alert_responses,
        total=len(alert_responses),
        limit=limit,
        offset=offset,
    )


# ── REST: DELETE /api/v1/alerts/{alert_id}/ack ───────────────────────────────


@router.delete("/alerts/{alert_id}/ack")
async def acknowledge_alert(
    alert_id: UUID,
    request: Request,
    session: DbSessionDep,
    user_id: UUID = Query(..., description="Authenticated user UUID"),
) -> dict[str, str]:
    """Acknowledge (mark delivered) an alert for the given user.

    Returns 200 on success.  Returns 404 — not 403 — when the alert
    does not exist OR belongs to a different user (avoids user enumeration).
    """
    updated = await AcknowledgeAlertUseCase().execute(session, user_id, alert_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Alert not found or already acknowledged")
    await session.commit()

    logger.debug(  # type: ignore[no-any-return]
        "alert_acknowledged",
        alert_id=str(alert_id),
        user_id=str(user_id),
    )
    return {"status": "acknowledged"}


# ── WebSocket: /api/v1/alerts/stream ─────────────────────────────────────────


@router.websocket("/alerts/stream")
async def alerts_stream(
    websocket: WebSocket,
    user_id: UUID = Query(..., description="Authenticated user UUID"),
) -> None:
    """WebSocket endpoint — pushes real-time alerts to a connected user.

    The client must pass ``user_id`` as a query parameter on connect.
    The connection manager (``app.state.ws_manager``) handles registration
    and broadcasting.  Stale connections are cleaned up on send failure.
    """
    manager = websocket.app.state.ws_manager
    await manager.connect(user_id, websocket)
    try:
        while True:
            # Keep connection alive; we only push server→client.
            # Wait for any client message (ping/close frame).
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception:
        logger.warning(  # type: ignore[no-any-return]
            "websocket_error",
            user_id=str(user_id),
            exc_info=True,
        )
        manager.disconnect(user_id)
