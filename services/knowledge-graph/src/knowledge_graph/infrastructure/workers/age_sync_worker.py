"""Worker 13F: Apache AGE Shadow Sync (PRD-0018 §6 Worker 13F).

APScheduler interval job — every 15 minutes by default.

Performs a watermark-based incremental sync from the relational tables
in ``intelligence_db`` to the Apache AGE property-graph extension:

  1. Read watermark from Valkey ``s7:age:sync:watermark`` (ISO-8601 UTC).
     Default: Unix epoch (first run syncs everything).
  2. Record ``new_watermark = utc_now()`` before syncing to avoid missing
     records written while the sync is running.
  3. Set up the AGE session: ``LOAD 'age'`` + ``SET search_path``.
  4. Sync ``canonical_entities WHERE updated_at > watermark`` → MERGE Entity vertices.
  5. Sync ``relations WHERE updated_at > watermark AND confidence > 0.1`` → MERGE edges.
  6. Sync ``temporal_events WHERE updated_at > watermark`` → MERGE TemporalEvent vertices.
  7. Sync ``entity_event_exposures WHERE created_at > watermark`` → MERGE EVENT_EXPOSES edges.
  8. Commit the DB transaction.
  9. Store ``new_watermark`` in Valkey.
  10. Emit Prometheus metrics.

Feature flag: ``KNOWLEDGE_GRAPH_CYPHER_ENABLED`` (default ``false``).
When disabled, the worker logs a debug message and returns immediately.

Edge-label security: Relation edge labels are derived from the
``canonical_type`` column (uppercase, spaces→underscores) and validated
against ``_VALID_EDGE_LABELS`` before being embedded in the Cypher string.
Unknown types are skipped and logged. This prevents Cypher-label injection.

AGE session requirement: Every DB connection that issues AGE Cypher MUST
execute ``LOAD 'age'`` and ``SET search_path = ag_catalog, public`` before
any Cypher call. This is enforced in ``_setup_age_session()``.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_age_sync_duration_seconds,
    s7_age_sync_entities_total,
    s7_age_sync_relations_total,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.config import Settings
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ─────────────────────────────────────────────────────────────────

_WATERMARK_KEY = "s7:age:sync:watermark"

# Pre-built AGE Cypher SQL strings — static graph name avoids S608 false positives.
# Data values are always passed as :params (parameterized), never string-interpolated.
_SQL_ENTITY_MERGE = (
    "SELECT * FROM ag_catalog.cypher('worldview_graph', $$"
    " MERGE (e:Entity {entity_id: $entity_id})"
    " SET e.canonical_name = $name,"
    "     e.entity_type = $type,"
    "     e.ticker = $ticker,"
    "     e.updated_at = $updated_at"
    " $$, :params) AS (result ag_catalog.agtype)"
)

_SQL_TEMPORAL_EVENT_MERGE = (
    "SELECT * FROM ag_catalog.cypher('worldview_graph', $$"
    " MERGE (t:TemporalEvent {event_id: $event_id})"
    " SET t.event_type = $event_type,"
    "     t.scope = $scope,"
    "     t.region = $region,"
    "     t.title = $title,"
    "     t.confidence = $confidence,"
    "     t.updated_at = $updated_at"
    " $$, :params) AS (result ag_catalog.agtype)"
)

_SQL_EVENT_EXPOSES_MERGE = (
    "SELECT * FROM ag_catalog.cypher('worldview_graph', $$"
    " MATCH (t:TemporalEvent {event_id: $event_id}),"
    "       (e:Entity {entity_id: $entity_id})"
    " MERGE (t)-[r:EVENT_EXPOSES {exposure_id: $exposure_id}]->(e)"
    " SET r.exposure_type = $exposure_type,"
    "     r.confidence = $confidence"
    " $$, :params) AS (result ag_catalog.agtype)"
)

# Unix epoch — used as the default watermark on first run so that the entire
# relational dataset is synced into AGE.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Pagination limits per batch
_ENTITY_BATCH = 1000
_RELATION_BATCH = 5000

# Confidence threshold — relations below this are not synced (noise filter).
_MIN_RELATION_CONFIDENCE = 0.1

# Whitelist of all valid AGE edge labels (27 relation types + EVENT_EXPOSES).
# Labels derived from ``canonical_type`` are validated here before being
# embedded in Cypher strings to prevent label injection.
_VALID_EDGE_LABELS: frozenset[str] = frozenset(
    {
        # migration 0001
        "EMPLOYS",
        "BOARD_MEMBER_OF",
        "SUBSIDIARY_OF",
        "ACQUIRED_BY",
        "LISTED_ON",
        "SUPPLIER_OF",
        "PARTNER_OF",
        "COMPETES_WITH",
        "REGULATES",
        "HEADQUARTERED_IN",
        "ANALYST_RATING",
        "MARKET_SHARE_CLAIM",
        "PRICE_TARGET",
        "EARNINGS_GUIDANCE",
        "SENTIMENT_SIGNAL",
        "CREDIT_RATING",
        "INVESTMENT_IN",
        "OWNS_STAKE_IN",
        "ISSUES_DEBT",
        "PRODUCES",
        # migration 0002
        "IS_IN_SECTOR",
        "IS_IN_INDUSTRY",
        "EARNINGS_RELEASED",
        "CORPORATE_ACTION",
        # migration 0004
        "HAS_EXECUTIVE",
        "REVENUE_FROM_COUNTRY",
        "OPERATES_IN_COUNTRY",
        # temporal event exposure
        "EVENT_EXPOSES",
    }
)


# ── Worker ────────────────────────────────────────────────────────────────────


class AgeSyncWorker:
    """Worker 13F: Watermark-based sync from relational tables to Apache AGE.

    Runs every 15 minutes via APScheduler. Skipped entirely when
    ``KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`` (default).

    Args:
        session_factory: async_sessionmaker for intelligence_db (read/write).
        valkey_client:   Connected :class:`~messaging.valkey.client.ValkeyClient`
                         instance used to store the sync watermark.
        settings:        Service settings (reads ``cypher_enabled``).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        valkey_client: ValkeyClient,
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._valkey = valkey_client
        self._settings = settings

    async def run(self) -> None:
        """Execute one full AGE shadow sync cycle."""
        if not self._settings.cypher_enabled:
            logger.debug("age_sync_worker_disabled")  # type: ignore[no-any-return]
            return

        start = time.monotonic()
        watermark = await self._get_watermark()
        new_watermark = utc_now()  # type: ignore[no-any-return]

        entities_synced = 0
        relations_synced = 0

        async with self._sf() as session:
            await _setup_age_session(session)
            entities_synced = await self._sync_entities(session, watermark)
            relations_synced = await self._sync_relations(session, watermark)
            await self._sync_temporal_events(session, watermark)
            await session.commit()

        await self._set_watermark(new_watermark)

        elapsed = time.monotonic() - start
        s7_age_sync_entities_total.inc(entities_synced)
        s7_age_sync_relations_total.inc(relations_synced)
        s7_age_sync_duration_seconds.observe(elapsed)

        logger.info(  # type: ignore[no-any-return]
            "age_sync_worker_complete",
            entities_synced=entities_synced,
            relations_synced=relations_synced,
            duration_s=round(elapsed, 2),
            watermark=new_watermark.isoformat(),
        )

    # ── Watermark ─────────────────────────────────────────────────────────────

    async def _get_watermark(self) -> datetime:
        """Read the current watermark from Valkey; return epoch if missing."""
        raw = await self._valkey.get(_WATERMARK_KEY)
        if raw is None:
            return _EPOCH
        return datetime.fromisoformat(raw)

    async def _set_watermark(self, dt: datetime) -> None:
        """Persist *dt* (ISO-8601 UTC) as the new watermark in Valkey."""
        await self._valkey.set(_WATERMARK_KEY, dt.isoformat())

    # ── Entity sync ───────────────────────────────────────────────────────────

    async def _sync_entities(self, session: AsyncSession, since: datetime) -> int:
        """MERGE canonical_entities updated since *since* as AGE Entity vertices.

        Returns the total number of vertices upserted.
        """
        total = 0
        offset = 0

        while True:
            rows = await session.execute(
                text(
                    "SELECT entity_id, canonical_name, entity_type, ticker, updated_at"
                    " FROM canonical_entities"
                    " WHERE updated_at > :since"
                    " ORDER BY updated_at ASC"
                    " LIMIT :lim OFFSET :off"
                ),
                {"since": since, "lim": _ENTITY_BATCH, "off": offset},
            )
            batch = rows.fetchall()
            if not batch:
                break

            for row in batch:
                params = {
                    "entity_id": str(row.entity_id),
                    "name": row.canonical_name,
                    "type": row.entity_type,
                    "ticker": row.ticker or "",
                    "updated_at": row.updated_at.isoformat(),
                }
                await session.execute(text(_SQL_ENTITY_MERGE), {"params": json.dumps(params)})

            total += len(batch)
            if len(batch) < _ENTITY_BATCH:
                break
            offset += _ENTITY_BATCH

        return total

    # ── Relation sync ─────────────────────────────────────────────────────────

    async def _sync_relations(self, session: AsyncSession, since: datetime) -> int:
        """MERGE relation edges updated since *since* into AGE.

        Edge labels are derived from ``canonical_type`` (uppercase, spaces→underscores)
        and validated against ``_VALID_EDGE_LABELS`` before being embedded in the
        Cypher string. Unknown types are skipped.

        Returns the total number of edges upserted.
        """
        total = 0
        offset = 0

        while True:
            rows = await session.execute(
                text(
                    "SELECT DISTINCT ON (relation_id)"
                    "       relation_id, subject_entity_id, object_entity_id,"
                    "       canonical_type, confidence, updated_at"
                    " FROM relations"
                    " WHERE updated_at > :since"
                    "   AND confidence > :min_conf"
                    " ORDER BY relation_id, updated_at ASC"
                    " LIMIT :lim OFFSET :off"
                ),
                {
                    "since": since,
                    "min_conf": _MIN_RELATION_CONFIDENCE,
                    "lim": _RELATION_BATCH,
                    "off": offset,
                },
            )
            batch = rows.fetchall()
            if not batch:
                break

            for row in batch:
                edge_label = _derive_edge_label(row.canonical_type)
                if edge_label is None:
                    logger.warning(  # type: ignore[no-any-return]
                        "age_sync_unknown_relation_type",
                        canonical_type=row.canonical_type,
                        relation_id=str(row.relation_id),
                    )
                    continue

                params = {
                    "subject_id": str(row.subject_entity_id),
                    "object_id": str(row.object_entity_id),
                    "relation_id": str(row.relation_id),
                    "confidence": float(row.confidence),
                    "updated_at": row.updated_at.isoformat(),
                }
                await session.execute(
                    text(_build_relation_merge_sql(edge_label)),
                    {"params": json.dumps(params)},
                )

            total += len(batch)
            if len(batch) < _RELATION_BATCH:
                break
            offset += _RELATION_BATCH

        return total

    # ── Temporal event sync ───────────────────────────────────────────────────

    async def _sync_temporal_events(self, session: AsyncSession, since: datetime) -> None:
        """MERGE temporal events + EVENT_EXPOSES edges updated since *since*."""
        # 1. TemporalEvent vertices
        rows = await session.execute(
            text(
                "SELECT event_id, event_type, scope, region, title, confidence, updated_at"
                " FROM temporal_events"
                " WHERE updated_at > :since"
                " ORDER BY updated_at ASC"
            ),
            {"since": since},
        )
        for row in rows.fetchall():
            params = {
                "event_id": str(row.event_id),
                "event_type": row.event_type,
                "scope": row.scope,
                "region": row.region or "",
                "title": row.title,
                "confidence": float(row.confidence),
                "updated_at": row.updated_at.isoformat(),
            }
            await session.execute(text(_SQL_TEMPORAL_EVENT_MERGE), {"params": json.dumps(params)})

        # 2. EVENT_EXPOSES edges (from entity_event_exposures created since watermark)
        exp_rows = await session.execute(
            text(
                "SELECT exposure_id, event_id, entity_id, exposure_type, confidence"
                " FROM entity_event_exposures"
                " WHERE created_at > :since"
                " ORDER BY created_at ASC"
            ),
            {"since": since},
        )
        for row in exp_rows.fetchall():
            params = {
                "event_id": str(row.event_id),
                "entity_id": str(row.entity_id),
                "exposure_id": str(row.exposure_id),
                "exposure_type": row.exposure_type,
                "confidence": float(row.confidence),
            }
            await session.execute(text(_SQL_EVENT_EXPOSES_MERGE), {"params": json.dumps(params)})


# ── Session helpers ────────────────────────────────────────────────────────────


async def _setup_age_session(session: AsyncSession) -> None:
    """Load the AGE extension and set the search path for this session.

    Must be called once per DB session before any AGE Cypher queries.
    See migration 0004 and PRD-0018 §6.4 for the rationale.
    """
    await session.execute(text("LOAD 'age'"))
    await session.execute(text("SET search_path = ag_catalog, public"))


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_relation_merge_sql(edge_label: str) -> str:
    """Build the AGE Cypher SQL for a MERGE relation edge with the given *edge_label*.

    The *edge_label* MUST be whitelist-validated before calling this function.
    It is embedded into the Cypher string (not parameterized) because AGE
    Cypher does not support dynamic edge labels via params. All data values
    (entity IDs, confidence, etc.) are passed separately as :params.
    """
    cypher = (
        "MATCH (s:Entity {entity_id: $subject_id}),"
        "      (o:Entity {entity_id: $object_id})"
        f" MERGE (s)-[r:{edge_label} {{relation_id: $relation_id}}]->(o)"
        " SET r.confidence = $confidence,"
        "     r.updated_at = $updated_at"
    )
    # edge_label is whitelist-validated; all data values in :params (parameterized)
    prefix = "SELECT * FROM ag_catalog.cypher('worldview_graph', $$"
    return prefix + cypher + "$$, :params) AS (result ag_catalog.agtype)"


def _derive_edge_label(canonical_type: str) -> str | None:
    """Derive the AGE edge label from *canonical_type*.

    Converts to uppercase and replaces spaces with underscores, then validates
    against the known whitelist. Returns ``None`` for unknown types.

    Examples:
        ``"competes_with"`` → ``"COMPETES_WITH"``
        ``"has executive"`` → ``"HAS_EXECUTIVE"``
        ``"unknown_type"``  → ``None``
    """
    label = canonical_type.upper().replace(" ", "_")
    return label if label in _VALID_EDGE_LABELS else None
