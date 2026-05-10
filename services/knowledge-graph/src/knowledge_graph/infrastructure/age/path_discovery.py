"""Apache AGE multi-hop path discovery for PathInsightWorker (T-E1-03).

Uses a parameterized Cypher query to find all paths of length 2-5 from an
anchor entity.  Entity IDs are ALWAYS passed as ``$id`` Cypher parameters
— never string-interpolated (injection guard).

AGE session requirements (enforced in ``_setup_age_session``):
  1. LOAD 'age'
  2. SET search_path = ag_catalog, "$user", public

Security invariant: ``entity_id`` is parameterized via the AGE params JSON
dict as ``$id``.  No user-supplied string is ever embedded in the Cypher
pattern itself (only the statically validated integer literal ``2..5`` is
embedded for the hop range).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.domain.errors import KnowledgeGraphError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Statement timeout for the AGE multi-hop query — 60s per design spec (T-E1-03).
_DISCOVERY_TIMEOUT_SECONDS = 60.0
_STATEMENT_TIMEOUT_MS = "60000"

# Hard cap on returned paths (Cypher LIMIT) to avoid runaway result sets.
_PATH_LIMIT = 200


class PathDiscoveryTimeoutError(KnowledgeGraphError):
    """Raised when the AGE path discovery query exceeds ``_DISCOVERY_TIMEOUT_SECONDS``."""

    def __init__(self, entity_id: UUID) -> None:
        super().__init__(f"PathDiscovery timed out after {_DISCOVERY_TIMEOUT_SECONDS}s for entity {entity_id}")
        self.entity_id = entity_id


@dataclass(frozen=True)
class RawPath:
    """A single multi-hop path returned by the AGE Cypher query.

    All data required for scoring is pre-extracted by the Cypher RETURN clause
    so Python code never needs to re-query the DB.
    """

    # entity_id values for each node in order (start → ... → end)
    node_ids: tuple[str, ...]
    # canonical_name of each node (same order as node_ids)
    node_names: tuple[str, ...]
    # entity_type of each node
    node_types: tuple[str, ...]
    # relation_type label of each edge (len = len(node_ids) - 1)
    rel_types: tuple[str, ...]
    # confidence of each edge (same order as rel_types)
    edge_confs: tuple[float, ...]

    @property
    def hop_count(self) -> int:
        return len(self.rel_types)


# ── AGE session helpers ────────────────────────────────────────────────────────


async def _setup_age_session(session: AsyncSession) -> None:
    """Load AGE extension and set the search_path for path discovery.

    Must be called before any AGE Cypher query on a fresh connection.
    Mirrors the pattern in AgeSyncWorker and CypherPathUseCase.
    """
    await session.execute(text("LOAD 'age'"))
    await session.execute(text('SET search_path = ag_catalog, "$user", public'))


# ── Cypher SQL template ────────────────────────────────────────────────────────

# The Cypher pattern ``*2..5`` is a static integer range literal — safe to embed.
# Entity IDs are passed via the ``$id`` Cypher parameter (never f-strung in).
#
# BP-442 (2026-05-10): ``end`` is a reserved keyword in Apache AGE / PostgreSQL.
# Using ``end`` as a node alias causes PostgresSyntaxError every run, which was
# preventing the path-insight-worker from computing ANY paths and causing
# repeated fatal restarts (6 restarts visible in docker inspect).
# Fix: renamed the destination node alias from ``end`` → ``tgt`` throughout.
#
# BP-SA1-003 (2026-05-10): Apache AGE does NOT support the openCypher
# list-comprehension pipe syntax ``[rel IN relationships(p) | rel.confidence]``.
# This caused a hard PostgresSyntaxError ("syntax error at or near |") for every
# path-insight job, leaving path_insight_jobs permanently failed.
#
# Fix: return ``relationships(p)`` and ``nodes(p)`` as raw agtype arrays.  The
# agtype JSON objects carry their full ``properties`` dict (e.g.
# ``{"confidence": 0.9, "relation_type": "PARTNER_OF"}``).  The Python parser
# (_parse_agtype_object_list) extracts the required fields post-query so no
# list-comprehension syntax is needed in the Cypher at all.
_CYPHER_FIND_PATHS = (
    "SELECT "  # noqa: S608 — only static int literals (*2..5, LIMIT 200) embedded; entity_id is :params JSON
    "  rels_col::text, "
    "  nodes_col::text "
    "FROM ag_catalog.cypher('worldview_graph', $$"
    "  MATCH p=(start:entity {entity_id: $id})-[*2..5]-(tgt:entity)"
    "  WHERE id(start) <> id(tgt)"
    "  RETURN"
    "    relationships(p) AS rels_col,"
    "    nodes(p)         AS nodes_col"
    f"  ORDER BY length(p) DESC"
    f"  LIMIT {_PATH_LIMIT}"
    " $$, :params) AS ("
    "   rels_col  agtype,"
    "   nodes_col agtype"
    " )"
)


# ── Agtype parsing helpers ─────────────────────────────────────────────────────


def _strip_agtype_suffix(text_val: str) -> str:
    """Remove trailing ``::agtype``, ``::edge``, ``::vertex``, etc. type annotations."""
    if "::" in text_val:
        text_val = text_val[: text_val.rindex("::")]
    return text_val.strip()


def _parse_agtype_list(raw: Any) -> list[Any]:
    """Coerce an agtype column value (str / bytes / None) to a Python list."""
    if raw is None:
        return []
    text_val: str = raw.decode() if isinstance(raw, bytes | bytearray) else str(raw)
    text_val = _strip_agtype_suffix(text_val)
    if not text_val or text_val == "null":
        return []
    return json.loads(text_val)  # type: ignore[no-any-return]


def _parse_agtype_float(v: Any) -> float:
    """Extract a float from an agtype scalar — may arrive as string with suffix."""
    if v is None:
        return 0.0
    s = str(v)
    if "::" in s:
        s = s[: s.rindex("::")]
    try:
        return float(s.strip())
    except (ValueError, TypeError):
        return 0.0


def _parse_agtype_object(raw: Any) -> dict[str, Any]:
    """Parse a single agtype object (edge or vertex) to a Python dict.

    AGE serialises edges as:
      {"id": ..., "label": "PARTNER_OF", "properties": {"confidence": 0.9, ...}}::edge
    and vertices as:
      {"id": ..., "label": "entity", "properties": {"entity_id": "...", ...}}::vertex

    The ``::edge`` / ``::vertex`` suffix is stripped before JSON parsing.
    Returns an empty dict on any parse error.
    """
    if raw is None:
        return {}
    text_val: str = raw.decode() if isinstance(raw, bytes | bytearray) else str(raw)
    text_val = _strip_agtype_suffix(text_val)
    if not text_val or text_val == "null":
        return {}
    try:
        return json.loads(text_val)  # type: ignore[no-any-return]
    except (ValueError, TypeError):
        return {}


def _parse_agtype_object_list(raw: Any) -> list[dict[str, Any]]:
    """Parse an agtype array of edge/vertex objects to a list of Python dicts.

    BP-SA1-003: used to extract per-element properties from ``relationships(p)``
    and ``nodes(p)`` return values instead of using the unsupported ``|`` pipe
    list-comprehension syntax.
    """
    items = _parse_agtype_list(raw)
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            result.append(item)
        else:
            # Item may still carry ``::edge`` suffix as a bare string — parse it.
            result.append(_parse_agtype_object(item))
    return result


# ── Main discovery class ───────────────────────────────────────────────────────


class PathDiscovery:
    """Discover multi-hop paths from an anchor entity via Apache AGE.

    Args:
    ----
        session_factory: Write session factory (AGE requires LOAD 'age' — same
                         restriction as CypherPathUseCase per R27 exception).

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:  # type: ignore[type-arg]
        self._sf = session_factory

    async def find_paths_for_anchor(self, entity_id: UUID) -> list[RawPath]:
        """Return up to 200 raw paths from ``entity_id`` with hops 2-5.

        Raises:
        ------
            PathDiscoveryTimeoutError: if the AGE query exceeds 60 seconds.

        Security: ``entity_id`` is passed as ``$id`` in the Cypher params JSON,
                  never string-interpolated into the query.
        """
        # Params JSON for AGE — entity_id as a string scalar value.
        # AGE passes Cypher params as a JSON object; the driver serialises
        # it automatically when we bind :params as a string.
        params_json = json.dumps({"id": str(entity_id)})

        async with self._sf() as session:
            await _setup_age_session(session)

            # Statement-level timeout prevents the long-running AGE query from
            # blocking the session indefinitely.
            await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))

            try:
                result = await asyncio.wait_for(
                    session.execute(
                        text(_CYPHER_FIND_PATHS),
                        {"params": params_json},
                    ),
                    timeout=_DISCOVERY_TIMEOUT_SECONDS,
                )
            except (TimeoutError, Exception) as exc:
                exc_str = str(exc).lower()
                # Catch both asyncio timeout and Postgres statement_timeout
                if "timeout" in exc_str or isinstance(exc, asyncio.TimeoutError):
                    logger.warning(  # type: ignore[no-any-return]
                        "path_discovery_timeout",
                        entity_id=str(entity_id),
                        timeout_s=_DISCOVERY_TIMEOUT_SECONDS,
                    )
                    raise PathDiscoveryTimeoutError(entity_id) from exc
                raise

            rows = result.fetchall()

        raw_paths: list[RawPath] = []
        for row in rows:
            try:
                # BP-SA1-003: row now has 2 columns — rels_col and nodes_col.
                # Each element is a full agtype object with a ``properties`` dict.
                edge_objects = _parse_agtype_object_list(row[0])
                node_objects = _parse_agtype_object_list(row[1])

                if not edge_objects or not node_objects:
                    continue

                # Extract per-edge fields from the ``properties`` sub-dict.
                # AGE edge object shape: {"id": ..., "label": "...", "properties": {...}}
                edge_props = [obj.get("properties") or {} for obj in edge_objects]
                edge_confs = tuple(_parse_agtype_float(ep.get("confidence")) for ep in edge_props)
                rel_types = tuple(
                    str(ep.get("relation_type") or obj.get("label") or "")
                    for ep, obj in zip(edge_props, edge_objects, strict=False)
                )

                # Extract per-node fields from the ``properties`` sub-dict.
                # AGE vertex shape: {"id": ..., "label": "...", "properties": {...}}
                node_props = [obj.get("properties") or {} for obj in node_objects]
                node_ids = tuple(str(np.get("entity_id") or "") for np in node_props)
                node_names = tuple(str(np.get("canonical_name") or "") for np in node_props)
                node_types = tuple(str(np.get("entity_type") or "") for np in node_props)

                if not rel_types or not edge_confs:
                    continue

                raw_paths.append(
                    RawPath(
                        node_ids=node_ids,
                        node_names=node_names,
                        node_types=node_types,
                        rel_types=rel_types,
                        edge_confs=edge_confs,
                    )
                )
            except Exception:
                # Skip malformed rows — never drop the whole batch.
                logger.warning(  # type: ignore[no-any-return]
                    "path_discovery_row_parse_error",
                    entity_id=str(entity_id),
                    exc_info=True,
                )

        logger.info(  # type: ignore[no-any-return]
            "path_discovery_complete",
            entity_id=str(entity_id),
            paths_found=len(raw_paths),
        )
        return raw_paths
