"""CypherNeighborhoodUseCase — egocentric neighborhood via AGE Cypher (PRD-0018 §6.3).

Uses a hybrid approach:
  1. AGE Cypher for multi-hop entity discovery (up to max_hops=3).
  2. SQL for authoritative entity + relation data (canonical_entities, relations).
  3. SQL for temporal events (temporal_events + entity_event_exposures) when requested.

This preserves the architectural invariant that the relational tables are the
source of truth. AGE is used for graph traversal only.

Security: entity_id is validated as a strict UUID (hex+hyphen only) via _UUID_RE before
being embedded as a string literal in the Cypher pattern (same approach as PathDiscovery).
``max_hops`` is a Pydantic-validated int [1, 3] embedded as a numeric literal.
``limit`` is a Pydantic-validated int [1, 200] embedded as a numeric literal.

BP-450 (2026-05-11): AGE 1.5 does not support ``ALL(rel IN relationships(path) WHERE ...)``
on variable-length relationship lists — the predicate raises:
  "syntax error at or near '('"
in asyncpg's PREPARE phase.  Additionally, asyncpg's extended-query (prepared-statement)
protocol fails for AGE Cypher queries that pass a ``$1`` params argument when the Cypher
body also contains Cypher-level ``$var`` references (asyncpg confuses them for additional
PostgreSQL positional parameters).

Fix: embed entity_id as a UUID string literal (UUID-validated — only [0-9a-fA-F-] chars),
remove the $1 params argument, and drop the ``ALL(...)`` Cypher predicate.  Confidence
filtering is performed post-query by ``relation_repo.list_for_entity(min_confidence=...)``
in Step 2 (the relational table is the authoritative source of truth for edge weights).
"""

from __future__ import annotations

import re
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

# UUID validation pattern — guards entity_id before it is embedded in Cypher.
# UUIDs contain only [0-9a-fA-F-] so no SQL/Cypher injection is possible.
# Mirrors the same pattern in PathDiscovery (BP-SA5-003).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.relation import RelationRepository
    from knowledge_graph.infrastructure.intelligence_db.repositories.temporal_event_repository import (
        TemporalEventRepository,
    )

# Statement timeout — 20 s to allow depth=3 AGE traversal on moderately-dense
# graphs (raised from 5 s; depth=3 traversal can visit hundreds of nodes and
# needs more wall time than a simple 2-hop neighbourhood query).
_STATEMENT_TIMEOUT_MS = "20000"

# ── Result dataclass (internal) ───────────────────────────────────────────────


@dataclass
class CypherNeighborhoodResult:
    """Return type of CypherNeighborhoodUseCase.execute()."""

    center_row: dict[str, Any]
    relation_rows: list[dict[str, Any]] = field(default_factory=list)
    neighbor_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    temporal_event_rows: list[dict[str, Any]] = field(default_factory=list)


# ── AGE SQL ───────────────────────────────────────────────────────────────────


def _build_neighborhood_sql(entity_id_str: str, max_hops: int, limit: int) -> str:
    """Build AGE Cypher SQL for neighborhood discovery with embedded UUID literal.

    ``entity_id_str`` is a UUID string pre-validated by ``_UUID_RE`` (only
    [0-9a-fA-F-] characters) — safe to embed directly as a Cypher string literal.
    ``max_hops`` is a Pydantic-validated int [1, 3] — embedded as a numeric literal.
    ``limit`` is a Pydantic-validated int [1, 200] — embedded as a numeric literal.

    WHY no $params argument: asyncpg's extended-query (prepared-statement) protocol
    fails for AGE Cypher queries that mix a PostgreSQL ``$1`` positional parameter
    with Cypher-level ``$var`` references — Postgres confuses them during PREPARE.
    Embedding the UUID as a string literal (after UUID validation) avoids this
    entirely.  Confidence filtering is done by SQL in Step 2 (relation_repo).
    See BP-450 (2026-05-11).

    WHY no ALL(rel IN relationships(path) WHERE ...) predicate: AGE 1.5 does not
    support this construct on variable-length relationship lists and raises
    "syntax error at or near '('" at PREPARE time.  Confidence is authoritative
    in the relational ``relations`` table — filtering is applied there in Step 2.
    """
    # BP-SA5-001 (2026-05-10): use lowercase ``entity`` label to match the
    # canonical label written by AgeSyncWorker and queried by PathDiscovery.
    return (
        "SELECT neighbor_id::text"  # noqa: S608 — entity_id UUID-validated; max_hops/limit validated ints
        " FROM ag_catalog.cypher('worldview_graph', $$"
        f" MATCH (center:entity {{entity_id: '{entity_id_str}'}})-[r*1..{max_hops}]-(neighbor:entity)"
        " RETURN DISTINCT neighbor.entity_id AS neighbor_id"
        f" LIMIT {limit}"
        " $$) AS (neighbor_id agtype)"
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
        CypherTimeoutError:        AGE query exceeded 20 s statement_timeout.

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

        # Validate entity_id as UUID before embedding in Cypher string literal.
        # WHY: UUID contains only [0-9a-fA-F-] — no SQL/Cypher metacharacters.
        # Mirrors the approach used in PathDiscovery (BP-SA5-003, BP-450).
        eid_str = str(entity_id)
        if not _UUID_RE.match(eid_str):
            raise ValueError(f"entity_id is not a valid UUID: {eid_str!r}")

        # AGE session setup
        await _setup_age_session(session)
        await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))

        # ── Step 1: AGE Cypher — discover neighbor entity_ids ─────────────────
        # BP-450 (2026-05-11): embed entity_id as literal; no $params argument.
        # Confidence filtering is deferred to SQL in Step 2 (source of truth).
        sql = _build_neighborhood_sql(eid_str, max_hops, limit)

        try:
            result = await session.execute(text(sql))
            rows = result.fetchall()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
                raise CypherTimeoutError("AGE Cypher query exceeded 20 s statement_timeout") from exc
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

        # ── Step 3b: SQL — resolve direct-relation endpoints AGE missed ───────
        # WHY: AGE's DISTINCT ... LIMIT fills arbitrarily — on dense graphs the
        # discovered set can omit some of the center's own 1-hop SQL neighbours
        # (and stale AGE edges can spend the LIMIT budget on ghosts). Direct
        # relation endpoints are renderable by definition, so resolve them too;
        # without this, lateral edges between two direct neighbours are missed
        # by Step 2b because one endpoint never made it into the node set.
        for rel in relation_rows:
            for key in ("subject_entity_id", "object_entity_id"):
                eid = rel.get(key)
                if not isinstance(eid, UUID) or eid == entity_id or str(eid) in neighbor_rows:
                    continue
                endpoint_row = await entity_repo.get(eid)
                if endpoint_row is not None:
                    neighbor_rows[str(eid)] = endpoint_row

        # ── Step 2b: SQL — lateral / second-hop edges among the node set ──────
        # PLAN-0099 W3 (graph depth fix): Step 2 only returns the CENTER's
        # direct relations, so every depth-2/3 node discovered in Step 1
        # arrived edge-less — the API consumer (S9 orphan filter) then deleted
        # it, making depth=2 visually identical to depth=1 (live AAPL had 23
        # real lateral relations among its direct neighbours — none returned).
        # Fetch the edges whose BOTH endpoints are inside {center + resolved
        # node set} and merge them (dedup by relation_id — the center's own
        # edges qualify for the lateral query too).
        # WHY only resolved neighbours: edges to AGE-only ghosts (stale AGE
        # sync) would be re-orphaned by the consumer; resolving first keeps
        # the payload self-consistent (every edge endpoint has an entity).
        if max_hops > 1 and neighbor_rows:
            lateral_rows = await relation_repo.list_among_entities(
                [entity_id, *(_UUID(k) for k in neighbor_rows)],
                min_confidence=min_confidence,
                limit=limit,
            )
            seen_relation_ids = {r["relation_id"] for r in relation_rows}
            for lateral_row in lateral_rows:
                if lateral_row["relation_id"] not in seen_relation_ids:
                    relation_rows.append(lateral_row)
                    seen_relation_ids.add(lateral_row["relation_id"])

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
