"""S5 Alert Service HTTP client adapter.

Endpoints:
  GET /api/v1/alerts/pending                              -> pending alerts (JWT-sub scoped)
  GET /internal/v1/users/{user_id}/alerts/pending         -> service-caller endpoint (PLAN-0094)

All errors (timeout, HTTP 4xx/5xx, connection refused) return empty lists
— never raises to the caller (R9 safe degradation).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog  # type: ignore[import-untyped]

from rag_chat.application.models.briefing_context import AlertSummary
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class S5Client(BaseUpstreamClient):
    """HTTP adapter for S5 Alert Service — fetches pending alerts for briefing context."""

    def __init__(self, base_url: str, timeout: float = 10.0, *, internal_jwt: str | None = None) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._internal_jwt = internal_jwt

    async def get_pending_alerts(
        self,
        user_id: str,
        tenant_id: str,
        *,
        min_severity: str = "medium",
        limit: int = 20,
        x_internal_jwt: str | None = None,
    ) -> list[AlertSummary]:
        """GET /api/v1/alerts/pending — returns [] on any error (graceful degradation)."""
        # Per-call JWT takes priority; fall back to constructor-level JWT.
        jwt = x_internal_jwt or self._internal_jwt
        headers: dict[str, str] = {}
        if jwt:
            headers["X-Internal-JWT"] = jwt
        try:
            resp = await self._client.get(
                "/api/v1/alerts/pending",
                params={"min_severity": min_severity, "limit": limit},
                headers=headers,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            alerts_raw = data.get("alerts", data if isinstance(data, list) else [])
            if not isinstance(alerts_raw, list):
                alerts_raw = []
            return [
                AlertSummary(
                    alert_id=UUID(str(a.get("alert_id", a.get("id", "00000000-0000-0000-0000-000000000000")))),
                    entity_id=UUID(str(a.get("entity_id", "00000000-0000-0000-0000-000000000000"))),
                    alert_type=str(a.get("alert_type", "")),
                    severity=str(a.get("severity", "")),
                    payload=dict(a.get("payload", {})),
                    created_at=(
                        datetime.fromisoformat(str(a["created_at"])) if "created_at" in a else datetime.now(tz=UTC)
                    ),
                )
                for a in alerts_raw
            ]
        except Exception:
            logger.warning("s5_client_error", path="/api/v1/alerts/pending")
            return []

    async def get_pending_alerts_for_user(
        self,
        user_id: str,
        tenant_id: str,
        *,
        min_severity: str = "medium",
        limit: int = 20,
        x_internal_jwt: str | None = None,
    ) -> list[AlertSummary]:
        """GET /internal/v1/users/{user_id}/alerts/pending — service-caller endpoint.

        Used by the brief pre-generation worker, which holds a single
        service-account JWT and needs to read alerts for arbitrary users.
        The endpoint is gated by an allow-list of service callers on the
        S5 side; this client just forwards the JWT.

        Returns [] on any error (R9 safe degradation).
        """
        # tenant_id is accepted for API parity with get_pending_alerts but is
        # not sent over the wire — tenant scoping is derived from the JWT on S5.
        del tenant_id  # explicit no-op: signature parity with the user-token method
        jwt = x_internal_jwt or self._internal_jwt
        headers: dict[str, str] = {}
        if jwt:
            headers["X-Internal-JWT"] = jwt
        try:
            resp = await self._client.get(
                f"/internal/v1/users/{user_id}/alerts/pending",
                params={"min_severity": min_severity, "limit": limit},
                headers=headers,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            alerts_raw = data.get("alerts", data if isinstance(data, list) else [])
            if not isinstance(alerts_raw, list):
                alerts_raw = []
            return [
                AlertSummary(
                    alert_id=UUID(str(a.get("alert_id", a.get("id", "00000000-0000-0000-0000-000000000000")))),
                    entity_id=UUID(str(a.get("entity_id", "00000000-0000-0000-0000-000000000000"))),
                    alert_type=str(a.get("alert_type", "")),
                    severity=str(a.get("severity", "")),
                    payload=dict(a.get("payload", {})),
                    created_at=(
                        datetime.fromisoformat(str(a["created_at"])) if "created_at" in a else datetime.now(tz=UTC)
                    ),
                )
                for a in alerts_raw
            ]
        except Exception:
            logger.warning("s5_client_error", path="/internal/v1/users/*/alerts/pending")
            return []
