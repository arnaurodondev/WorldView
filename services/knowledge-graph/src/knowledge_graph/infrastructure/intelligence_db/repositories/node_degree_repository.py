"""NodeDegreeRepository — materialise + read per-vertex degree from AGE (T-3-02).

Concrete asyncpg implementation of ``NodeDegreeRepositoryPort``.  Recomputes the
undirected degree of every graph vertex (and a *meaningful* degree that excludes
``MEMBERSHIP_RELATIONS`` edge labels) and upserts the result into ``node_degree``
+ the single-row ``graph_stats`` table.

DEGREE SOURCE — FAST raw-table SQL aggregation (NOT AGE Cypher):
  The redesign audit (2026-06-12 Thread 2) prescribes a plain SQL aggregation
  over ``worldview_graph._ag_label_edge`` measured at ~18 ms.  The earlier
  Cypher form ``MATCH (a:entity)-[r]-(b:entity)`` was the SAME slow ``-[r]-``
  full-graph traversal class and TIMED OUT at 50 s on the live graph (W3 live QA)
  — so degrees are now computed entirely from the relational AGE storage:

    * ``worldview_graph._ag_label_edge(id, start_id, end_id, properties)`` holds
      every edge as graphids (~9,979 rows).  Undirected degree of a vertex =
      count of edge rows where it is ``start_id`` OR ``end_id`` (i.e. count its
      graphid across ``start_id UNION ALL end_id``).
    * ``worldview_graph.entity(id /*graphid*/, properties /*agtype*/)`` maps
      graphid → ``entity_id`` UUID, extracted via
      ``agtype_access_operator(properties, '"entity_id"')`` (quotes trimmed).
    * Each relation label is its own child table inheriting from
      ``_ag_label_edge``; the four membership labels in ``MEMBERSHIP_RELATIONS``
      are excluded from the *meaningful* degree by edge ``id`` (exact, unaffected
      by parallel edges).

  This is pure SQL — it needs neither ``LOAD 'age'`` nor any Cypher, and the
  full per-entity aggregation runs in well under 1 s on the live graph.

R24 note: this repo issues no DDL — it only INSERTs/UPSERTs into tables owned by
the intelligence-migrations service (migration 0052).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.application.ports.node_degree_repository import (
    GraphStats,
    NodeDegreeRepositoryPort,
)
from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)  # type: ignore[no-any-return]

# AGE graph + schema name (matches AgeSyncWorker / path_discovery).
_GRAPH_SCHEMA = "worldview_graph"

# Valid AGE edge-label pattern.  Membership-label names are compile-time
# constants (from MEMBERSHIP_RELATIONS) but we still assert they are plain
# uppercase identifiers before embedding the (double-quoted) child-table name in
# SQL — defence-in-depth against any future label containing a metacharacter.
_AGE_LABEL_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _membership_id_union_sql() -> str:
    """Build the ``UNION ALL`` of membership child-table edge ids.

    Each membership label has its own child table under ``_ag_label_edge`` whose
    name is the (uppercase) label, double-quoted.  Returns SQL selecting the
    ``id`` graphids of every membership edge, or an empty-set sentinel when no
    membership labels are configured.
    """
    parts: list[str] = []
    for label in sorted(MEMBERSHIP_RELATIONS):
        # SECURITY: assert the label is a plain uppercase identifier before
        # embedding it as a quoted child-table name (it never reaches data).
        if not _AGE_LABEL_RE.match(label):
            msg = f"Invalid AGE membership label (refusing to embed in SQL): {label!r}"
            raise ValueError(msg)
        parts.append(f'SELECT id FROM {_GRAPH_SCHEMA}."{label}"')
    if not parts:
        # No membership labels → meaningful == full degree (empty exclusion set).
        return "SELECT NULL::ag_catalog.graphid AS id WHERE false"
    return " UNION ALL ".join(parts)


def _degree_aggregation_sql() -> str:
    """SQL returning (entity_id, degree, degree_meaningful) for every vertex.

    Undirected degree = count of edge endpoints (``start_id`` + ``end_id``) that
    resolve to the vertex.  Meaningful degree = same but only over edges whose
    ``id`` is NOT a membership-edge id.  Both computed in one pass via a tagged
    endpoint enumeration joined to the vertex graphid→entity_id map.
    """
    membership_ids = _membership_id_union_sql()
    # ``is_meaningful`` flags each endpoint row by whether its edge is non-membership.
    # The two SUMs over that flag give degree (all) and degree_meaningful.
    return f"""
WITH membership_ids AS (
    {membership_ids}
),
endpoints AS (
    SELECT e.start_id AS gid, (e.id NOT IN (SELECT id FROM membership_ids)) AS is_meaningful
    FROM {_GRAPH_SCHEMA}._ag_label_edge e
    UNION ALL
    SELECT e.end_id AS gid, (e.id NOT IN (SELECT id FROM membership_ids)) AS is_meaningful
    FROM {_GRAPH_SCHEMA}._ag_label_edge e
),
vertices AS (
    SELECT
        v.id AS gid,
        trim(both '"' from
            ag_catalog.agtype_access_operator(v.properties, '"entity_id"'::ag_catalog.agtype)::text
        ) AS entity_id
    FROM {_GRAPH_SCHEMA}.entity v
)
SELECT
    vx.entity_id,
    count(*)::int AS degree,
    count(*) FILTER (WHERE ep.is_meaningful)::int AS degree_meaningful
FROM endpoints ep
JOIN vertices vx ON vx.gid = ep.gid
GROUP BY vx.entity_id
"""


# Graph-wide stat counts (total edges, total meaningful edges).  ``max_degree``
# is derived in Python from the per-vertex aggregation (no extra scan).
def _stats_count_sql() -> str:
    membership_ids = _membership_id_union_sql()
    return f"""
SELECT
    (SELECT count(*) FROM {_GRAPH_SCHEMA}._ag_label_edge)::int AS total_edges,
    (SELECT count(*) FROM {_GRAPH_SCHEMA}._ag_label_edge e
        WHERE e.id NOT IN (SELECT id FROM ({membership_ids}) m))::int AS total_meaningful_edges
"""


# Strict UUID guard for entity_ids parsed out of the AGE vertex map (some seed /
# test vertices carry non-UUID ids like "e-test1" — skip those for the FK-bound
# node_degree table).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class NodeDegreeRepository(NodeDegreeRepositoryPort):
    """asyncpg-backed degree materialisation + read (PLAN-0112 T-3-02)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def refresh_from_age(self) -> GraphStats:
        """Recompute degree + meaningful-degree via fast SQL and upsert (FR-5)."""
        # The degree SQL compares ``graphid`` values (``e.id NOT IN (...)``); the
        # ``graphid = graphid`` operator lives in ``ag_catalog`` and the planner
        # only resolves it when ``ag_catalog`` is on the search_path.  Set it for
        # THIS session (the AGE storage tables also live under worldview_graph).
        # SET LOCAL scopes it to the surrounding transaction — it does not leak.
        await self._session.execute(text("SET LOCAL search_path = ag_catalog, worldview_graph, public"))

        # 1. Per-vertex degree aggregation (one fast pass over the raw edge table).
        rows = (await self._session.execute(text(_degree_aggregation_sql()))).fetchall()

        degree: dict[str, int] = {}
        meaningful: dict[str, int] = {}
        max_degree = 0
        for entity_id, deg, mdeg in rows:
            if not entity_id:
                continue
            degree[str(entity_id)] = int(deg)
            meaningful[str(entity_id)] = int(mdeg)
            if int(deg) > max_degree:
                max_degree = int(deg)

        # 2. Graph-wide edge counts (the configuration-model 2m normaliser).
        stat_row = (await self._session.execute(text(_stats_count_sql()))).fetchone()
        total_edges = int(stat_row[0]) if stat_row and stat_row[0] is not None else 0
        total_meaningful_edges = int(stat_row[1]) if stat_row and stat_row[1] is not None else 0

        refreshed_at = utc_now()  # type: ignore[no-any-return]

        await self._upsert_node_degrees(degree, meaningful, refreshed_at)
        await self._upsert_graph_stats(
            total_edges=total_edges,
            total_meaningful_edges=total_meaningful_edges,
            max_degree=max_degree,
            refreshed_at=refreshed_at,
        )

        logger.info(  # type: ignore[no-any-return]
            "node_degree_refreshed",
            vertices=len(degree),
            total_edges=total_edges,
            total_meaningful_edges=total_meaningful_edges,
            max_degree=max_degree,
        )
        return GraphStats(
            total_edges=total_edges,
            total_meaningful_edges=total_meaningful_edges,
            max_degree=max_degree,
            refreshed_at=refreshed_at,
        )

    async def _upsert_node_degrees(
        self,
        degree: dict[str, int],
        meaningful: dict[str, int],
        refreshed_at: object,
    ) -> None:
        """Bulk UPSERT every vertex's degree row (ON CONFLICT updates in place).

        Only UUID-shaped vertex ids that exist in ``canonical_entities`` survive
        (the FK rejects orphans; the JOIN drops them up-front).  Non-UUID seed /
        test vertex ids (e.g. ``e-test1``) are skipped here.
        """
        items = [(eid, deg) for eid, deg in degree.items() if _UUID_RE.match(eid)]
        if not items:
            return
        # Chunk to keep the multi-row VALUES statement within bind-param limits.
        chunk = 500
        for start in range(0, len(items), chunk):
            batch = items[start : start + chunk]
            parts: list[str] = []
            params: dict[str, object] = {"refreshed_at": refreshed_at}
            for i, (eid, deg) in enumerate(batch):
                # asyncpg sends untyped binds as text in a VALUES context, which
                # collides with the INTEGER columns ("expression is of type text").
                # Cast the numeric binds explicitly, like the UUID/timestamptz ones.
                parts.append(
                    f"(CAST(:eid_{i} AS UUID), CAST(:deg_{i} AS INTEGER), "
                    f"CAST(:mdeg_{i} AS INTEGER), CAST(:refreshed_at AS TIMESTAMPTZ))"
                )
                params[f"eid_{i}"] = eid
                params[f"deg_{i}"] = deg
                params[f"mdeg_{i}"] = meaningful.get(eid, 0)
            sql = (
                "INSERT INTO node_degree (entity_id, degree, degree_meaningful, refreshed_at) "
                "SELECT v.entity_id, v.degree, v.degree_meaningful, v.refreshed_at "
                f"FROM (VALUES {', '.join(parts)}) "
                "AS v(entity_id, degree, degree_meaningful, refreshed_at) "
                # FK guard: only keep vertices that still exist as canonical entities
                "JOIN canonical_entities ce ON ce.entity_id = v.entity_id "
                "ON CONFLICT (entity_id) DO UPDATE SET "
                "  degree = EXCLUDED.degree, "
                "  degree_meaningful = EXCLUDED.degree_meaningful, "
                "  refreshed_at = EXCLUDED.refreshed_at"
            )
            await self._session.execute(text(sql), params)

    async def _upsert_graph_stats(
        self,
        *,
        total_edges: int,
        total_meaningful_edges: int,
        max_degree: int,
        refreshed_at: object,
    ) -> None:
        """UPSERT the single-row (id=1) graph_stats normaliser store."""
        await self._session.execute(
            text(
                "INSERT INTO graph_stats (id, total_edges, total_meaningful_edges, max_degree, refreshed_at) "
                "VALUES (1, CAST(:te AS INTEGER), CAST(:tme AS INTEGER), CAST(:md AS INTEGER), "
                "CAST(:refreshed_at AS TIMESTAMPTZ)) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  total_edges = EXCLUDED.total_edges, "
                "  total_meaningful_edges = EXCLUDED.total_meaningful_edges, "
                "  max_degree = EXCLUDED.max_degree, "
                "  refreshed_at = EXCLUDED.refreshed_at"
            ),
            {
                "te": total_edges,
                "tme": total_meaningful_edges,
                "md": max_degree,
                "refreshed_at": refreshed_at,
            },
        )

    async def get_degree_map(self) -> dict[UUID, tuple[int, int]]:
        """Return ``{entity_id: (degree, degree_meaningful)}`` for every vertex."""
        result = await self._session.execute(text("SELECT entity_id, degree, degree_meaningful FROM node_degree"))
        return {UUID(str(row[0])): (int(row[1]), int(row[2])) for row in result.fetchall()}

    async def get_graph_stats(self) -> GraphStats | None:
        """Return the single ``graph_stats`` row, or ``None`` if never refreshed."""
        result = await self._session.execute(
            text("SELECT total_edges, total_meaningful_edges, max_degree, refreshed_at FROM graph_stats WHERE id = 1")
        )
        row = result.fetchone()
        if row is None:
            return None
        return GraphStats(
            total_edges=int(row[0]) if row[0] is not None else 0,
            total_meaningful_edges=int(row[1]) if row[1] is not None else 0,
            max_degree=int(row[2]) if row[2] is not None else 0,
            refreshed_at=row[3],
        )
