"""Apache AGE multi-hop path discovery for PathInsightWorker (T-E1-03).

Discovers 2-hop and 3-hop paths from an anchor entity using Apache AGE Cypher
with fully scalar return columns so asyncpg's prepared-statement protocol is
never asked to handle agtype list values.

Security invariants:
- ``entity_id`` is validated as a strict UUID (hex+hyphen only) via ``_UUID_RE``
  before being embedded as a string literal in the Cypher pattern.
- No other user-supplied strings are ever embedded in any Cypher or SQL query.

AGE session requirements (enforced in ``_setup_age_session``):
  1. LOAD 'age'
  2. SET search_path = ag_catalog, public

Design note — BP-SA5-003 (2026-05-10):
  asyncpg's extended-query (prepared-statement) protocol fails for AGE Cypher
  queries that return agtype *list* values such as ``relationships(p)`` and
  ``nodes(p)``.  AGE raises "agtype argument must resolve to a scalar value"
  at bind time because the PREPARE phase cannot resolve the agtype OID for
  list-typed columns.  This error persists even with ``statement_cache_size=0``
  and ``set_type_codec``.

  Fix: use explicit undirected pattern-matching (2-hop and 3-hop) that returns
  only scalar agtype properties (entity_id, canonical_name, entity_type,
  relation type, confidence) rather than the opaque list functions.  The two
  queries are run separately and their results assembled into ``RawPath``
  objects in Python.  This avoids the agtype list serialisation issue entirely.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import text

from knowledge_graph.domain.errors import KnowledgeGraphError
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# UUID validation pattern — guards entity_id before it is embedded in Cypher.
# UUIDs contain only [0-9a-fA-F-] so no SQL/Cypher injection is possible.
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

logger = get_logger(__name__)  # type: ignore[no-any-return]

# Statement timeout for the AGE multi-hop query — 60s per design spec (T-E1-03).
_DISCOVERY_TIMEOUT_SECONDS = 60.0
_STATEMENT_TIMEOUT_MS = "60000"

# Hard cap on returned paths per hop-length query.
_PATH_LIMIT = 200


class PathDiscoveryTimeoutError(KnowledgeGraphError):
    """Raised when the AGE path discovery query exceeds ``_DISCOVERY_TIMEOUT_SECONDS``."""

    def __init__(self, entity_id: UUID) -> None:
        super().__init__(f"PathDiscovery timed out after {_DISCOVERY_TIMEOUT_SECONDS}s for entity {entity_id}")
        self.entity_id = entity_id


@dataclass(frozen=True)
class RawPath:
    """A single multi-hop path returned by the AGE Cypher query.

    All data required for scoring is pre-extracted so Python code never
    needs to re-query the DB.
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


# ── AGE session setup ─────────────────────────────────────────────────────────


async def _setup_age_session(session: AsyncSession) -> None:
    """Load AGE extension and set the search_path for path discovery.

    Must be called before any AGE Cypher query on a fresh connection.
    Mirrors the pattern in AgeSyncWorker and CypherPathUseCase.
    """
    await session.execute(text("LOAD 'age'"))
    await session.execute(text("SET search_path = ag_catalog, public"))


# ── Scalar-based Cypher SQL builders ─────────────────────────────────────────
#
# BP-SA5-003 (2026-05-10): asyncpg prepared-statement protocol fails for AGE
# queries that return agtype LIST values (relationships(p), nodes(p)) with:
#   "agtype argument must resolve to a scalar value"
# This error persists even with statement_cache_size=0 and set_type_codec.
#
# Fix: explicit 2-hop and 3-hop MATCH patterns that return individual scalar
# agtype columns (entity_id, canonical_name, entity_type, type(r), r.confidence).
# asyncpg handles scalar agtype columns correctly.
#
# BP-SA5-001 (2026-05-10): use lowercase ``entity`` label to match the
# canonical label written by AgeSyncWorker.
#
# Security: entity_id is a UUID literal embedded after strict _UUID_RE
# validation — UUIDs contain only [0-9a-fA-F-], no SQL metacharacters.


def _build_2hop_sql(entity_id: str) -> str:
    """Build the 2-hop undirected path query returning scalar columns."""
    return (
        "SELECT "  # noqa: S608 — only UUID-validated hex literal embedded; no user input
        "  n0_id::text, n0_name::text, n0_type::text,"
        "  r1_type::text, r1_conf::text,"
        "  n1_id::text, n1_name::text, n1_type::text,"
        "  r2_type::text, r2_conf::text,"
        "  n2_id::text, n2_name::text, n2_type::text"
        " FROM ag_catalog.cypher('worldview_graph', $$"
        f"  MATCH (n0:entity {{entity_id: '{entity_id}'}})-[r1]-(n1:entity)-[r2]-(n2:entity)"
        "   WHERE id(n0) <> id(n2)"
        "   RETURN"
        "     n0.entity_id, n0.canonical_name, n0.entity_type,"
        "     type(r1), r1.confidence,"
        "     n1.entity_id, n1.canonical_name, n1.entity_type,"
        "     type(r2), r2.confidence,"
        "     n2.entity_id, n2.canonical_name, n2.entity_type"
        f"  LIMIT {_PATH_LIMIT}"
        " $$) AS ("
        "   n0_id agtype, n0_name agtype, n0_type agtype,"
        "   r1_type agtype, r1_conf agtype,"
        "   n1_id agtype, n1_name agtype, n1_type agtype,"
        "   r2_type agtype, r2_conf agtype,"
        "   n2_id agtype, n2_name agtype, n2_type agtype"
        " )"
    )


def _build_3hop_sql(entity_id: str) -> str:
    """Build the 3-hop undirected path query returning scalar columns."""
    # Use a smaller LIMIT for 3-hop to stay under the total 200 path cap.
    limit_3hop = _PATH_LIMIT // 2
    return (
        "SELECT "  # noqa: S608 — only UUID-validated hex literal embedded; no user input
        "  n0_id::text, n0_name::text, n0_type::text,"
        "  r1_type::text, r1_conf::text,"
        "  n1_id::text, n1_name::text, n1_type::text,"
        "  r2_type::text, r2_conf::text,"
        "  n2_id::text, n2_name::text, n2_type::text,"
        "  r3_type::text, r3_conf::text,"
        "  n3_id::text, n3_name::text, n3_type::text"
        " FROM ag_catalog.cypher('worldview_graph', $$"
        f"  MATCH (n0:entity {{entity_id: '{entity_id}'}})-[r1]-(n1:entity)-[r2]-(n2:entity)-[r3]-(n3:entity)"
        "   WHERE id(n0) <> id(n3) AND id(n1) <> id(n3)"
        "   RETURN"
        "     n0.entity_id, n0.canonical_name, n0.entity_type,"
        "     type(r1), r1.confidence,"
        "     n1.entity_id, n1.canonical_name, n1.entity_type,"
        "     type(r2), r2.confidence,"
        "     n2.entity_id, n2.canonical_name, n2.entity_type,"
        "     type(r3), r3.confidence,"
        "     n3.entity_id, n3.canonical_name, n3.entity_type"
        f"  LIMIT {limit_3hop}"
        " $$) AS ("
        "   n0_id agtype, n0_name agtype, n0_type agtype,"
        "   r1_type agtype, r1_conf agtype,"
        "   n1_id agtype, n1_name agtype, n1_type agtype,"
        "   r2_type agtype, r2_conf agtype,"
        "   n2_id agtype, n2_name agtype, n2_type agtype,"
        "   r3_type agtype, r3_conf agtype,"
        "   n3_id agtype, n3_name agtype, n3_type agtype"
        " )"
    )


def _validate_and_embed_entity_id(entity_id: UUID) -> str:
    """Validate UUID format and return the string for Cypher embedding.

    BP-SA5-003: entity_id is embedded directly in the Cypher string because
    asyncpg prepared-statement protocol rejects agtype list output columns.
    Strict UUID validation ensures only [0-9a-fA-F-] characters are embedded
    — no SQL metacharacters, no injection possible.
    """
    eid_str = str(entity_id)
    if not _UUID_RE.match(eid_str):
        raise ValueError(f"entity_id is not a valid UUID: {eid_str!r}")
    return eid_str


# ── Agtype scalar parsing ──────────────────────────────────────────────────────


def _as_str(val: Any) -> str:
    """Coerce an agtype scalar column value to a Python str.

    asyncpg returns scalar agtype columns as Python str when the outer SQL
    applies a ``::text`` cast.  Without the cast the value is still a str
    in most SA 2.0/asyncpg configurations.  Strip surrounding quotes that
    AGE occasionally adds for string scalars.
    """
    if val is None:
        return ""
    s = str(val)
    # Strip trailing agtype type annotations (e.g. '::text', '::agtype')
    if "::" in s:
        s = s[: s.rindex("::")]
    # Strip surrounding double-quotes that AGE adds for string scalars
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s


def _as_float(val: Any) -> float:
    """Coerce an agtype scalar confidence value to a Python float."""
    s = _as_str(val)
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ── Row parsers ───────────────────────────────────────────────────────────────


def _parse_2hop_row(row: Any) -> RawPath | None:
    """Parse a single 2-hop query result row into a RawPath.

    Row layout (13 columns, all ::text):
      0  n0_id,  1  n0_name,  2  n0_type,
      3  r1_type, 4  r1_conf,
      5  n1_id,  6  n1_name,  7  n1_type,
      8  r2_type, 9  r2_conf,
      10 n2_id,  11 n2_name,  12 n2_type
    """
    try:
        node_ids = (_as_str(row[0]), _as_str(row[5]), _as_str(row[10]))
        node_names = (_as_str(row[1]), _as_str(row[6]), _as_str(row[11]))
        node_types = (_as_str(row[2]), _as_str(row[7]), _as_str(row[12]))
        rel_types = (_as_str(row[3]), _as_str(row[8]))
        edge_confs = (_as_float(row[4]), _as_float(row[9]))
        if not all(node_ids) or not all(rel_types):
            return None
        return RawPath(
            node_ids=node_ids,
            node_names=node_names,
            node_types=node_types,
            rel_types=rel_types,
            edge_confs=edge_confs,
        )
    except Exception:
        return None


def _parse_3hop_row(row: Any) -> RawPath | None:
    """Parse a single 3-hop query result row into a RawPath.

    Row layout (18 columns, all ::text):
      0  n0_id,  1  n0_name,  2  n0_type,
      3  r1_type, 4  r1_conf,
      5  n1_id,  6  n1_name,  7  n1_type,
      8  r2_type, 9  r2_conf,
      10 n2_id,  11 n2_name,  12 n2_type,
      13 r3_type, 14 r3_conf,
      15 n3_id,  16 n3_name,  17 n3_type
    """
    try:
        node_ids = (_as_str(row[0]), _as_str(row[5]), _as_str(row[10]), _as_str(row[15]))
        node_names = (_as_str(row[1]), _as_str(row[6]), _as_str(row[11]), _as_str(row[16]))
        node_types = (_as_str(row[2]), _as_str(row[7]), _as_str(row[12]), _as_str(row[17]))
        rel_types = (_as_str(row[3]), _as_str(row[8]), _as_str(row[13]))
        edge_confs = (_as_float(row[4]), _as_float(row[9]), _as_float(row[14]))
        if not all(node_ids) or not all(rel_types):
            return None
        return RawPath(
            node_ids=node_ids,
            node_names=node_names,
            node_types=node_types,
            rel_types=rel_types,
            edge_confs=edge_confs,
        )
    except Exception:
        return None


# ── Main discovery class ───────────────────────────────────────────────────────


class PathDiscovery:
    """Discover multi-hop paths from an anchor entity via Apache AGE.

    Runs two separate Cypher queries (2-hop and 3-hop) using explicit scalar
    column returns to avoid the asyncpg agtype list protocol incompatibility
    (BP-SA5-003).  Results are assembled into :class:`RawPath` objects.

    Args:
    ----
        session_factory: Write session factory (AGE requires LOAD 'age' —
                         same restriction as CypherPathUseCase per R27 exception).

    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:  # type: ignore[type-arg]
        self._sf = session_factory

    async def find_paths_for_anchor(self, entity_id: UUID) -> list[RawPath]:
        """Return up to 200 raw paths from ``entity_id`` with hops 2-3.

        Runs two queries (2-hop, 3-hop) in the same AGE session and combines
        the results.  Deduplicates paths by their node_ids tuple to avoid
        returning the same structural path twice from the undirected queries.

        Raises:
        ------
            PathDiscoveryTimeoutError: if the AGE queries exceed 60 seconds.

        Security: ``entity_id`` is validated as a strict UUID (hex+hyphen only)
                  before being embedded in the Cypher literals.  See BP-SA5-003.
        """
        eid_str = _validate_and_embed_entity_id(entity_id)
        sql_2hop = _build_2hop_sql(eid_str)
        sql_3hop = _build_3hop_sql(eid_str)

        raw_paths: list[RawPath] = []
        seen: set[tuple[str, ...]] = set()

        async with self._sf() as session:
            await _setup_age_session(session)
            await session.execute(text(f"SET LOCAL statement_timeout = '{_STATEMENT_TIMEOUT_MS}'"))

            try:
                # Run both queries within the AGE-loaded session.
                result_2 = await asyncio.wait_for(
                    session.execute(text(sql_2hop)),
                    timeout=_DISCOVERY_TIMEOUT_SECONDS / 2,
                )
                rows_2 = result_2.fetchall()

                result_3 = await asyncio.wait_for(
                    session.execute(text(sql_3hop)),
                    timeout=_DISCOVERY_TIMEOUT_SECONDS / 2,
                )
                rows_3 = result_3.fetchall()

            except TimeoutError as exc:
                logger.warning(  # type: ignore[no-any-return]
                    "path_discovery_timeout",
                    entity_id=str(entity_id),
                    timeout_s=_DISCOVERY_TIMEOUT_SECONDS,
                )
                raise PathDiscoveryTimeoutError(entity_id) from exc
            except Exception as exc:
                exc_str = str(exc).lower()
                if "timeout" in exc_str or "canceling" in exc_str or "statement_timeout" in exc_str:
                    logger.warning(  # type: ignore[no-any-return]
                        "path_discovery_timeout",
                        entity_id=str(entity_id),
                        timeout_s=_DISCOVERY_TIMEOUT_SECONDS,
                    )
                    raise PathDiscoveryTimeoutError(entity_id) from exc
                raise

        # Parse 2-hop rows
        for row in rows_2:
            path = _parse_2hop_row(row)
            if path is None:
                continue
            key = path.node_ids
            if key not in seen:
                seen.add(key)
                raw_paths.append(path)

        # Parse 3-hop rows
        for row in rows_3:
            path = _parse_3hop_row(row)
            if path is None:
                continue
            key = path.node_ids
            if key not in seen:
                seen.add(key)
                raw_paths.append(path)

        logger.info(  # type: ignore[no-any-return]
            "path_discovery_complete",
            entity_id=str(entity_id),
            paths_found=len(raw_paths),
            paths_2hop=len(rows_2),
            paths_3hop=len(rows_3),
        )
        return raw_paths
