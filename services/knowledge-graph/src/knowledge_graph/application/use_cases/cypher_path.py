"""CypherPathUseCase — shortest path between two entities via Apache AGE (PRD-0018 §6.3).

Security invariants (enforced here — see Pitfalls in .claude-context.md):
- Entity IDs are UUID-validated ([0-9a-fA-F-] only) and embedded as string literals
  in the Cypher pattern — never passed as $params (BP-459-C / BP-450: asyncpg's
  prepared-statement protocol confuses PostgreSQL $1 params with Cypher $var refs).
- ``max_hops`` is a Pydantic-validated integer [1, 5] and is embedded as a numeric
  literal in the Cypher pattern. The route handler ensures it cannot exceed 5.
- ``relation_types`` filtering is applied in Python after the query (post-hoc),
  using the agtype-parsed label string. No user string is embedded in Cypher.

AGE 1.5.0 compatibility — confirmed working syntax (BP-461, 2026-05-11):
  AGE 1.5.0 does NOT support:
    - ``shortestPath()`` / ``allShortestPaths()`` — raises "function does not exist"
    - ``[n IN nodes(p) | n]`` list comprehension with ``|`` — raises syntax error
    - ``ALL(rel IN relationships(path) WHERE ...)`` — raises syntax error
  AGE 1.5.0 DOES support (verified by live query):
    - ``MATCH p = (s)-[*1..N]-(t) RETURN nodes(p), relationships(p)``
    - ``ORDER BY length(p)`` in Cypher body to sort shortest paths first
    - ``LIMIT N`` for controlling result count
  Fix: use ``RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col`` —
  NOT the broken ``[n IN nodes(p) | n]`` list comprehension form.

AGE session requirements:
  Every DB session that issues AGE Cypher MUST execute the following first:
    LOAD 'age'
    SET search_path = ag_catalog, public
  This is enforced in ``_setup_age_session()`` called at the start of execute().

Result parsing:
  AGE Cypher returns ``agtype`` columns. asyncpg returns these as raw bytes
  (no registered codec for custom types). The text representation of agtype
  arrays includes per-element type annotations:
    ``[{...}::vertex, {...}::vertex]``  (nodes array)
    ``[{...}::edge, {...}::edge]``      (edges array)
  ``_parse_agtype_text`` strips all ``}::word`` / ``]::word`` annotations with
  a regex before calling json.loads — fixes the old ``rfind("::")`` approach
  which only stripped the outermost annotation (BP-461).
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
    """Raised when the AGE Cypher query exceeds the 30 s statement_timeout backstop."""


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

# Statement timeout — 30 s BACKSTOP only (BP-687, 2026-06-12).
# This is deliberately a safety net, NOT the mechanism we rely on. The real fix
# for the hub-to-hub blow-up (OpenAI↔Microsoft 504s) is the *staged shortest-first*
# traversal below (`_execute_staged`): we probe one exact hop length at a time
# (1, then 2, then 3) and STOP at the first length that yields a path, instead of
# the old ``-[*1..3]- ... ORDER BY length(p)`` which forced AGE to enumerate the
# entire O(avg_degree^3) variable-length frontier before it could sort+LIMIT.
# Most hub pairs connect at 1-2 hops, so the explosive 3-hop frontier is never
# materialised. The route handler awaits this use case directly (no separate
# upstream HTTP/asyncio timeout in the KG service), so this constant is the single
# authoritative deadline for the path query — but it should now rarely bind.
_STATEMENT_TIMEOUT_MS = "30000"

# Number of paths returned when all_paths=True (top-K cap embedded as a Cypher LIMIT
# so the planner can stop scanning after K matches at the winning hop length).
_ALL_PATHS_LIMIT = 5


def _build_path_sql(
    source_id_str: str,
    target_id_str: str,
    max_hops: int,
    all_paths: bool,
    *,
    exact_hops: int | None = None,
) -> str:
    """Build AGE Cypher SQL for shortest-path discovery between two entities.

    Uses the confirmed-working AGE 1.5.0 syntax (BP-461, 2026-05-11):
      ``MATCH p = (s:entity {...})-[*L..L]-(t:entity {...})``
      ``RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col LIMIT N``

    Optimisation (BP-687, 2026-06-12) — *staged shortest-first*:
      When ``exact_hops`` is given, the relationship pattern is pinned to that
      EXACT length (``*L..L``), not the open range ``*1..max_hops``. The caller
      (:meth:`CypherPathUseCase._execute_staged`) issues these probes in
      increasing order (1, 2, …, max_hops) and stops at the first that returns
      a row. A single fixed-length match needs no ``ORDER BY length(p)`` (every
      result is already the same, shortest-so-far length), which is what made
      the old open-range query materialise and sort the whole frontier before
      it could apply ``LIMIT`` — the root cause of the hub-to-hub 504s. AGE can
      now stop after ``LIMIT`` matches at the current depth and never expand the
      explosive deeper frontier when a shorter path exists.

      When ``exact_hops`` is None the legacy open-range pattern (``*1..max_hops``
      with ``ORDER BY length(p)``) is emitted — retained for callers/tests that
      want the single-query form; ``_execute_staged`` does not use it.

    WHY NOT ``shortestPath()``: AGE 1.5.0 raises "function does not exist".
    WHY NOT ``[n IN nodes(p) | n]``: AGE 1.5.0 raises syntax error on ``|``.

    Source/target IDs are pre-validated by ``_UUID_RE`` — only [0-9a-fA-F-] chars,
    safe to embed as Cypher string literals. ``max_hops``/``exact_hops`` are
    validated ints. All are embedded as literals (no $params) — see BP-450 / BP-459-C.
    """
    limit = _ALL_PATHS_LIMIT if all_paths else 1

    if exact_hops is not None:
        # Staged form: pin the pattern to one exact hop length. No ORDER BY needed
        # (single length ⇒ already uniform), so AGE stops after LIMIT matches at
        # this depth without enumerating the full O(degree^max_hops) frontier.
        return (
            "SELECT nodes_col, rels_col"  # noqa: S608 — UUIDs validated by _UUID_RE; hop/limit are validated ints
            " FROM ag_catalog.cypher('worldview_graph', $$"
            f" MATCH p = (s:entity {{entity_id: '{source_id_str}'}})"
            f"-[*{exact_hops}..{exact_hops}]-"
            f"(t:entity {{entity_id: '{target_id_str}'}})"
            " RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col"
            f" LIMIT {limit}"
            " $$) AS (nodes_col agtype, rels_col agtype)"
        )

    # Legacy open-range form (kept for completeness / single-query callers).
    return (
        "SELECT nodes_col, rels_col"  # noqa: S608 — UUIDs validated by _UUID_RE; max_hops/limit are validated ints
        " FROM ag_catalog.cypher('worldview_graph', $$"
        f" MATCH p = (s:entity {{entity_id: '{source_id_str}'}})"
        f"-[*1..{max_hops}]-"
        f"(t:entity {{entity_id: '{target_id_str}'}})"
        " RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col"
        " ORDER BY length(p)"
        f" LIMIT {limit}"
        " $$) AS (nodes_col agtype, rels_col agtype)"
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

    AGE 1.5.0 returns agtype arrays with per-element type annotations::

        [{...}::vertex, {...}::vertex]   (nodes array)
        [{...}::edge,   {...}::edge]     (edges array)

    The old ``rfind("::")`` approach only stripped the LAST ``::`` in the string,
    leaving inner ``::vertex`` annotations intact — causing json.loads to fail
    for arrays with more than one element.

    Fix (BP-461): regex strips ALL ``}::word`` and ``]::word`` annotations before
    calling json.loads, making any agtype array into valid JSON.
    """
    if raw is None:
        return []
    text_val: str = raw.decode() if isinstance(raw, bytes | bytearray) else str(raw)
    # Strip per-element AGE type annotations: ::vertex, ::edge, ::path, ::agtype
    text_val = re.sub(r"([}\]])::[ \t]*\w+", r"\1", text_val).strip()
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
        CypherTimeoutError:        AGE query exceeded 30 s statement_timeout backstop.

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

        # Validate entity UUIDs before embedding as Cypher string literals (BP-459-C).
        # UUIDs contain only [0-9a-fA-F-] — no Cypher/SQL metacharacters possible.
        source_id_str = str(source_entity_id)
        target_id_str = str(target_entity_id)
        if not _UUID_RE.match(source_id_str):
            raise ValueError(f"source_entity_id is not a valid UUID: {source_id_str!r}")
        if not _UUID_RE.match(target_id_str):
            raise ValueError(f"target_entity_id is not a valid UUID: {target_id_str!r}")

        start_ms = time.monotonic() * 1000

        # AGE session setup: LOAD 'age' + set search_path (required before any AGE query).
        await _setup_age_session(session)
        await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))

        rows = await self._execute_staged(
            session,
            source_id_str=source_id_str,
            target_id_str=target_id_str,
            max_hops=max_hops,
            all_paths=all_paths,
        )

        paths = self._build_paths(rows, relation_types)
        elapsed_ms = int(time.monotonic() * 1000 - start_ms)
        return CypherPathResult(
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            paths=paths,
            paths_found=len(paths),
            query_time_ms=elapsed_ms,
        )

    async def _execute_staged(
        self,
        session: AsyncSession,
        *,
        source_id_str: str,
        target_id_str: str,
        max_hops: int,
        all_paths: bool,
    ) -> list[Any]:
        """Probe hop lengths 1..max_hops in order; return rows from the first that hits.

        This is the heart of the BP-687 optimisation. Instead of one open-range
        ``-[*1..max_hops]-`` query (which forces AGE to enumerate the full
        O(avg_degree^max_hops) frontier before ``ORDER BY length(p)`` + ``LIMIT``
        can pick the shortest), we issue one *exact-length* query per hop depth
        and STOP at the first depth that returns any path:

          L=1: direct edge?      → if yes, done (1 cheap query, no frontier blow-up)
          L=2: 2-hop path?       → only reached when no direct edge exists
          L=3: 3-hop path?       → only reached when nothing shorter connects them

        For the hub pairs that caused the 504s (e.g. OpenAI↔Microsoft, connected
        directly via INVESTMENT_IN), the L=1 probe returns immediately and the
        expensive L=3 frontier is never expanded. Worst case (no path at all) is
        the same as before: every depth is probed, but each is a bounded
        fixed-length match with a LIMIT, which the planner can short-circuit.

        Shortest-first is guaranteed by construction: we ascend hop length and
        return on the first non-empty depth, so ``ORDER BY length(p)`` is no
        longer needed (and its removal is precisely what lets AGE stop early).

        all_paths semantics: with ``all_paths=False`` we want a single shortest
        path, so we stop at the first non-empty depth (LIMIT 1 inside Cypher).
        With ``all_paths=True`` we want up to ``_ALL_PATHS_LIMIT`` shortest paths;
        each depth's query already caps at that LIMIT, so the first non-empty
        depth yields the shortest paths. We do NOT keep probing deeper after the
        first hit even for all_paths=True — a strictly longer path is by
        definition not among the "shortest" set, so deeper probing would only
        re-introduce the expensive frontier we are trying to avoid.
        """
        collected: list[Any] = []
        for hops in range(1, max_hops + 1):
            sql = _build_path_sql(
                source_id_str,
                target_id_str,
                max_hops,
                all_paths,
                exact_hops=hops,
            )
            try:
                result = await session.execute(text(sql))
                rows = result.fetchall()
            except Exception as exc:
                exc_str = str(exc).lower()
                if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
                    raise CypherTimeoutError(
                        f"AGE Cypher query exceeded {_STATEMENT_TIMEOUT_MS} ms statement_timeout",
                    ) from exc
                raise
            if rows:
                # First non-empty depth wins (the shortest). Stop probing deeper —
                # a longer path is never preferred over a shorter one, and this is
                # exactly what prevents the deeper O(degree^N) frontier from ever
                # being expanded when a shorter connection exists.
                collected = list(rows)
                break
        return collected

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
