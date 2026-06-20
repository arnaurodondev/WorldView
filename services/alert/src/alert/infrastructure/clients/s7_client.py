"""HTTP client for S7 Knowledge-Graph pairwise pathfinding (PLAN-0113 T-3-01 — NEW).

This is a SEPARATE artifact from ``s7_entity_resolver.py`` (which resolves
``(canonical_name, ticker)`` via ``POST /api/v1/entities/batch``). The only S7
read this client performs is the pairwise *path* probe used by the
KG_CONNECTION rule type:

    GET /api/v1/paths/between?source=<a>&target=<b>&max_hops=<1..3>

returning a ``PathsBetweenResponse`` whose ``connected`` boolean tells us whether
A and B are linked within ``max_hops``. When the rule pins a ``relation_type`` we
additionally require a matching edge among ``paths[].path_edges[].relation_type``.

R9: cross-service access via REST only. R25: implements the ``IS7GraphClient`` ABC.
PRD-0025: the call carries ``X-Internal-JWT`` (S7 returns 401 without it).

**Fail-closed** (the key reliability invariant for W3): S7 may return ``503`` when
the AGE traversal exceeds its statement timeout, and the upstream may be down or
slow. In every such case we return ``False`` — an *unproven* connection must never
fire an alert. A genuinely-new edge that we miss because S7 was momentarily down
is re-evaluated on the next ``graph.state.changed.v1`` event for the same pair, so
fail-closed costs us at most a small delay, never a phantom alert. BP-235: an
explicit ``httpx.Timeout`` is set AND the whole call is wrapped in
``asyncio.wait_for`` so a wedged S7 cannot hang the consumer.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from httpx import AsyncClient, HTTPStatusError, RequestError, Timeout

from alert.application.ports.graph_clients import IS7GraphClient

if TYPE_CHECKING:
    from alert.config import Settings

logger = structlog.get_logger(__name__)

# BP-235: a wedged/slow S7 must not hang the consumer's KG branch. The inner
# httpx timeout fires first; the outer asyncio.wait_for is the belt-and-braces
# guard around the whole coroutine (DNS, connect, read).
_S7_PATHS_TIMEOUT_S = 10.0
# The S7 endpoint constrains max_hops to 1..3 (knowledge-graph/api/paths.py
# Query(ge=1, le=3)). Sending out-of-range would 422; clamp defensively so a
# stored condition can never break the probe.
_MIN_HOPS = 1
_MAX_HOPS = 3


class S7GraphClient(IS7GraphClient):
    """Async HTTP client for the S7 pairwise-path endpoint (fail-closed)."""

    def __init__(self, settings: Settings, client: AsyncClient | None = None) -> None:
        # Reuse the SAME base URL + JWT config the entity resolver already uses —
        # no new S7 base-URL setting is needed (PLAN-0113 Cross-Cutting/Config).
        self._base_url = settings.s7_knowledge_graph_base_url.rstrip("/")
        self._jwt = settings.s7_internal_jwt
        self._client = client or AsyncClient(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        """Internal-JWT header (PRD-0025); empty when no token is configured."""
        return {"X-Internal-JWT": self._jwt} if self._jwt else {}

    async def close(self) -> None:
        """Close the underlying HTTP client. Safe to call once at shutdown."""
        await self._client.aclose()

    async def confirm_connection(
        self,
        source_entity_id: UUID,
        target_entity_id: UUID,
        max_hops: int,
        relation_type: str | None = None,
    ) -> bool:
        """Probe S7 for a path between source and target; fail-closed on any error.

        Returns ``True`` only when S7 *positively* reports ``connected=true``
        (and, if ``relation_type`` is pinned, a matching edge is present). Any
        503 / transport error / timeout / malformed body → ``False``.
        """
        # A self-loop is never a "connection" worth alerting on; the rule factory
        # already forbids node_a == node_b, but guard here too (defensive — a
        # malformed event pair must not produce a 400 round-trip).
        if source_entity_id == target_entity_id:
            return False

        hops = max(_MIN_HOPS, min(_MAX_HOPS, int(max_hops)))
        url = f"{self._base_url}/api/v1/paths/between"
        params: dict[str, str | int] = {
            "source": str(source_entity_id),
            "target": str(target_entity_id),
            "max_hops": hops,
            # We only need the existence flag (+ edges when a relation_type is
            # pinned); a small limit keeps the AGE traversal + payload cheap.
            "limit": 5,
        }
        try:
            resp = await asyncio.wait_for(
                self._client.get(
                    url,
                    params=params,
                    headers=self._headers(),
                    timeout=Timeout(_S7_PATHS_TIMEOUT_S),
                ),
                timeout=_S7_PATHS_TIMEOUT_S + 1.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except (RequestError, HTTPStatusError, TimeoutError) as exc:
            # Fail-closed: 503 (AGE timeout), 5xx, network error, or our own
            # asyncio timeout all mean "could not prove a connection" → no fire.
            logger.warning(
                "s7_graph_client_confirm_failed",
                url=url,
                source=str(source_entity_id),
                target=str(target_entity_id),
                error=str(exc),
            )
            return False

        if not isinstance(data, dict) or not bool(data.get("connected")):
            return False

        if relation_type is None:
            return True

        # Relation-type filter: require at least one returned path to contain an
        # edge whose relation_type matches (case-insensitive — S7 stores
        # canonical_types in varied case across pipelines).
        wanted = relation_type.strip().lower()
        for path in data.get("paths", []) or []:
            for edge in path.get("path_edges", []) or []:
                if str(edge.get("relation_type", "")).strip().lower() == wanted:
                    return True
        return False
