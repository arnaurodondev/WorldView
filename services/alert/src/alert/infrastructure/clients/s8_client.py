"""HTTP client for S8 RAG/Chat internal briefing endpoint.

Calls ``POST {s8_base_url}/internal/v1/briefings`` with an ``X-Internal-Token``
header.  Raises :class:`BriefingClientError` on authentication failure (401),
service unavailability (503), or any transport error.

Timeout is set to 90 s to accommodate large-model inference latency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError

if TYPE_CHECKING:
    from uuid import UUID

    from alert.config import Settings

logger = structlog.get_logger(__name__)


class BriefingClientError(Exception):
    """Raised by :class:`S8BriefingClient` when the briefing request fails."""


class S8BriefingClient:
    """Async HTTP client for the S8 internal briefing endpoint.

    Returns the full response JSON dict on success.  Raises
    :class:`BriefingClientError` on any failure so the caller can decide
    whether to degrade gracefully or abort.
    """

    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        self._base_url = settings.s8_base_url.rstrip("/")
        self._token = settings.s8_internal_token
        self._client = client or AsyncClient(timeout=90.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def request_briefing(
        self,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_context: dict[str, Any],
        market_snapshots: list[dict[str, Any]],
        active_signals: list[dict[str, Any]] | None = None,
        lookback_days: int = 7,
    ) -> dict[str, Any]:
        """Request an AI-generated portfolio risk narrative from S8.

        Args:
            user_id: The user whose portfolio is being briefed.
            tenant_id: Multi-tenant scope.
            portfolio_context: Portfolio context dict from S1.
            market_snapshots: OHLCV + fundamentals per holding.
            active_signals: Recent S10 alert signals (optional).
            lookback_days: Lookback period for news/signals (1-30).

        Returns:
            The S8 response dict (``narrative``, ``risk_summary``,
            ``citations``, ``generated_at``).

        Raises:
            BriefingClientError: On 401 (bad token), 503 (LLM unavailable),
                or any transport failure.
        """
        url = f"{self._base_url}/internal/v1/briefings"
        payload: dict[str, Any] = {
            "user_id": str(user_id),
            "tenant_id": str(tenant_id),
            "portfolio_context": portfolio_context,
            "market_snapshots": market_snapshots,
            "active_signals": active_signals or [],
            "lookback_days": lookback_days,
        }
        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers={
                    "X-Internal-Token": self._token,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            logger.debug("s8_briefing_received", user_id=str(user_id))
            return data
        except HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("s8_briefing_failed", user_id=str(user_id), status=status)
            raise BriefingClientError(f"S8 briefing error {status}: {exc.response.text}") from exc
        except RequestError as exc:
            logger.warning("s8_briefing_transport_error", user_id=str(user_id), error=str(exc))
            raise BriefingClientError(f"S8 transport error: {exc}") from exc
