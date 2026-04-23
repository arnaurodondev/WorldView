"""CypherPathUseCase — shortest path between two entities via Apache AGE (PRD-0018 §6.3).

Security invariants (enforced here — see Pitfalls in .claude-context.md):
- Entity IDs are ALWAYS passed as parameterized ``$source`` / ``$target`` values
  in the AGE params JSON dict — never string-interpolated into Cypher.
- ``max_hops`` is a Pydantic-validated integer [1, 5] and is embedded as a numeric
  literal in the Cypher pattern. The route handler ensures it cannot exceed 5.
- ``relation_types`` filtering is applied in Python after the query (post-hoc),
  using the agtype-parsed label string. No user string is embedded in Cypher.

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


def _build_path_sql(max_hops: int, *, all_paths: bool) -> str:
    """Build parameterized AGE Cypher SQL for path finding.

    ``max_hops`` is a Pydantic-validated int [1, 5] — safe to embed as a
    numeric literal (not a string from user input).  Entity IDs are always
    passed via the ``$source`` / ``$target`` Cypher parameters.
    """
    fn = "allShortestPaths" if all_paths else "shortestPath"
    limit_clause = " LIMIT 5" if all_paths else ""
    return (
        "SELECT nodes_col::text, edges_col::text"  # noqa: S608 — max_hops validated int; IDs via $source/$target
        " FROM ag_catalog.cypher('worldview_graph', $$"
        f" MATCH path = {fn}("
        f"   (s:Entity {{entity_id: $source}})-[r*1..{max_hops}]->(t:Entity {{entity_id: $target}})"
        " )"
        " WHERE ALL(rel IN relationships(path) WHERE rel.confidence >= $min_conf)"
        " RETURN [n IN nodes(path) | n] AS nodes_col,"
        "        [r IN relationships(path) | r] AS edges_col"
        + limit_clause
        + " $$, :params) AS (nodes_col agtype, edges_col agtype)"
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
                )
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
            )
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

    Raises:
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

        # AGE session setup — LOAD 'age' + SET search_path
        await _setup_age_session(session)
        await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))

        sql = _build_path_sql(max_hops, all_paths=all_paths)
        params_json = json.dumps(
            {
                "source": str(source_entity_id),
                "target": str(target_entity_id),
                "min_conf": min_confidence,
            }
        )

        start_ms = time.monotonic() * 1000
        try:
            result = await session.execute(text(sql), {"params": params_json})
            rows = result.fetchall()
        except Exception as exc:
            exc_str = str(exc).lower()
            if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
                raise CypherTimeoutError("AGE Cypher query exceeded 5 s statement_timeout") from exc
            raise
        elapsed_ms = int(time.monotonic() * 1000 - start_ms)

        paths = self._build_paths(list(rows), relation_types)
        return CypherPathResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            paths=paths,
            paths_found=len(paths),
            query_time_ms=elapsed_ms,
        )

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
                )
            )
        return paths
