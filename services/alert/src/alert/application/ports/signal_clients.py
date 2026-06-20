"""ABC ports for the read-only signal clients used by poll evaluators (PLAN-0113 W2).

The evaluators in ``application/rules/`` depend only on these interfaces (R25),
never on the concrete ``infrastructure/clients/*`` implementations. This keeps
the evaluators unit-testable with lightweight stubs and isolates the HTTP/JSON
concerns in the infrastructure layer.

All three ports are *read-only* (R9 — cross-service access via REST only) and
*best-effort*: implementations must never raise on transport/HTTP errors; they
return ``None``/empty so the poller treats a flaky upstream as "no observation"
(no state change, no fire) rather than crashing the cycle.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class IS3PriceClient(ABC):
    """Port for S3 market-data reads (price batch + fundamental metric)."""

    @abstractmethod
    async def get_price_batch(self, instrument_ids: list[UUID]) -> dict[UUID, float]:
        """Return ``{instrument_id: last_price}``. Missing instruments are omitted."""

    @abstractmethod
    async def get_fundamental_metric(self, instrument_id: UUID, metric: str) -> float | None:
        """Return the latest numeric value of ``metric`` for an instrument, or None."""


class IS6NewsClient(ABC):
    """Port for S6 news-signal reads (rollup counts + trending momentum)."""

    @abstractmethod
    async def get_news_count_7d(self, instrument_id: UUID) -> int | None:
        """Return the 7-day article count for an instrument, or None on failure."""

    @abstractmethod
    async def get_trending_count(self, entity_id: UUID, window_hours: int) -> int | None:
        """Return the article count for an entity in a trending window, or None."""

    @abstractmethod
    async def get_trending_momentum(self, entity_id: UUID, window_hours: int) -> tuple[float, int] | None:
        """Return ``(delta_pct, count)`` for an entity in a window, or None if absent."""
