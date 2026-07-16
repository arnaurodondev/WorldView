"""RelationalGraphPathAdapter — recursive-CTE traversal over ``graph_edges`` (PLAN-0113).

A drop-in :class:`GraphPathEngine` implementation that traverses the relational
``graph_edges`` materialized view (migration 0063) with an ordinary Postgres
recursive CTE — NO Apache AGE, NO ``LOAD 'age'``, NO write session.  It exists
because the AGE Cypher VLE engine, while correct, degrades badly under
contention (~0.9 s p95 idle → ~17 s contended on the live graph), whereas a
settled-set recursive-CTE traversal over the same edges measured ~4 ms p50 /
~53 ms p95 (prototype: scripts/eval/bench_relational_traversal_prototype.py).

Two traversal shapes
--------------------
1. **Connectivity / shortest-hop** (``path_exists``): a SETTLED-SET recursive CTE
   using ``UNION`` (deduplicating — NOT ``UNION ALL``).  Each node is expanded at
   most once, so the frontier is bounded by |V| regardless of cycle count; we
   carry ``depth`` and read off the minimum depth at which ``target`` is settled.
   This is the cheap O(V+E) BFS-style probe that mirrors the prototype.

2. **Path enumeration** (``find_paths_between`` / ``find_paths_from_anchor``): a
   PATH-ARRAY recursive CTE that carries the ordered ``node_path`` (uuid[]) and
   parallel ``rel_path`` (uuid[]) so we can (a) reject cycles in-SQL
   (``NOT dst = ANY(node_path)``), (b) degree-cap each expansion (a per-node fan
   limit so a hub cannot explode the frontier), and (c) ``LIMIT`` the number of
   materialised paths.  The resulting node/relation id arrays are then resolved
   to full :class:`RawPath` objects (names, types, edge labels/confidences,
   ``edge_forward``) by a single batch lookup — mirroring the AGE adapter's
   ``_row_to_raw_path`` assembly for byte-for-byte parity.

AGE parity
----------
- Self-loop paths (``node_ids[0] == node_ids[-1]``) are rejected, same as AGE.
- Membership pruning reuses the SAME ``domain.constants.MEMBERSHIP_RELATIONS``
  set, applied post-hoc in Python (a path is dropped if ANY edge label is a
  membership label) — identical semantics to ``AgeGraphPathEngine``.
- ``edge_forward[i]`` is ``True`` when the edge was walked subject→object, i.e.
  the ``graph_edges`` row's ``src == subject_entity_id``.  The matview carries
  ``subject_entity_id`` precisely so this is a column comparison, not a guess.
- ``find_paths_between`` allows a 1-hop direct connection; ``find_paths_from_anchor``
  starts at 2 hops (insights, never a trivial known edge) — same as AGE.

Read replica (R27)
------------------
Unlike the AGE adapter (which needs a write session for ``LOAD 'age'``), this
adapter is pure SQL over a materialized view and runs on the READ-replica session
factory (``app.state.read_factory``).  Each query sets ``statement_timeout`` and
``max_parallel_workers_per_gather = 0`` as session-scoped GUCs on the same
connection (the recursive CTE is a serial plan; parallel workers add overhead and
muddy the timeout accounting — same hygiene the AGE engine applies).

Security
--------
``entity_id`` values are strict-UUID-validated and bound as SQLAlchemy parameters
(``:source`` etc.) — no string interpolation of identifiers.  ``max_hops`` /
``limit`` / ``degree_cap`` are validated ints bound as parameters.  There is no
Cypher here, so the asyncpg ``$1`` vs Cypher ``$var`` confusion (BP-450) does not
apply; ordinary parameter binding is used throughout.
"""

from __future__ import annotations

# The only string interpolation in this module is the STATIC ``terminal`` literal
# in ``_build_enumerate_sql`` (one of two fixed predicates — never user input);
# every value (uuids, hop bounds, limits) is bound as a SQLAlchemy parameter.  So
# the S608 string-SQL heuristic is a false positive here — suppressed file-wide,
# mirroring scripts/eval/bench_relational_traversal_prototype.py.
# ruff: noqa: S608
import contextlib
import re
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.graph_path_engine import GraphPathEngine, RawPath
from knowledge_graph.application.use_cases.cypher_path import CypherTimeoutError
from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Any

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from sqlalchemy.sql.elements import TextClause

logger = get_logger(__name__)  # type: ignore[no-any-return]

# UUID validation pattern — guards entity_ids before binding (defence in depth;
# the values are bound as params, not interpolated).
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

# DB-side statement_timeout for each traversal query (ms).  The relational
# traversal is fast (tens of ms), so a generous-but-bounded ceiling catches a
# pathological plan without ever firing on a healthy query.
_STATEMENT_TIMEOUT_MS = 25000

# Default per-node fan-out cap for path ENUMERATION (a hub with thousands of
# neighbours must not explode the path-array frontier).  Overridable via config
# (``Settings.relational_traversal_degree_cap``).  Connectivity (``path_exists``)
# is NOT degree-capped — the settled-set UNION already bounds it by |V|.
_DEFAULT_DEGREE_CAP = 200

# Hard ceiling on enumerated paths per query (safety net above the caller limit).
_MAX_LIMIT = 200


def _validate_uuid(entity_id: UUID) -> str:
    """Validate UUID format and return the canonical string for binding."""
    s = str(entity_id)
    if not _UUID_RE.match(s):
        msg = f"entity_id is not a valid UUID: {s!r}"
        raise ValueError(msg)
    return s


def _path_has_membership(rel_types: Sequence[str]) -> bool:
    """True if any edge label is a membership relation (post-hoc pruning, FR-3)."""
    return any(rt.upper() in MEMBERSHIP_RELATIONS for rt in rel_types)


# ── SQL builders ────────────────────────────────────────────────────────────────


# Settled-set connectivity probe (UNION, dedup).  Returns the MINIMUM depth at
# which ``target`` is reached, or no row if unreachable within ``max_hops``.
# Bound params: source, target, max_hops.
_PATH_EXISTS_SQL = text(
    """
    WITH RECURSIVE reach(node, depth) AS (
        SELECT CAST(:source AS uuid), 0
        UNION
        SELECT e.dst, r.depth + 1
          FROM reach r
          JOIN public.graph_edges e ON e.src = r.node
         WHERE r.depth < :max_hops
    )
    SELECT min(depth) AS hops
      FROM reach
     WHERE node = CAST(:target AS uuid)
       AND depth > 0
    """
)


def _build_enumerate_sql(*, anchor_free_target: bool) -> TextClause:
    """Build the path-array enumeration recursive CTE.

    Carries ``node_path`` (uuid[]) + ``rel_path`` (uuid[]) so cycles are rejected
    in-SQL and the caller can resolve full edge/node detail afterwards.  The
    expansion is degree-capped per node via a ``row_number()`` window in a
    lateral-free correlated form (``rn <= :degree_cap``), and the whole walk is
    bounded by ``:max_hops`` depth.

    When ``anchor_free_target`` is False (pairwise) the terminal filter binds
    ``node = :target``.  When True (anchor discovery) every node at depth
    ``>= :min_hops`` is a candidate terminal (open discovery).

    Bound params: source [, target], min_hops, max_hops, degree_cap, limit.
    """
    # Degree-cap the expansion: number the neighbours of each frontier node and
    # keep only the first ``:degree_cap`` (stable order by dst).  This is applied
    # inside the recursive term so a hub never enqueues more than the cap.
    terminal = "w.node = CAST(:target AS uuid)" if not anchor_free_target else "TRUE"

    return text(  # — all interpolation is the static ``terminal`` literal above; values bound as params
        f"""
        WITH RECURSIVE walk(node, depth, node_path, rel_path) AS (
            SELECT
                CAST(:source AS uuid),
                0,
                ARRAY[CAST(:source AS uuid)],
                ARRAY[]::uuid[]
            UNION ALL
            SELECT
                capped.dst,
                w.depth + 1,
                w.node_path || capped.dst,
                w.rel_path || capped.relation_id
              FROM walk w
              JOIN LATERAL (
                    SELECT e.dst, e.relation_id
                      FROM public.graph_edges e
                     WHERE e.src = w.node
                       AND NOT e.dst = ANY(w.node_path)
                     ORDER BY e.dst, e.relation_id
                     LIMIT :degree_cap
              ) AS capped ON TRUE
             WHERE w.depth < :max_hops
        )
        SELECT node_path, rel_path, depth
          FROM walk w
         WHERE w.depth >= :min_hops
           AND {terminal}
         ORDER BY w.depth, w.node_path
         LIMIT :limit
        """
    )


# Batch resolver: given a set of entity_ids, return name/type per id.
_RESOLVE_NODES_SQL = text(
    """
    SELECT entity_id, canonical_name, entity_type
      FROM canonical_entities
     WHERE entity_id = ANY(:ids)
    """
)

# Batch resolver: given a set of relation_ids, return per-edge detail.  ``typ``
# is the AGE-style label; ``subject_entity_id`` lets us compute edge_forward.
_RESOLVE_EDGES_SQL = text(
    """
    SELECT DISTINCT relation_id, typ, confidence, subject_entity_id
      FROM public.graph_edges
     WHERE relation_id = ANY(:ids)
    """
)


class _NodeInfo:
    __slots__ = ("etype", "name")

    def __init__(self, name: str, etype: str) -> None:
        self.name = name
        self.etype = etype


class _EdgeInfo:
    __slots__ = ("confidence", "subject_entity_id", "typ")

    def __init__(self, typ: str, confidence: float, subject_entity_id: str) -> None:
        self.typ = typ
        self.confidence = confidence
        self.subject_entity_id = subject_entity_id


class RelationalGraphPathAdapter(GraphPathEngine):
    """Recursive-CTE :class:`GraphPathEngine` over the ``graph_edges`` matview.

    Args:
    ----
        session_factory: READ-replica async sessionmaker (``app.state.read_factory``).
            Pure SQL over a materialized view — no write session / no ``LOAD 'age'``.
        degree_cap: Per-node fan-out cap for path ENUMERATION (default 200).
            Connectivity probing is not degree-capped (the settled-set UNION
            already bounds it).

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],  # type: ignore[type-arg]
        *,
        degree_cap: int = _DEFAULT_DEGREE_CAP,
    ) -> None:
        self._sf = session_factory
        self._degree_cap = max(1, int(degree_cap))

    # ── Session hygiene ─────────────────────────────────────────────────────

    async def _setup_session(self, session: AsyncSession) -> None:
        """Apply session-scoped GUCs (timeout + serial plan) on this connection.

        Session-scoped ``SET`` (not ``SET LOCAL``) so the GUC persists for every
        statement on the connection — same rationale as the AGE engine's
        ``_setup_age_session`` (a ``SET LOCAL`` would evaporate before the
        traversal query under SQLAlchemy autocommit).
        """
        await session.execute(text(f"SET statement_timeout = {int(_STATEMENT_TIMEOUT_MS)}"))
        await session.execute(text("SET max_parallel_workers_per_gather = 0"))

    # ── Port methods ────────────────────────────────────────────────────────

    async def path_exists(self, source: UUID, target: UUID, *, max_hops: int) -> int | None:
        """Shortest hop-count via the settled-set connectivity probe (or None)."""
        src = _validate_uuid(source)
        tgt = _validate_uuid(target)
        if src == tgt:
            # Self is trivially 0-hop "connected" but that is not a path.
            return None
        async with self._sf() as session:
            await self._setup_session(session)
            row = await self._execute_one(
                session,
                _PATH_EXISTS_SQL,
                {"source": src, "target": tgt, "max_hops": int(max_hops)},
            )
        if row is None or row[0] is None:
            return None
        return int(row[0])

    async def find_paths_between(
        self,
        source: UUID,
        target: UUID,
        *,
        max_hops: int,
        prune_membership: bool,
        limit: int,
    ) -> list[RawPath]:
        """Up to ``limit`` distinct paths between two bound endpoints (1..max_hops)."""
        src = _validate_uuid(source)
        tgt = _validate_uuid(target)
        if src == tgt:
            return []
        return await self._discover(
            source_id=src,
            target_id=tgt,
            min_hops=1,
            max_hops=max_hops,
            prune_membership=prune_membership,
            limit=limit,
        )

    async def find_paths_from_anchor(
        self,
        entity_id: UUID,
        *,
        max_hops: int,
        prune_membership: bool,
        limit: int,
        min_hops: int = 2,
    ) -> list[RawPath]:
        """Up to ``limit`` insight paths radiating from one anchor (>=2 hops).

        ``min_hops`` is clamped to >= 2 (PathInsight enforces hop_count >= 2);
        exposed for the data-coverage tuning (2026-07-16) parity with the AGE
        engine.
        """
        src = _validate_uuid(entity_id)
        return await self._discover(
            source_id=src,
            target_id=None,
            min_hops=max(2, min_hops),
            max_hops=max_hops,
            prune_membership=prune_membership,
            limit=limit,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    async def _discover(
        self,
        *,
        source_id: str,
        target_id: str | None,
        min_hops: int,
        max_hops: int,
        prune_membership: bool,
        limit: int,
    ) -> list[RawPath]:
        """Enumerate, resolve, prune, and assemble RawPaths shortest-first."""
        capped_limit = min(max(1, int(limit)), _MAX_LIMIT)
        # Over-fetch so post-hoc membership pruning still yields ``limit`` keepers.
        fetch = min(_MAX_LIMIT, capped_limit * 2) if prune_membership else capped_limit
        sql = _build_enumerate_sql(anchor_free_target=target_id is None)
        params = {
            "source": source_id,
            "min_hops": max(1, int(min_hops)),
            "max_hops": int(max_hops),
            "degree_cap": self._degree_cap,
            "limit": int(fetch),
        }
        if target_id is not None:
            params["target"] = target_id

        async with self._sf() as session:
            await self._setup_session(session)
            rows = await self._execute_all(session, sql, params)
            if not rows:
                self._log(source_id, target_id, prune_membership, 0, max_hops)
                return []

            # Collect every node + relation id across all candidate paths, then
            # batch-resolve names/types/edge-detail in two queries (avoids an
            # N+1 round-trip per path).
            node_ids_all: set[str] = set()
            rel_ids_all: set[str] = set()
            raw_rows: list[tuple[list[str], list[str]]] = []
            for node_path, rel_path, _depth in rows:
                npath = [str(n) for n in (node_path or [])]
                rpath = [str(r) for r in (rel_path or [])]
                if len(npath) < 2 or len(rpath) != len(npath) - 1:
                    continue
                raw_rows.append((npath, rpath))
                node_ids_all.update(npath)
                rel_ids_all.update(rpath)

            node_info = await self._resolve_nodes(session, node_ids_all)
            edge_info = await self._resolve_edges(session, rel_ids_all)

        collected: list[RawPath] = []
        seen: set[tuple[str, ...]] = set()
        for npath, rpath in raw_rows:
            if len(collected) >= capped_limit:
                break
            path = self._assemble(npath, rpath, node_info, edge_info)
            if path is None:
                continue
            # Self-loop guard: endpoints must be distinct.
            if path.node_ids[0] == path.node_ids[-1]:
                continue
            # Membership pruning (FR-3) — identical to the AGE engine.
            if prune_membership and _path_has_membership(path.rel_types):
                continue
            key = path.node_ids
            if key in seen:
                continue
            seen.add(key)
            collected.append(path)

        self._log(source_id, target_id, prune_membership, len(collected), max_hops)
        return collected

    @staticmethod
    def _assemble(
        node_path: list[str],
        rel_path: list[str],
        node_info: dict[str, _NodeInfo],
        edge_info: dict[str, _EdgeInfo],
    ) -> RawPath | None:
        """Build a :class:`RawPath` from node + relation id arrays.

        Mirrors ``AgeGraphPathEngine._row_to_raw_path``: pulls name/type per node,
        label/confidence/relation_id per edge, and computes ``edge_forward[i]`` =
        (the node we leave from at hop i IS the edge's stored subject).
        """
        names: list[str] = []
        types: list[str] = []
        for nid in node_path:
            info = node_info.get(nid)
            if info is None:
                # A node missing from canonical_entities cannot be rendered — drop
                # the whole path (parity with AGE returning None on a bad vertex).
                return None
            names.append(info.name)
            types.append(info.etype)

        rel_types: list[str] = []
        edge_confs: list[float] = []
        rel_ids: list[UUID] = []
        edge_forward: list[bool] = []
        for i, rid in enumerate(rel_path):
            einfo = edge_info.get(rid)
            if einfo is None:
                return None
            rel_types.append(einfo.typ)
            edge_confs.append(float(einfo.confidence))
            # relation_id is always a UUID from the matview; defensively skip a
            # malformed id rather than crash the whole path assembly.
            with contextlib.suppress(ValueError, AttributeError, TypeError):
                rel_ids.append(UUID(rid))
            # FORWARD = the node we leave from (node_path[i]) is the stored subject.
            edge_forward.append(node_path[i] == einfo.subject_entity_id)

        if len(rel_types) != len(node_path) - 1:
            return None

        return RawPath(
            node_ids=tuple(node_path),
            node_names=tuple(names),
            node_types=tuple(types),
            rel_types=tuple(rel_types),
            edge_confs=tuple(edge_confs),
            rel_ids=tuple(rel_ids),
            edge_forward=tuple(edge_forward),
        )

    async def _resolve_nodes(self, session: AsyncSession, ids: set[str]) -> dict[str, _NodeInfo]:
        if not ids:
            return {}
        rows = await self._execute_all(session, _RESOLVE_NODES_SQL, {"ids": list(ids)})
        return {str(r[0]): _NodeInfo(str(r[1]), str(r[2])) for r in rows}

    async def _resolve_edges(self, session: AsyncSession, ids: set[str]) -> dict[str, _EdgeInfo]:
        if not ids:
            return {}
        rows = await self._execute_all(session, _RESOLVE_EDGES_SQL, {"ids": list(ids)})
        # A relation_id appears twice in graph_edges (forward + reverse rows) with
        # the SAME typ/confidence/subject_entity_id, so first-wins is correct.
        out: dict[str, _EdgeInfo] = {}
        for r in rows:
            rid = str(r[0])
            if rid not in out:
                out[rid] = _EdgeInfo(str(r[1]), float(r[2]), str(r[3]))
        return out

    async def _execute_one(self, session: AsyncSession, sql: TextClause, params: dict[str, object]) -> Row[Any] | None:
        try:
            result = await session.execute(sql, params)
            return result.first()
        except Exception as exc:
            self._maybe_timeout(exc)
            raise

    async def _execute_all(self, session: AsyncSession, sql: TextClause, params: dict[str, object]) -> list[Row[Any]]:
        try:
            result = await session.execute(sql, params)
            return list(result.fetchall())
        except Exception as exc:
            self._maybe_timeout(exc)
            raise

    @staticmethod
    def _maybe_timeout(exc: Exception) -> None:
        """Map a Postgres statement-timeout cancellation to CypherTimeoutError.

        Reuses ``CypherTimeoutError`` (not a new error type) so callers — the
        router maps it to HTTP 503 — get identical handling whether the AGE or the
        relational engine timed out.
        """
        exc_str = str(exc).lower()
        if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
            msg = f"relational traversal exceeded {_STATEMENT_TIMEOUT_MS} ms statement_timeout"
            raise CypherTimeoutError(msg) from exc

    @staticmethod
    def _log(source_id: str, target_id: str | None, prune_membership: bool, found: int, max_hops: int) -> None:
        logger.info(  # type: ignore[no-any-return]
            "relational_graph_path_discover_complete",
            source_id=source_id,
            target_id=target_id,
            mode="pairwise" if target_id is not None else "anchor",
            prune_membership=prune_membership,
            paths_found=found,
            max_hops=max_hops,
        )


__all__ = ["RelationalGraphPathAdapter"]
