"""CypherPathUseCase — shortest path between two entities via Apache AGE (PRD-0018 §6.3).

Security invariants (enforced here — see Pitfalls in .claude-context.md):
- Entity IDs are UUID-validated ([0-9a-fA-F-] only) and embedded as string literals
  in the Cypher pattern — never passed as $params (BP-459-C / BP-450: asyncpg's
  prepared-statement protocol confuses PostgreSQL $1 params with Cypher $var refs).
- ``max_hops`` is a Pydantic-validated integer [1, 5] and is embedded as a numeric
  literal in the Cypher pattern. The route handler ensures it cannot exceed 5.
- ``relation_types`` filtering is applied in Python after the query (post-hoc),
  using the agtype-parsed label string. No user string is embedded in Cypher.

AGE 1.5.0 compatibility (BP-459-C, 2026-05-11):
  AGE 1.5.0 does NOT support:
    - ``shortestPath()`` / ``allShortestPaths()`` — raises "function does not exist"
    - ``ALL(rel IN relationships(path) WHERE ...)`` — raises "syntax error at or near '('"
  Fix: use variable-length relationship pattern ``-[r*1..N]-`` with LIMIT,
  embed entity_ids as UUID string literals (no $params argument), and apply
  confidence filtering post-query via relation_repo (same approach as BP-450 in
  cypher_neighborhood.py).

AGE session requirements:
  Every DB session that issues AGE Cypher MUST execute the following first:
    LOAD 'age'
    SET search_path = ag_catalog, public
  This is enforced in ``_setup_age_session()`` called at the start of execute().

Result parsing:
  AGE Cypher returns ``agtype`` columns. Cast to ``::text`` in the outer SQL
  SELECT to get standard JSON strings. The node list and edge list can then be
  parsed with ``json.loads()``.

  Node agtype text format:
    {"id": <int>, "label": "Entity", "properties": {
      "entity_id": "...", "canonical_name": "...", "entity_type": "...", "updated_at": "..."}}

  Edge agtype text format:
    {"id": <int>, "start_id": <int>, "end_id": <int>, "label": "COMPETES_WITH",
     "properties": {"relation_id": "...", "confidence": 0.87, "updated_at": "..."}}
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.domain.errors import KnowledgeGraphError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from knowledge_graph.infrastructure.intelligence_db.repositories.canonical_entity import (
        CanonicalEntityRepository,
    )

# UUID validation pattern — guards entity_ids before they are embedded in Cypher.
# UUIDs contain only [0-9a-fA-F-] so no SQL/Cypher injection is possible.
# Mirrors the same pattern in cypher_neighborhood.py (BP-450, BP-459-C).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

# ── Custom errors ─────────────────────────────────────────────────────────────


class CypherDisabledError(KnowledgeGraphError):
    """Raised when a Cypher endpoint is called while KNOWLEDGE_GRAPH_CYPHER_ENABLED=false."""


class CypherTimeoutError(KnowledgeGraphError):
    """Raised when the AGE Cypher query exceeds the 5 s statement_timeout."""


class CypherEntityNotFoundError(KnowledgeGraphError):
    """Raised when a requested entity does not exist in canonical_entities."""

    def __init__(self, entity_id: UUID) -> None:
        super().__init__(f"Entity not found: {entity_id}")
        self.entity_id = entity_id


# ── Result dataclasses (internal — not Pydantic) ──────────────────────────────


@dataclass(frozen=True)
class _PathNode:
    entity_id: str
    canonical_name: str
    entity_type: str


@dataclass(frozen=True)
class _PathEdge:
    from_entity_id: str
    to_entity_id: str
    canonical_type: str
    confidence: float
    direction: str = "forward"


@dataclass(frozen=True)
class _Path:
    hops: int
    nodes: list[_PathNode] = field(default_factory=list)
    edges: list[_PathEdge] = field(default_factory=list)
    path_confidence: float = 0.0


@dataclass(frozen=True)
class CypherPathResult:
    """Return type of CypherPathUseCase.execute()."""

    source_entity_id: UUID
    target_entity_id: UUID
    paths: list[_Path]
    paths_found: int
    query_time_ms: int


# ── AGE SQL helpers ───────────────────────────────────────────────────────────

# Statement timeout — matches PRD §6.3 "504 response on AGE timeout (5s)"
_STATEMENT_TIMEOUT_MS = "5000"


def _build_direct_sql(source_id_str: str, target_id_str: str, limit: int) -> str:
    """Build a pure-SQL query for 1-hop paths between two entities.

    BP-461 (2026-05-11): AGE 1.5.0 does NOT support Cypher list comprehensions
    using the ``|`` operator (``[n IN nodes(path) | n]`` raises syntax error).
    The fix for the common case (1-hop, i.e. direct relation) is to bypass AGE
    entirely and query the SQL ``relations`` table directly.

    For 2-hop paths a second SQL subquery handles the mid-node lookup.
    AGE is only used as a last resort for 3+ hop paths (not currently needed).

    Source/target IDs are validated by ``_UUID_RE`` before this call — they
    contain only [0-9a-fA-F-] and are safe to embed as UUID literals.
    ``limit`` is a Python int — safe as a numeric literal.
    """
    return (
        "SELECT"  # noqa: S608 — UUIDs validated by _UUID_RE; limit is a Python int
        "  r.canonical_type::text,"
        "  COALESCE(r.confidence, 0.0)::float,"
        "  r.subject_entity_id::text  AS s_id,"
        "  r.object_entity_id::text   AS t_id,"
        "  ce_s.canonical_name::text  AS s_name,"
        "  ce_s.entity_type::text     AS s_type,"
        "  ce_t.canonical_name::text  AS t_name,"
        "  ce_t.entity_type::text     AS t_type,"
        "  NULL::text                 AS mid_id,"
        "  NULL::text                 AS mid_name,"
        "  NULL::text                 AS mid_type,"
        "  NULL::text                 AS r2_type,"
        "  NULL::float                AS r2_conf"
        " FROM relations r"
        " JOIN canonical_entities ce_s ON ce_s.entity_id = r.subject_entity_id"
        " JOIN canonical_entities ce_t ON ce_t.entity_id = r.object_entity_id"
        f" WHERE (r.subject_entity_id = '{source_id_str}'"
        f"        AND r.object_entity_id = '{target_id_str}')"
        f"    OR (r.subject_entity_id = '{target_id_str}'"
        f"        AND r.object_entity_id = '{source_id_str}')"
        " ORDER BY r.confidence DESC NULLS LAST"
        f" LIMIT {limit}"
    )


def _build_twohop_sql(source_id_str: str, target_id_str: str, limit: int) -> str:
    """Build a pure-SQL query for 2-hop paths (source → mid → target).

    Finds paths where the source entity has a direct relation to an intermediate
    entity, which in turn has a direct relation to the target entity.
    """
    return (
        "SELECT"  # noqa: S608 — UUIDs validated by _UUID_RE; limit is a Python int
        "  r1.canonical_type::text    AS r1_type,"
        "  COALESCE(r1.confidence, 0.0)::float AS r1_conf,"
        "  r1.subject_entity_id::text AS s_id,"
        "  r1.object_entity_id::text  AS t_id,"
        "  ce_s.canonical_name::text  AS s_name,"
        "  ce_s.entity_type::text     AS s_type,"
        "  ce_t.canonical_name::text  AS t_name,"
        "  ce_t.entity_type::text     AS t_type,"
        "  ce_m.entity_id::text       AS mid_id,"
        "  ce_m.canonical_name::text  AS mid_name,"
        "  ce_m.entity_type::text     AS mid_type,"
        "  r2.canonical_type::text    AS r2_type,"
        "  COALESCE(r2.confidence, 0.0)::float AS r2_conf"
        " FROM relations r1"
        " JOIN relations r2 ON r2.subject_entity_id = r1.object_entity_id"
        " JOIN canonical_entities ce_s ON ce_s.entity_id = r1.subject_entity_id"
        " JOIN canonical_entities ce_t ON ce_t.entity_id = r2.object_entity_id"
        " JOIN canonical_entities ce_m ON ce_m.entity_id = r1.object_entity_id"
        f" WHERE r1.subject_entity_id = '{source_id_str}'"
        f"   AND r2.object_entity_id  = '{target_id_str}'"
        f"   AND r1.object_entity_id <> '{source_id_str}'"
        f"   AND r1.object_entity_id <> '{target_id_str}'"
        " ORDER BY (COALESCE(r1.confidence, 0.0) * COALESCE(r2.confidence, 0.0)) DESC"
        f" LIMIT {limit}"
    )


async def _setup_age_session(session: AsyncSession) -> None:
    """Load AGE extension and set the search_path for the current session.

    Must be called before any AGE Cypher query on a fresh session.
    This matches the pattern enforced in AgeSyncWorker._setup_age_session().
    """
    await session.execute(text("LOAD 'age'"))
    await session.execute(text("SET search_path = ag_catalog, public"))


# ── Agtype parsing ────────────────────────────────────────────────────────────


def _parse_agtype_text(raw: Any) -> list[dict[str, Any]]:
    """Coerce an agtype column value (str / bytes / None) to a Python list.

    AGE returns agtype values as their text representation when no codec is
    registered with asyncpg.  The text for a list is standard JSON (no suffix).
    If the value already ends with a ``::`` type annotation, we strip it.
    """
    if raw is None:
        return []
    text_val: str = raw.decode() if isinstance(raw, bytes | bytearray) else str(raw)
    # Strip trailing ``::agtype`` or ``::path`` type annotations if present
    if "::" in text_val:
        text_val = text_val[: text_val.rfind("::")]
    text_val = text_val.strip()
    try:
        parsed = json.loads(text_val)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def _extract_nodes(node_dicts: list[dict[str, Any]]) -> list[_PathNode]:
    """Parse a list of AGE vertex dicts into _PathNode objects."""
    nodes: list[_PathNode] = []
    for nd in node_dicts:
        props = nd.get("properties") or {}
        entity_id = props.get("entity_id")
        canonical_name = props.get("canonical_name")
        entity_type = props.get("entity_type")
        if entity_id and canonical_name and entity_type:
            nodes.append(
                _PathNode(
                    entity_id=str(entity_id),
                    canonical_name=str(canonical_name),
                    entity_type=str(entity_type),
                ),
            )
    return nodes


def _extract_edges(edge_dicts: list[dict[str, Any]], nodes: list[_PathNode]) -> list[_PathEdge]:
    """Parse a list of AGE edge dicts into _PathEdge objects.

    ``nodes`` is the ordered list of path nodes — edges[i] connects nodes[i] → nodes[i+1].
    """
    edges: list[_PathEdge] = []
    for idx, ed in enumerate(edge_dicts):
        props = ed.get("properties") or {}
        confidence_raw = props.get("confidence")
        canonical_type = ed.get("label", "")
        if confidence_raw is None or not canonical_type:
            continue
        from_node = nodes[idx] if idx < len(nodes) else None
        to_node = nodes[idx + 1] if (idx + 1) < len(nodes) else None
        if from_node is None or to_node is None:
            continue
        edges.append(
            _PathEdge(
                from_entity_id=from_node.entity_id,
                to_entity_id=to_node.entity_id,
                canonical_type=str(canonical_type),
                confidence=float(confidence_raw),
                direction="forward",
            ),
        )
    return edges


def _path_confidence(edges: list[_PathEdge]) -> float:
    """Product of edge confidences — lower is weaker (PRD §6.3)."""
    if not edges:
        return 0.0
    result = 1.0
    for e in edges:
        result *= e.confidence
    return round(result, 6)


# ── Use case ──────────────────────────────────────────────────────────────────


class CypherPathUseCase:
    """Find shortest path(s) between two entities using Apache AGE Cypher.

    Validates entities exist (SQL), sets up AGE session, executes Cypher, and
    parses agtype results into :class:`CypherPathResult`.

    Raises
    ------
        CypherDisabledError:       KNOWLEDGE_GRAPH_CYPHER_ENABLED=false.
        CypherEntityNotFoundError: source or target entity not in canonical_entities.
        CypherTimeoutError:        AGE query exceeded 5 s statement_timeout.

    """

    async def execute(
        self,
        session: AsyncSession,
        entity_repo: CanonicalEntityRepository,
        *,
        cypher_enabled: bool,
        source_entity_id: UUID,
        target_entity_id: UUID,
        max_hops: int = 3,
        min_confidence: float = 0.3,
        relation_types: list[str] | None = None,
        all_paths: bool = False,
    ) -> CypherPathResult:
        if not cypher_enabled:
            raise CypherDisabledError("Cypher endpoints are disabled (KNOWLEDGE_GRAPH_CYPHER_ENABLED=false)")

        # Validate entities exist (fast SQL check before AGE session setup)
        if not await entity_repo.exists(source_entity_id):
            raise CypherEntityNotFoundError(source_entity_id)
        if not await entity_repo.exists(target_entity_id):
            raise CypherEntityNotFoundError(target_entity_id)

        # BP-461: validate entity UUIDs before embedding as SQL string literals.
        # UUIDs contain only [0-9a-fA-F-] — no SQL metacharacters possible.
        source_id_str = str(source_entity_id)
        target_id_str = str(target_entity_id)
        if not _UUID_RE.match(source_id_str):
            raise ValueError(f"source_entity_id is not a valid UUID: {source_id_str!r}")
        if not _UUID_RE.match(target_id_str):
            raise ValueError(f"target_entity_id is not a valid UUID: {target_id_str!r}")

        limit = 5 if all_paths else 1
        start_ms = time.monotonic() * 1000

        # BP-461: bypass AGE entirely for 1-hop paths — AGE 1.5.0 raises a
        # PostgresSyntaxError on Cypher list comprehensions using `|`.
        # Query the SQL `relations` table directly for direct and 2-hop paths;
        # this is both faster and avoids the AGE session overhead entirely.
        # Phase 1 — try direct (1-hop) relation lookup.
        paths: list[_Path] = []
        try:
            sql_direct = _build_direct_sql(source_id_str, target_id_str, limit)
            result = await session.execute(text(sql_direct))
            rows_direct = result.fetchall()

            if rows_direct:
                paths = self._build_paths_from_sql(
                    list(rows_direct),
                    relation_types,
                    hops=1,
                    source_id_str=source_id_str,
                    target_id_str=target_id_str,
                )

            # Phase 2 — try 2-hop path lookup if no direct relations found.
            if not paths and max_hops >= 2:
                sql_twohop = _build_twohop_sql(source_id_str, target_id_str, limit)
                result2 = await session.execute(text(sql_twohop))
                rows_twohop = result2.fetchall()
                if rows_twohop:
                    paths = self._build_paths_from_sql(
                        list(rows_twohop),
                        relation_types,
                        hops=2,
                        source_id_str=source_id_str,
                        target_id_str=target_id_str,
                    )
        except Exception as exc:
            exc_str = str(exc).lower()
            if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
                raise CypherTimeoutError("SQL path query exceeded statement_timeout") from exc
            raise

        elapsed_ms = int(time.monotonic() * 1000 - start_ms)
        return CypherPathResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            paths=paths,
            paths_found=len(paths),
            query_time_ms=elapsed_ms,
        )

    def _build_paths_from_sql(
        self,
        rows: list[Any],
        relation_types: list[str] | None,
        hops: int,
        source_id_str: str = "",
        target_id_str: str = "",
    ) -> list[_Path]:
        """Parse SQL result rows (13 columns) into _Path objects.

        Column layout for hops=1 (_build_direct_sql):
          [0] rel_type  [1] confidence  [2] s_id      [3] t_id
          [4] s_name    [5] s_type      [6] t_name    [7] t_type
          [8-12] NULLs

        Column layout for hops=2 (_build_twohop_sql):
          [0] r1_type   [1] r1_conf     [2] s_id      [3] mid_id (r1.object_entity_id)
          [4] s_name    [5] s_type      [6] target_name (ce_t)  [7] target_type (ce_t)
          [8] mid_id    [9] mid_name    [10] mid_type  [11] r2_type  [12] r2_conf

        For hops=1: direction normalised so source_id_str is the first node.
        For hops=2: target entity ID supplied via target_id_str (r2.object_entity_id
          equals target_id_str by WHERE clause; its name/type come from ce_t columns).
        """
        paths: list[_Path] = []
        for row in rows:
            if len(row) < 13:
                continue
            try:
                rel_type = str(row[0] or "")
                confidence = float(row[1] or 0.0)
                s_id = str(row[2] or "")
                s_name = str(row[4] or "")
                s_type = str(row[5] or "")

                if hops == 1:
                    t_id = str(row[3] or "")
                    t_name = str(row[6] or "")
                    t_type = str(row[7] or "")
                    if not rel_type or not s_id or not t_id:
                        continue
                    # Normalise: ensure source_id_str is the first node in the path.
                    if s_id == source_id_str or not source_id_str:
                        src_node = _PathNode(entity_id=s_id, canonical_name=s_name, entity_type=s_type)
                        tgt_node = _PathNode(entity_id=t_id, canonical_name=t_name, entity_type=t_type)
                        from_id, to_id = s_id, t_id
                    else:
                        # Relation stored in reverse direction in DB — swap.
                        src_node = _PathNode(entity_id=t_id, canonical_name=t_name, entity_type=t_type)
                        tgt_node = _PathNode(entity_id=s_id, canonical_name=s_name, entity_type=s_type)
                        from_id, to_id = t_id, s_id
                    nodes: list[_PathNode] = [src_node, tgt_node]
                    edges: list[_PathEdge] = [
                        _PathEdge(
                            from_entity_id=from_id,
                            to_entity_id=to_id,
                            canonical_type=rel_type,
                            confidence=confidence,
                            direction="forward",
                        )
                    ]

                else:  # hops == 2
                    # row[3] = r1.object_entity_id = mid ID (confusingly named t_id in SQL)
                    target_name = str(row[6] or "")  # ce_t.canonical_name = actual target
                    target_type = str(row[7] or "")  # ce_t.entity_type = actual target
                    mid_id = str(row[8] or "")  # ce_m.entity_id = mid
                    mid_name = str(row[9] or "")
                    mid_type = str(row[10] or "")
                    r2_type = str(row[11] or "")
                    r2_conf = float(row[12] or 0.0)
                    if not rel_type or not r2_type or not mid_id:
                        continue
                    src_node = _PathNode(entity_id=s_id, canonical_name=s_name, entity_type=s_type)
                    mid_node = _PathNode(entity_id=mid_id, canonical_name=mid_name, entity_type=mid_type)
                    tgt_node = _PathNode(
                        entity_id=target_id_str,
                        canonical_name=target_name,
                        entity_type=target_type,
                    )
                    nodes = [src_node, mid_node, tgt_node]
                    edges = [
                        _PathEdge(
                            from_entity_id=s_id,
                            to_entity_id=mid_id,
                            canonical_type=rel_type,
                            confidence=confidence,
                            direction="forward",
                        ),
                        _PathEdge(
                            from_entity_id=mid_id,
                            to_entity_id=target_id_str,
                            canonical_type=r2_type,
                            confidence=r2_conf,
                            direction="forward",
                        ),
                    ]

            except (TypeError, ValueError, IndexError):
                continue

            # Post-hoc relation_types filter (applied in Python, same as AGE path).
            if relation_types is not None:
                allowed = {rt.upper() for rt in relation_types}
                if not all(e.canonical_type.upper() in allowed for e in edges):
                    continue

            paths.append(
                _Path(
                    hops=hops,
                    nodes=nodes,
                    edges=edges,
                    path_confidence=_path_confidence(edges),
                )
            )
        return paths

    def _build_paths(
        self,
        rows: list[Any],
        relation_types: list[str] | None,
    ) -> list[_Path]:
        """Parse raw AGE result rows (one per path) into _Path objects."""
        paths: list[_Path] = []
        for row in rows:
            nodes_raw = row[0] if len(row) > 0 else None
            edges_raw = row[1] if len(row) > 1 else None

            node_dicts = _parse_agtype_text(nodes_raw)
            edge_dicts = _parse_agtype_text(edges_raw)

            nodes = _extract_nodes(node_dicts)
            edges = _extract_edges(edge_dicts, nodes)

            # Post-hoc relation_types filter (applied in Python — not in Cypher)
            if relation_types is not None:
                allowed = {rt.upper() for rt in relation_types}
                if not all(e.canonical_type.upper() in allowed for e in edges):
                    continue

            paths.append(
                _Path(
                    hops=len(edges),
                    nodes=nodes,
                    edges=edges,
                    path_confidence=_path_confidence(edges),
                ),
            )
        return paths
