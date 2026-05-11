"""CypherNeighborhoodUseCase — egocentric neighborhood via AGE Cypher (PRD-0018 §6.3).

Uses a hybrid approach:
  1. AGE Cypher for multi-hop entity discovery (up to max_hops=3).
  2. SQL for authoritative entity + relation data (canonical_entities, relations).
  3. SQL for temporal events (temporal_events + entity_event_exposures) when requested.

This preserves the architectural invariant that the relational tables are the
source of truth. AGE is used for graph traversal only.

Security: entity_id passed as parameterized ``$center_id`` — never f-strung into Cypher.
``max_hops`` is a Pydantic-validated int [1, 3] embedded as a numeric literal.
``limit`` is a Pydantic-validated int [1, 200] embedded as a numeric literal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.use_cases.cypher_path import (
    CypherDisabledError,
    CypherEntityNotFoundError,
    CypherTimeoutError,
    _setup_age_session,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
    from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
        TemporalEventRepository,
    )

# Statement timeout — same 5 s limit as the path endpoint (PRD §6.3)
_STATEMENT_TIMEOUT_MS = "5000"

# ── Result dataclass (internal) ───────────────────────────────────────────────


@dataclass
class CypherNeighborhoodResult:
    """Return type of CypherNeighborhoodUseCase.execute()."""

    center_row: dict[str, Any]
    relation_rows: list[dict[str, Any]] = field(default_factory=list)
    neighbor_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    temporal_event_rows: list[dict[str, Any]] = field(default_factory=list)


# ── AGE SQL ───────────────────────────────────────────────────────────────────


def _build_neighborhood_sql(max_hops: int, limit: int) -> str:
    """Build parameterized AGE Cypher SQL for neighborhood discovery.

    ``max_hops`` is a Pydantic-validated int [1, 3] — embedded as a numeric literal.
    ``limit`` is a Pydantic-validated int [1, 200] — embedded as a numeric literal.
    The center entity_id is passed as ``$center_id`` (parameterized).
    """
    # BP-SA5-001 (2026-05-10): use lowercase ``entity`` label to match the
    # canonical label written by AgeSyncWorker and queried by PathDiscovery.
    # BP-450 (2026-05-11): AGE 1.5 does not support ALL(rel IN r WHERE ...) on
    # variable-length relationship lists — use ``relationships(path)`` on a named
    # path instead, mirroring the working syntax in cypher_path.py.
    return (
        "SELECT neighbor_id::text"  # noqa: S608 — max_hops/limit validated ints; center_id via $center_id param
        " FROM ag_catalog.cypher('worldview_graph', $$"
        f" MATCH path = (center:entity {{entity_id: $center_id}})-[r*1..{max_hops}]-(neighbor:entity)"
        " WHERE ALL(rel IN relationships(path) WHERE rel.confidence >= $min_conf)"
        " RETURN DISTINCT neighbor.entity_id AS neighbor_id"
        f" LIMIT {limit}"
        " $$, :params) AS (neighbor_id agtype)"
    )


# ── Use case ──────────────────────────────────────────────────────────────────


class CypherNeighborhoodUseCase:
    """Egocentric neighborhood using Apache AGE Cypher multi-hop traversal.

    Returns :class:`CypherNeighborhoodResult` with:
    - ``center_row``: full entity dict from SQL.
    - ``relation_rows``: direct relations of the center entity from SQL.
    - ``neighbor_rows``: dict of entity_id_str → entity dict for discovered neighbors.
    - ``temporal_event_rows``: events exposed to the center entity (if requested).

    Raises
    ------
        CypherDisabledError:       KNOWLEDGE_GRAPH_CYPHER_ENABLED=false.
        CypherEntityNotFoundError: entity not in canonical_entities.
        CypherTimeoutError:        AGE query exceeded 5 s statement_timeout.

    """

    async def execute(
        self,
        session: AsyncSession,
        entity_repo: CanonicalEntityRepository,
        relation_repo: RelationRepository,
        temporal_event_repo: TemporalEventRepository | None,
        *,
        cypher_enabled: bool,
        entity_id: UUID,
        max_hops: int = 2,
        min_confidence: float = 0.4,
        include_temporal_events: bool = True,
        limit: int = 50,
    ) -> CypherNeighborhoodResult:
        if not cypher_enabled:
            raise CypherDisabledError("Cypher endpoints are disabled (KNOWLEDGE_GRAPH_CYPHER_ENABLED=false)")

        # Validate entity exists (SQL check before AGE session setup)
        center_row = await entity_repo.get(entity_id)
        if center_row is None:
            raise CypherEntityNotFoundError(entity_id)

        # AGE session setup
        await _setup_age_session(session)
        await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))

        # ── Step 1: AGE Cypher — discover neighbor entity_ids ─────────────────
        import json

        sql = _build_neighborhood_sql(max_hops, limit)
        params_json = json.dumps(
            {
                "center_id": str(entity_id),
                "min_conf": min_confidence,
            },
        )

        try:
            result = await session.execute(text(sql), {"params": params_json})
            rows = result.fetchall()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
                raise CypherTimeoutError("AGE Cypher query exceeded 5 s statement_timeout") from exc
            raise

        # Parse neighbor entity_ids from agtype text
        neighbor_ids: list[str] = []
        for row in rows:
            raw = row[0] if row else None
            if raw is None:
                continue
            # neighbor_id is a single agtype string value (not a list)
            text_val: str = raw.decode() if isinstance(raw, bytes | bytearray) else str(raw)
            if "::" in text_val:
                text_val = text_val[: text_val.rfind("::")]
            text_val = text_val.strip().strip('"')
            if text_val:
                neighbor_ids.append(text_val)

        # ── Step 2: SQL — full relation data for center entity ────────────────
        relation_rows = await relation_repo.list_for_entity(
            entity_id,
            min_confidence=min_confidence,
            limit=limit,
        )

        # ── Step 3: SQL — entity details for discovered neighbors ─────────────
        from uuid import UUID as _UUID

        neighbor_rows: dict[str, dict[str, Any]] = {}
        for nid in neighbor_ids:
            try:
                uid = _UUID(nid)
            except ValueError:
                continue
            if str(uid) == str(entity_id):
                continue  # skip center entity
            row_data = await entity_repo.get(uid)
            if row_data is not None:
                neighbor_rows[str(uid)] = row_data

        # ── Step 4 (optional): SQL — temporal events for center entity ────────
        temporal_event_rows: list[dict[str, Any]] = []
        if include_temporal_events and temporal_event_repo is not None:
            events, _ = await temporal_event_repo.list_active(
                entity_id=entity_id,
                active_only=True,
                limit=20,
                offset=0,
            )
            temporal_event_rows = list(events)

        return CypherNeighborhoodResult(
            center_row=dict(center_row),
            relation_rows=relation_rows,
            neighbor_rows=neighbor_rows,
            temporal_event_rows=temporal_event_rows,
        )
