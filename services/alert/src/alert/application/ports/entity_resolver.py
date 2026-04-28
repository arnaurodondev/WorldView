"""EntityNameResolverPort — application port for resolving entity_id → (name, ticker).

WHY THIS PORT EXISTS (PLAN-0048 Wave B-1):
The AlertFanoutUseCase enriches outgoing alert payloads with `entity_name` and
`ticker` so the frontend (RecentAlerts, AlertDetailSheet) can render
human-readable text without an extra round-trip per alert. Hexagonal
architecture (R12 + R13) requires the use case to depend on an *abstract* port,
not the concrete S7 HTTP client — that lets us mock it in unit tests and swap
implementations (e.g. an in-memory cache for E2E tests) without touching the
use case.

Returns a 2-tuple ``(entity_name, ticker)`` where either element may be
``None`` when the entity is unknown to S7 or the lookup fails. Callers MUST
handle the all-``None`` case gracefully (graceful degradation — never raise).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class EntityNameResolverPort(ABC):
    """Abstract port for resolving an entity_id to ``(canonical_name, ticker)``.

    Implementations:
    - ``S7EntityResolver`` — production HTTP-backed adapter with Valkey cache.
    - In-memory fakes for unit/integration tests.

    Contract:
    - MUST NOT raise on lookup failure — return ``(None, None)`` instead. The
      alert fan-out path is best-effort: a missing name should not block the
      alert from being delivered.
    - SHOULD cache aggressively. The same entity_id may be looked up many times
      per minute under burst load (one alert per watcher per signal).
    """

    @abstractmethod
    async def resolve(self, entity_id: UUID) -> tuple[str | None, str | None]:
        """Resolve ``entity_id`` to ``(canonical_name, ticker)``.

        Args:
        ----
            entity_id: The KG entity UUID (NOT the market-data instrument UUID).

        Returns:
        -------
            A tuple ``(canonical_name, ticker)``. Either element may be ``None``
            when the entity is unknown or the upstream is unavailable.

        """
        ...
