"""ABC port for the S7 graph-path client used by the KG_CONNECTION evaluator (PLAN-0113 W3).

The ``KgConnectionEvaluator`` (and the consumer branch that drives it) depend only
on this interface (R25), never on the concrete ``infrastructure/clients/s7_client.py``
implementation. This keeps the evaluator unit-testable with a lightweight stub.

The port is *read-only* (R9 — cross-service access via REST only) and
*fail-closed*: a connection confirm that cannot be proven (S7 unavailable, AGE
statement-timeout 503, transport error, or timeout) returns ``False`` so an
unproven connection NEVER fires an alert (a false positive is worse here than a
missed edge, which the next graph event will re-evaluate anyway).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class IS7GraphClient(ABC):
    """Port for S7 pairwise pathfinding (``GET /api/v1/paths/between``)."""

    @abstractmethod
    async def confirm_connection(
        self,
        source_entity_id: UUID,
        target_entity_id: UUID,
        max_hops: int,
        relation_type: str | None = None,
    ) -> bool:
        """Return True iff a path exists between source and target within ``max_hops``.

        When ``relation_type`` is set, additionally require at least one returned
        path to contain an edge of that relation type. Fail-closed: any error /
        timeout / 503 returns ``False`` (no fire).
        """
