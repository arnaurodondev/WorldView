"""S10Client — S9-proxied alert service HTTP adapter (PLAN-0082 Wave A).

WHY S9-proxied (not S10 direct): R14/R7 — all internal service-to-service calls go through
S9 for auth and rate limiting. The concrete endpoint path is the S9 proxy route that
forwards to S10 (Alert service) behind authentication.

R9 safe degradation: all methods return [] on any HTTP or network error so callers
never receive an exception from this adapter.
"""

from __future__ import annotations

import structlog  # type: ignore[import-untyped]

from rag_chat.infrastructure.clients.base import BaseUpstreamClient

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class S10Client(BaseUpstreamClient):
    """Concrete HTTP adapter for the S9-proxied alert (S10) endpoints.

    Implements S10Port Protocol (application/ports/upstream_clients.py).
    Returns [] on any HTTP or network error (R9 safe degradation).
    Inherits X-Internal-JWT propagation from BaseUpstreamClient._get.
    """

    async def get_alerts(self, user_id: str, tenant_id: str, limit: int = 20) -> list[dict]:
        """GET /v1/alerts/pending → list of active alerts for the user.

        Passes X-User-Id and X-Tenant-Id headers so S10 can scope results to the
        authenticated user. The limit query param caps the response size.

        Returns [] on any HTTP or network error (R9 safe degradation).
        BaseUpstreamClient._get() returns a dict on success (or {} on error).
        S10 wraps the list under a top-level key — we handle both a direct list
        response (if S10 changes its contract) and the standard envelope pattern.

        WHY extra_headers: S10 needs the user + tenant scope to filter pending
        alerts. We cannot rely on the X-Internal-JWT alone because S10 uses that
        for service authentication, not per-user filtering.
        """
        extra_headers: dict[str, str] = {
            "X-User-Id": user_id,
            "X-Tenant-Id": tenant_id,
        }
        params: dict = {"limit": limit}

        # _get returns {} on any error (R9 contract from BaseUpstreamClient)
        raw = await self._get(
            "/v1/alerts/pending",
            params=params,
            extra_headers=extra_headers,
        )

        if not raw:
            # Either upstream error (BaseUpstreamClient already logged it) or empty response
            return []

        # S10 may return {"alerts": [...]} envelope or a direct list under a "data" key.
        # Support both patterns for forward-compatibility.
        alerts = raw.get("alerts") or raw.get("data") or raw.get("results") or []
        # Guard: if the caller receives a non-list value, degrade gracefully
        if not isinstance(alerts, list):
            log.warning(
                "s10_unexpected_response_shape",
                expected="list",
                got=type(alerts).__name__,
            )
            return []
        return alerts  # type: ignore[return-value]
