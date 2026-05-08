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
_CYPHER_FIND_PATHS = (
    "SELECT "  # noqa: S608 — only static int literals (*2..5, LIMIT 200) embedded; entity_id is :params JSON
    "  edges_col::text, "
    "  node_types_col::text, "
    "  rel_types_col::text, "
    "  node_ids_col::text, "
    "  node_names_col::text "
    "FROM ag_catalog.cypher('worldview_graph', $$"
    "  MATCH p=(start:entity {entity_id: $id})-[*2..5]-(end:entity)"
    "  WHERE id(start) <> id(end)"
    "  RETURN"
    "    [rel IN relationships(p) | rel.confidence]      AS edges_col,"
    "    [n   IN nodes(p)         | n.entity_type]       AS node_types_col,"
    "    [rel IN relationships(p) | rel.relation_type]   AS rel_types_col,"
    "    [n   IN nodes(p)         | n.entity_id]         AS node_ids_col,"
    "    [n   IN nodes(p)         | n.canonical_name]    AS node_names_col"
    f"  ORDER BY length(p) DESC"
    f"  LIMIT {_PATH_LIMIT}"
    " $$, :params) AS ("
    "   edges_col      agtype,"
    "   node_types_col agtype,"
    "   rel_types_col  agtype,"
    "   node_ids_col   agtype,"
    "   node_names_col agtype"
    " )"
)


# ── Agtype parsing helpers ─────────────────────────────────────────────────────


def _parse_agtype_list(raw: Any) -> list[Any]:
    """Coerce an agtype column value (str / bytes / None) to a Python list."""
    if raw is None:
        return []
    text_val: str = raw.decode() if isinstance(raw, bytes | bytearray) else str(raw)
    # Strip trailing ``::agtype`` or ``::path`` type annotations if present.
    if "::" in text_val:
        text_val = text_val[: text_val.rindex("::")]
    text_val = text_val.strip()
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
                edge_confs_raw = _parse_agtype_list(row[0])
                node_types_raw = _parse_agtype_list(row[1])
                rel_types_raw = _parse_agtype_list(row[2])
                node_ids_raw = _parse_agtype_list(row[3])
                node_names_raw = _parse_agtype_list(row[4])

                if not rel_types_raw or not edge_confs_raw:
                    continue

                edge_confs = tuple(_parse_agtype_float(c) for c in edge_confs_raw)
                raw_paths.append(
                    RawPath(
                        node_ids=tuple(str(nid) for nid in node_ids_raw),
                        node_names=tuple(str(nn) for nn in node_names_raw),
                        node_types=tuple(str(nt) for nt in node_types_raw),
                        rel_types=tuple(str(rt) for rt in rel_types_raw),
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
