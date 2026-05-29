"""EarningsCalendarClient — HTTP adapter for market-data /internal/v1/calendar/earnings.

PLAN-0102 Wave 3 T-W3-03.

Speaks to market-data directly via the internal-JWT pattern (same precedent
as ``S1Client`` and ``MarketTapeClient``). NOT the same as the existing
``S3BriefClient.get_earnings_calendar`` which queries S7 temporal-events
through S9 (used by the public dashboard) — this client targets the
EODHD-sourced ``earnings_calendar`` table on S3 which carries consensus
EPS and the before/after market session tag, both of which the brief
formatter wants.

R9 safe degradation: HTTP / network error returns an empty result.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import httpx
import structlog  # type: ignore[import-untyped]

from rag_chat.application.ports.upstream_clients import (
    EarningsCalendarResult,
    EarningsEvent,
)
from rag_chat.infrastructure.clients.base import BaseUpstreamClient

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class EarningsCalendarClient(BaseUpstreamClient):
    """Concrete HTTP adapter for /internal/v1/calendar/earnings.

    Implements ``EarningsCalendarPort``. No client-side Valkey cache —
    market-data caches the response server-side for 5 min already.
    """

    async def get_earnings(self, days_ahead: int) -> EarningsCalendarResult:
        """GET /internal/v1/calendar/earnings?from=today&to=today+days_ahead.

        ``days_ahead`` is clamped to [0, 90] to match the market-data router's
        90-day cap; values outside that range silently clamp rather than 422
        because the brief generator's intent ("the next week" / "the next
        month") is well-defined even when callers pass odd values.
        """
        # Clamp to the server-side window. Doing this client-side as well
        # converts a potential 422 into a successful empty response which is
        # easier for the brief to reason about.
        clamped_days = max(0, min(days_ahead, 90))

        from_date = datetime.now(tz=UTC).date()
        to_date = from_date + timedelta(days=clamped_days)

        # ``from`` is a Python keyword so we pass it via a dict, not a kwarg.
        params = {"from": from_date.isoformat(), "to": to_date.isoformat()}

        from rag_chat.infrastructure.clients.auth_context import get_current_jwt

        headers: dict[str, str] = {}
        jwt = get_current_jwt()
        if jwt:
            headers["X-Internal-JWT"] = jwt

        path = "/internal/v1/calendar/earnings"
        try:
            resp = await self._client.get(path, params=params, headers=headers)
            resp.raise_for_status()
            raw: dict = resp.json()
        except httpx.TimeoutException:
            logger.warning("upstream_timeout", path=path)
            return EarningsCalendarResult(from_date=from_date, to_date=to_date, events=[])
        except httpx.HTTPStatusError as exc:
            logger.warning("upstream_http_error", path=path, status=exc.response.status_code)
            return EarningsCalendarResult(from_date=from_date, to_date=to_date, events=[])
        except httpx.RequestError as exc:
            logger.warning("upstream_request_error", path=path, error=str(exc))
            return EarningsCalendarResult(from_date=from_date, to_date=to_date, events=[])

        # Parse the bracket dates. The market-data router serialises ``from_``
        # as ``"from"`` via Pydantic alias, so we honour that wire key here.
        parsed_from = _parse_date(raw.get("from"), default=from_date)
        parsed_to = _parse_date(raw.get("to"), default=to_date)

        events: list[EarningsEvent] = []
        for e in raw.get("events") or []:
            try:
                events.append(
                    EarningsEvent(
                        symbol=str(e["symbol"]),
                        entity_id=(UUID(e["entity_id"]) if e.get("entity_id") else None),
                        report_date=date.fromisoformat(str(e["report_date"])),
                        when=(str(e["when"]) if e.get("when") is not None else None),
                        period=(str(e["period"]) if e.get("period") is not None else None),
                        consensus_eps=(float(e["consensus_eps"]) if e.get("consensus_eps") is not None else None),
                        consensus_rev_usd=(
                            float(e["consensus_rev_usd"]) if e.get("consensus_rev_usd") is not None else None
                        ),
                    )
                )
            except (KeyError, ValueError, TypeError):
                # Single-row malformed payload should not crash the brief.
                logger.warning("earnings_calendar_row_parse_error", path=path, raw=e)
                continue

        return EarningsCalendarResult(from_date=parsed_from, to_date=parsed_to, events=events)


def _parse_date(value: object, *, default: date) -> date:
    """Best-effort date parser — falls back to ``default`` on any error.

    Kept module-private and tiny because the brief generator's preferred
    behaviour is "always return a date" rather than "raise on schema drift".
    """
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            logger.warning("earnings_calendar_date_parse_error", value=value)
    return default


__all__ = ["EarningsCalendarClient"]
