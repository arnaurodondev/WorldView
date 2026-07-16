"""AgeGraphPathEngine — consolidated AGE traversal engine (PLAN-0112 W2, T-2-02).

This adapter implements the :class:`GraphPathEngine` port (PRD-0112 §6.5, FR-2)
by CONSOLIDATING the proven staged variable-length-edge (VLE) probing already in
``application/use_cases/cypher_path.py`` (BP-687) with full path-detail parsing
via agtype-text (``_parse_agtype_text``, BP-461).  It RETIRES the slow
untyped-explicit-edge form in ``path_discovery.py`` (``_build_2hop_sql`` /
``_build_3hop_sql``, BP-689) which forced AGE to enumerate the entire
O(degree^k) frontier.

Why VLE (and never the explicit ``-[r1]-(n1)-[r2]-`` form)
----------------------------------------------------------
The retired ``path_discovery`` form matched ``(n0)-[r1]-(n1)-[r2]-(n2)`` with
*explicit per-hop* relationships, which AGE executed as an O(#label-tables)
sequential scan across every edge-label table — ~18 s for a single 1-hop probe
on a hub (BP-689).  This engine instead emits a single **variable-length-edge
(VLE)** pattern::

    MATCH p = (s:entity {entity_id: '…'})-[*L..L]-(t:entity …)

which AGE executes via its (far faster) VLE traversal path — measured ~190 ms /
1.7 s for 2-/3-hop hub discovery vs the 18 s explicit form.

Membership pruning is applied **post-hoc in Python** (reject any path containing a
membership relation when ``prune_membership=True``), NOT via a typed label list in
the Cypher pattern.  AGE 1.5 does **not** support the multi-label VLE syntax
``-[:LABEL_A|LABEL_B*L..L]-`` (it is a parse error at the ``|`` — measured
2026-06-12, same family as the BP-461 ``|`` list-comprehension limitation), and it
does not support ``ALL(r IN relationships(p) WHERE type(r) <> …)`` (BP-450).  So
the only AGE-1.5-compatible options are an *untyped* VLE plus a Python label
filter (used here) — which removes membership noise from the *results* — accepting
that membership edges are still walked during traversal (the cap=3 budget absorbs
this; see the maxhops spike).

Staged shortest-first probing (BP-687)
--------------------------------------
Rather than one open-range ``*1..max_hops`` query with ``ORDER BY length(p)``
(which materialises + sorts the whole frontier before ``LIMIT``), we issue one
*exact-length* query per hop depth (``*L..L`` for L = 1, 2, …) and STOP at the
first depth that returns a row.  Most pairs connect early, so the explosive deep
frontier is never expanded.

GUC-scope fix (the difference between the flood stopping or not)
---------------------------------------------------------------
``_setup_age_session`` now applies ``statement_timeout`` and
``max_parallel_workers_per_gather = 0`` as **session-scoped** ``SET`` (not
``SET LOCAL``) on the SAME session that runs the traversal query.  ``SET LOCAL``
only lives for the current transaction; SQLAlchemy auto-commits a bare ``SET``
in its own transaction, so a ``SET LOCAL`` evaporated before the traversal query
ran — the GUCs never constrained the query.  Session-scoped ``SET`` persists on
the connection for every subsequent statement, so the timeout / serial-plan cap
actually bind the traversal.

Security
--------
``entity_id`` values are strict-UUID-validated (hex+hyphen only) before being
embedded as Cypher string literals (BP-450 / BP-459-C — asyncpg's prepared
statements confuse ``$1`` params with Cypher ``$var`` refs, so UUIDs are embedded
not parameterized).  Relationship labels in the allow-list come exclusively from
the validated ``_VALID_EDGE_LABELS`` whitelist, never from user input.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.application.ports.graph_path_engine import GraphPathEngine, RawPath
from knowledge_graph.application.use_cases.cypher_path import (
    CypherTimeoutError,
    _parse_agtype_text,
    _setup_age_session,
)

# The AGE edge-label whitelist (single source of truth) + the membership set.
from knowledge_graph.domain.constants import MEMBERSHIP_RELATIONS
from knowledge_graph.infrastructure.workers.age_sync_worker import (
    _VALID_EDGE_LABELS as _AGE_EDGE_LABELS,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# UUID validation pattern — guards entity_ids before embedding in Cypher.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

# ── Membership-pruning drift guard + traversable allow-list ────────────────────
#
# R12 keeps the domain layer free of infra imports, so the validation that all
# four membership labels really exist in the AGE whitelist (and the derived
# TRAVERSABLE_RELATIONS set) lives HERE in infrastructure, where importing the
# AGE-sync worker's whitelist is legal.  Fail loudly at import on drift (BP-405).
_missing_membership = MEMBERSHIP_RELATIONS - _AGE_EDGE_LABELS
if _missing_membership:  # pragma: no cover - defensive import-time guard
    _msg = (
        "MEMBERSHIP_RELATIONS contains labels absent from the AGE edge-label "
        f"whitelist (_VALID_EDGE_LABELS): {sorted(_missing_membership)}. The "
        "relation registry and domain.constants have drifted."
    )
    raise RuntimeError(_msg)

# Traversable relations = AGE whitelist - membership relations (FR-3).  Exposed
# for callers/scorers and the maxhops spike; the engine applies the membership
# filter post-hoc (AGE 1.5 cannot express it in the VLE pattern — see docstring).
TRAVERSABLE_RELATIONS: frozenset[str] = frozenset(_AGE_EDGE_LABELS) - MEMBERSHIP_RELATIONS

# DB-side statement_timeout for each AGE query (ms).  Must be STRICTLY LESS than
# any client-side wait (none here — the engine awaits the query directly), and
# is the single authoritative deadline.  25 s mirrors the corrected value in
# path_discovery (BP-688): a clean ``canceling statement due to statement
# timeout`` instead of an orphaned connection.
_STATEMENT_TIMEOUT_MS = "25000"

# Hard cap on returned paths per query (safety net; callers pass an explicit
# ``limit`` that is typically far smaller).
_MAX_LIMIT = 200


def _validate_uuid(entity_id: UUID) -> str:
    """Validate UUID format and return the string for Cypher embedding."""
    s = str(entity_id)
    if not _UUID_RE.match(s):
        raise ValueError(f"entity_id is not a valid UUID: {s!r}")
    return s


def _path_has_membership(rel_types: tuple[str, ...]) -> bool:
    """True if any edge label is a membership relation (post-hoc pruning, FR-3)."""
    return any(rt.upper() in MEMBERSHIP_RELATIONS for rt in rel_types)


def _build_vle_sql(
    *,
    source_id: str,
    target_id: str | None,
    exact_hops: int,
    limit: int,
) -> str:
    """Build an untyped staged-VLE Cypher SQL for one exact hop length.

    - ``source_id`` end is always bound.
    - ``target_id`` is bound for pairwise queries (find_paths_between) and left
      FREE (an unbound ``(t:entity)``) for anchor discovery (find_paths_from_anchor).
    - ``exact_hops`` pins the relationship pattern to ``*L..L`` (staged probe,
      BP-687) — no ``ORDER BY length(p)`` needed (uniform length).

    The relationship is an UNTYPED VLE ``-[*L..L]-`` (NOT the explicit
    ``-[r1]-(n1)-[r2]-`` form, BP-689; and NOT the multi-label ``-[:A|B*L..L]-``
    form which AGE 1.5 rejects with a parse error).  Membership relations are
    filtered out of the *results* in Python (``_path_has_membership``), not in the
    Cypher pattern.

    Returns ``nodes(p)`` and ``relationships(p)`` as agtype list columns parsed
    with ``_parse_agtype_text`` (agtype-text parse, BP-461), which is why no
    separate "typed fixed-k scalar" detail query is needed (AD-1 consolidation).
    """
    # Pairwise binds both ends; anchor discovery leaves the target end free
    # ``(t:entity)`` and relies on the ``id(s) <> id(t)`` self-loop guard below.
    target_pattern = f"(t:entity {{entity_id: '{target_id}'}})" if target_id is not None else "(t:entity)"

    # ``id(s) <> id(t)`` rejects 0-length / self-loop matches (AGE vertex ids).
    return (
        "SELECT nodes_col, rels_col"  # noqa: S608 — UUIDs validated by _UUID_RE; hops/limit are validated ints
        " FROM ag_catalog.cypher('worldview_graph', $$"
        f" MATCH p = (s:entity {{entity_id: '{source_id}'}})"
        f"-[*{exact_hops}..{exact_hops}]-"
        f"{target_pattern}"
        " WHERE id(s) <> id(t)"
        " RETURN nodes(p) AS nodes_col, relationships(p) AS rels_col"
        f" LIMIT {limit}"
        " $$) AS (nodes_col agtype, rels_col agtype)"
    )


# ── agtype detail parsing → RawPath ────────────────────────────────────────────


def _parse_rel_id(props: dict[str, Any]) -> UUID | None:
    """Extract the ``relation_id`` UUID from an AGE edge's properties.

    Relation edges carry ``relation_id`` (see age_sync_worker._build_relation_merge_sql).
    EVENT_EXPOSES edges carry ``exposure_id`` instead and have no relation_id →
    returns None (the rel_ids tuple simply omits that edge; novelty falls back).
    """
    raw = props.get("relation_id")
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _row_to_raw_path(nodes_raw: Any, rels_raw: Any) -> RawPath | None:
    """Assemble a :class:`RawPath` from one (nodes_col, rels_col) agtype row.

    ``nodes(p)`` and ``relationships(p)`` come back in PATH-WALK order; edge ``i``
    connects ``nodes[i] → nodes[i + 1]``.  We pull entity_id / canonical_name /
    entity_type from each vertex's properties and label / confidence / relation_id
    from each edge.

    Edge directionality (2026-06-13, see
    docs/audits/2026-06-13-edge-directionality-investigation.md): the VLE
    traversal is UNDIRECTED, so an edge can be walked against its stored
    ``subject → object`` direction.  Each AGE edge still carries its real
    ``start_id`` (subject) and ``end_id`` (object), and each AGE vertex carries
    its graphid ``id``.  We therefore compare each edge's ``start_id`` to the
    graphid of the path node it leaves from (``nodes[i].id``): if they match the
    edge was walked FORWARD (subject→object); otherwise it was walked REVERSE.
    This per-edge ``edge_forward`` flag lets renderers present every hop in TRUE
    subject→object order regardless of walk direction.
    """
    node_dicts = _parse_agtype_text(nodes_raw)
    edge_dicts = _parse_agtype_text(rels_raw)
    if not node_dicts or not edge_dicts:
        return None

    node_ids: list[str] = []
    node_names: list[str] = []
    node_types: list[str] = []
    # AGE vertex graphids (top-level ``id`` on each vertex agtype), used to decide
    # per-edge walk orientation below.  Coerced to str for stable comparison with
    # the edge ``start_id`` / ``end_id`` (which json.loads may yield as int).
    node_graphids: list[str | None] = []
    for nd in node_dicts:
        props = nd.get("properties") or {}
        eid = props.get("entity_id")
        name = props.get("canonical_name")
        etype = props.get("entity_type")
        if not (eid and name and etype):
            return None
        node_ids.append(str(eid))
        node_names.append(str(name))
        node_types.append(str(etype))
        gid = nd.get("id")
        node_graphids.append(str(gid) if gid is not None else None)

    rel_types: list[str] = []
    edge_confs: list[float] = []
    rel_ids: list[UUID] = []
    # ``edge_forward`` is aligned 1:1 with ``rel_types`` (one entry per edge).
    edge_forward: list[bool] = []
    for idx, ed in enumerate(edge_dicts):
        props = ed.get("properties") or {}
        label = ed.get("label", "")
        conf = props.get("confidence")
        if not label or conf is None:
            return None
        rel_types.append(str(label))
        try:
            edge_confs.append(float(conf))
        except (ValueError, TypeError):
            return None
        rel_id = _parse_rel_id(props)
        if rel_id is not None:
            rel_ids.append(rel_id)
        # Determine walk orientation for edge ``idx`` (connecting path node idx →
        # idx+1).  FORWARD = the edge's stored subject (``start_id``) is the node
        # we leave from (``nodes[idx].id``).  If we cannot resolve the ids (legacy
        # agtype without start_id/id) we default to forward — the pre-fix
        # behaviour — so nothing regresses.
        edge_forward.append(_edge_is_forward(ed, node_graphids, idx))

    # Consistency: edge count must be node count - 1.
    if len(rel_types) != len(node_ids) - 1:
        return None

    return RawPath(
        node_ids=tuple(node_ids),
        node_names=tuple(node_names),
        node_types=tuple(node_types),
        rel_types=tuple(rel_types),
        edge_confs=tuple(edge_confs),
        rel_ids=tuple(rel_ids),
        edge_forward=tuple(edge_forward),
    )


def _edge_is_forward(edge: dict[str, Any], node_graphids: list[str | None], idx: int) -> bool:
    """Return True if edge ``idx`` was walked subject→object (FORWARD).

    Compares the edge's stored ``start_id`` (subject) / ``end_id`` (object)
    graphids to the graphid of the path node the edge leaves from
    (``node_graphids[idx]``).  Returns:
      - True  if ``start_id == nodes[idx].id`` (walked subject→object), OR if the
        ids cannot be resolved (defensive back-compat default = forward).
      - False if ``end_id == nodes[idx].id`` (walked object→subject, REVERSE).

    The comparison is string-based: ``_parse_agtype_text`` runs the agtype through
    ``json.loads`` so graphids arrive as ints; both sides are stringified by the
    caller / here for a stable match.
    """
    start_id = edge.get("start_id")
    end_id = edge.get("end_id")
    from_gid = node_graphids[idx] if idx < len(node_graphids) else None
    if start_id is None or end_id is None or from_gid is None:
        # Legacy / unparsable payload — preserve the old node[i]→node[i+1]
        # assumption (forward) rather than guessing a reversal.
        return True
    if str(start_id) == from_gid:
        return True
    # An edge is REVERSE-walked iff its ``end_id`` is the node we are leaving.
    # Otherwise (start matches, or — for a valid path — neither endpoint matches)
    # default forward to avoid spuriously inverting a hop.  Expressed as the
    # negated condition per ruff SIM103 (behaviour-preserving).
    return str(end_id) != from_gid


# ── Adapter ────────────────────────────────────────────────────────────────────


class AgeGraphPathEngine(GraphPathEngine):
    """AGE-backed implementation of :class:`GraphPathEngine` (PLAN-0112 T-2-02).

    Args:
    ----
        session_factory: Write session factory.  AGE requires ``LOAD 'age'`` so
            traversal runs on a write session (documented R27 exception, same as
            ``CypherPathUseCase`` / ``PathDiscovery``).

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:  # type: ignore[type-arg]
        self._sf = session_factory

    async def path_exists(self, source: UUID, target: UUID, *, max_hops: int) -> int | None:
        """Return the shortest hop-count between two entities (or None).

        Staged shortest-first (BP-687): probe ``*L..L`` for L = 1..max_hops and
        return the first L that yields a row.  Existence checks never prune
        membership (we want to know if ANY connection exists).
        """
        src = _validate_uuid(source)
        tgt = _validate_uuid(target)
        if src == tgt:
            # Self is trivially "connected" at 0 hops but that is not a path.
            return None

        async with self._sf() as session:
            await _setup_age_session(session, statement_timeout_ms=_STATEMENT_TIMEOUT_MS)
            for hops in range(1, max_hops + 1):
                # Existence never prunes membership — any connection counts.
                sql = _build_vle_sql(
                    source_id=src,
                    target_id=tgt,
                    exact_hops=hops,
                    limit=1,
                )
                rows = await self._execute(session, sql)
                if rows:
                    return hops
        return None

    async def find_paths_between(
        self,
        source: UUID,
        target: UUID,
        *,
        max_hops: int,
        prune_membership: bool,
        limit: int,
    ) -> list[RawPath]:
        """Return up to ``limit`` distinct paths between two bound endpoints.

        Paths are accumulated across hop depths shortest-first: several routes at
        the shortest depth and, if fewer than ``limit`` exist there, longer
        alternative routes at deeper depths (within ``max_hops``).  Distinct by
        node-id sequence.
        """
        src = _validate_uuid(source)
        tgt = _validate_uuid(target)
        if src == tgt:
            return []
        # Pairwise allows a direct (1-hop) connection — "A is directly linked to B"
        # is a legitimate answer to "are these connected?".
        return await self._staged_discover(
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
        """Return up to ``limit`` paths radiating from a single anchor.

        The source end is bound and the target end is free.  Unlike the old
        PathDiscovery (which ran a 2-hop AND a 3-hop query and unioned them), we
        probe each depth in ascending order and accumulate paths until we hit
        ``limit`` — keeping the full multi-hop neighbourhood while never
        enumerating an explosive untyped frontier.

        ``prune_membership`` and ``min_hops`` are caller-supplied so the
        PathInsightWorker can tune them via ``Settings`` (data-coverage fix
        2026-07-16): hard membership pruning empties the result set on a sparse
        star graph, so it now defaults OFF at the worker.  ``min_hops`` stays at
        2 by default because PathInsight enforces ``hop_count >= 2`` — a 1-hop
        result would be rejected by the domain entity.
        """
        src = _validate_uuid(entity_id)
        # Clamp min_hops to >= 2: a 1-hop path is a trivial direct edge and is
        # rejected by PathInsight's ``2 <= hop_count <= 5`` invariant, so we must
        # never emit one from anchor discovery even if misconfigured.
        effective_min_hops = max(2, min_hops)
        return await self._staged_discover(
            source_id=src,
            target_id=None,
            min_hops=effective_min_hops,
            max_hops=max_hops,
            prune_membership=prune_membership,
            limit=limit,
        )

    async def _staged_discover(
        self,
        *,
        source_id: str,
        target_id: str | None,
        max_hops: int,
        prune_membership: bool,
        limit: int,
        min_hops: int = 1,
    ) -> list[RawPath]:
        """Shared staged-probe + parse loop for both pairwise and anchor modes.

        BOTH modes ACCUMULATE distinct paths ACROSS depths up to ``limit``,
        iterating hop depths ascending so the result is shortest-first
        (PLAN-0112 W4 refinement 2026-06-13).

        For PAIRWISE (target bound): we no longer stop at the first non-empty
        depth.  "How are A and B connected?" should show the VARIETY of routes —
        several distinct paths at the shortest hop length AND, if fewer than
        ``limit`` exist there, longer alternative routes at deeper depths (within
        ``max_hops``).  ``seen`` dedupes by node-id sequence so each route is
        distinct; the use case derives ``shortest_hops`` = min(hop_count) over
        the returned set, which is still the shortest depth that yielded a path.
        (The cheap shortest-only existence probe lives in ``path_exists``, which
        is unchanged and still used for the disconnected short-circuit.)

        For ANCHOR (target free): accumulate paths across depths up to ``limit``
        so the discovery returns the multi-hop neighbourhood (per-anchor insight
        discovery wants 2- and 3-hop paths, not just the nearest).
        """
        capped_limit = min(limit, _MAX_LIMIT)
        collected: list[RawPath] = []
        seen: set[tuple[str, ...]] = set()
        # ``pairwise`` is retained for logging only — both modes now accumulate
        # distinct paths across depths up to ``capped_limit`` (no early-stop).
        pairwise = target_id is not None

        async with self._sf() as session:
            await _setup_age_session(session, statement_timeout_ms=_STATEMENT_TIMEOUT_MS)
            for hops in range(max(1, min_hops), max_hops + 1):
                if len(collected) >= capped_limit:
                    break
                # We over-fetch a bit (membership-containing paths are dropped
                # post-hoc below) so a depth dominated by membership edges still
                # yields its non-membership paths.  Capped at _MAX_LIMIT.
                fetch = min(_MAX_LIMIT, max(capped_limit, capped_limit * 2))
                sql = _build_vle_sql(
                    source_id=source_id,
                    target_id=target_id,
                    exact_hops=hops,
                    limit=fetch,
                )
                rows = await self._execute(session, sql)
                for row in rows:
                    if len(collected) >= capped_limit:
                        break
                    nodes_raw = row[0] if len(row) > 0 else None
                    rels_raw = row[1] if len(row) > 1 else None
                    path = _row_to_raw_path(nodes_raw, rels_raw)
                    if path is None:
                        continue
                    # Self-loop guard: endpoints must be distinct.
                    if path.node_ids[0] == path.node_ids[-1]:
                        continue
                    # Membership pruning (FR-3) — post-hoc because AGE 1.5 cannot
                    # express it in the VLE pattern (see module docstring).
                    if prune_membership and _path_has_membership(path.rel_types):
                        continue
                    key = path.node_ids
                    if key in seen:
                        continue
                    seen.add(key)
                    collected.append(path)
                # Both pairwise and anchor modes ACCUMULATE across depths
                # (shortest-first): we continue to the next deeper depth unless
                # ``capped_limit`` is reached (checked at the top of the loop).

        logger.info(  # type: ignore[no-any-return]
            "graph_path_engine_discover_complete",
            source_id=source_id,
            target_id=target_id,
            mode="pairwise" if pairwise else "anchor",
            prune_membership=prune_membership,
            paths_found=len(collected),
            max_hops=max_hops,
        )
        return collected

    async def _execute(self, session: AsyncSession, sql: str) -> list[Any]:
        """Execute a traversal query, mapping timeout cancellations to a domain error."""
        try:
            result = await session.execute(text(sql))
            return list(result.fetchall())
        except Exception as exc:
            exc_str = str(exc).lower()
            if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
                raise CypherTimeoutError(
                    f"AGE VLE traversal exceeded {_STATEMENT_TIMEOUT_MS} ms statement_timeout",
                ) from exc
            raise


__all__ = [
    "TRAVERSABLE_RELATIONS",
    "AgeGraphPathEngine",
]
