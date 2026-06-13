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
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_age_sync_duration_seconds,
    s7_age_sync_entities_total,
    s7_age_sync_relations_total,
    s7_node_degree_refresh_seconds,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.application.ports.node_degree_repository import (
        NodeDegreeRepositoryPort,
    )
    from knowledge_graph.config import Settings
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ─────────────────────────────────────────────────────────────────

_WATERMARK_KEY = "s7:age:sync:watermark"

# Pre-built AGE Cypher SQL strings — static graph name avoids S608 false positives.
# Data values are always passed as :params (parameterized), never string-interpolated.
_SQL_ENTITY_MERGE = (
    # BP-SA5-001 (2026-05-10): AGE label MUST be lowercase ``entity`` to match
    # the label used by PathDiscovery (path_discovery.py) and the existing
    # hand-seeded test nodes.  Using ``Entity`` (capital) caused a label split
    # where sync wrote to one label space and path_discovery queried another,
    # leaving path_insight_jobs returning zero paths for all hub entities.
    "SELECT * FROM ag_catalog.cypher('worldview_graph', $$"
    " MERGE (e:entity {entity_id: $entity_id})"
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
    # BP-SA5-001: entity node uses lowercase ``entity`` label to match the
    # canonical label used throughout (sync + path_discovery).
    "SELECT * FROM ag_catalog.cypher('worldview_graph', $$"
    " MATCH (t:TemporalEvent {event_id: $event_id}),"
    "       (e:entity {entity_id: $entity_id})"
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
        # theme exposure (added in migration 0029 / PLAN-0076)
        "EXPOSED_TO_THEME",
    },
)


# ── Worker ────────────────────────────────────────────────────────────────────


class AgeSyncWorker:
    """Worker 13F: Watermark-based sync from relational tables to Apache AGE.

    Runs every 15 minutes via APScheduler. Skipped entirely when
    ``KNOWLEDGE_GRAPH_CYPHER_ENABLED=false`` (default).

    Args:
    ----
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
        read_session_factory: Any = None,
        node_degree_repo_factory: Callable[[AsyncSession], NodeDegreeRepositoryPort] | None = None,
    ) -> None:
        self._sf = session_factory
        # PLAN-0112 W3 (T-3-02): after each AGE-sync cycle the worker recomputes
        # the per-vertex degree (powering the weirdness scorer's unexpectedness
        # term) and upserts node_degree + graph_stats.  The factory builds a
        # NodeDegreeRepositoryPort from a session (R25: worker depends on the ABC,
        # not the concrete repo).  When None (legacy/tests) the refresh is skipped.
        self._node_degree_repo_factory = node_degree_repo_factory
        # DEF-034 (Wave B-5): AGE Cypher MERGE statements (which are writes
        # against intelligence_db) and the entity/relation SELECTs all share
        # one session in :meth:`run` because every AGE write requires
        # ``LOAD 'age'`` + ``SET search_path`` to be loaded on that same
        # session.  The session therefore has to be a write session.  We
        # accept ``read_session_factory`` for API consistency and store it for
        # any future purely-read diagnostic queries; current behaviour is
        # unchanged.
        # Read factory wired for future use; current path is atomic read+write
        # because AGE Cypher MERGE writes share the session with the SELECTs.
        self._read_session_factory: Any = read_session_factory if read_session_factory is not None else session_factory
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

        watermark_age_s = round((new_watermark - watermark).total_seconds())
        logger.info(  # type: ignore[no-any-return]
            "age_sync_worker_start",
            watermark=watermark.isoformat(),
            watermark_age_s=watermark_age_s,
            is_full_resync=watermark.year == 1970,
        )

        entities_synced = 0
        relations_synced = 0
        temporal_events_synced = 0

        async with self._sf() as session:
            await _setup_age_session(session)
            # F-016: intermediate commits after each batch type so that a failure
            # mid-sync does not roll back all previously completed work. AGE MERGE
            # is idempotent (re-run is safe), so partial commits are correct here.
            entities_synced = await self._sync_entities(session, watermark)
            await session.commit()
            await _setup_age_session(session)  # reload AGE after commit
            relations_synced = await self._sync_relations(session, watermark)
            await session.commit()
            await _setup_age_session(session)
            temporal_events_synced = await self._sync_temporal_events(session, watermark)
            await session.commit()

        await self._set_watermark(new_watermark)

        # PLAN-0112 W3 (T-3-02): refresh node_degree + graph_stats from the
        # just-synced AGE graph so the weirdness scorer's unexpectedness term has
        # up-to-date degrees.  Fail-open: a refresh error must never abort the
        # sync cycle (the previous degree snapshot stays usable until next run).
        await self._refresh_node_degrees()

        elapsed = time.monotonic() - start
        s7_age_sync_entities_total.inc(entities_synced)
        s7_age_sync_relations_total.inc(relations_synced)
        s7_age_sync_duration_seconds.observe(elapsed)

        # Log a warning when nothing was synced — may indicate the relational
        # tables are empty or the watermark is ahead of all rows.
        if entities_synced == 0 and relations_synced == 0 and temporal_events_synced == 0:
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_worker_no_changes",
                watermark=watermark.isoformat(),
                duration_s=round(elapsed, 2),
                message="all AGE MERGE operations were no-ops — relational tables may be empty or watermark is stale",
            )

        logger.info(  # type: ignore[no-any-return]
            "age_sync_worker_complete",
            entities_synced=entities_synced,
            relations_synced=relations_synced,
            temporal_events_synced=temporal_events_synced,
            duration_s=round(elapsed, 2),
            new_watermark=new_watermark.isoformat(),
        )

    # ── node_degree refresh (PLAN-0112 W3, T-3-02) ─────────────────────────────

    async def _refresh_node_degrees(self) -> None:
        """Recompute + upsert node_degree/graph_stats from the synced AGE graph.

        Fail-open: any error is logged and swallowed so a degree-refresh failure
        never aborts the AGE-sync cycle (BP-540/541 — degrade gracefully rather
        than block the pipeline).  Emits ``s7_node_degree_refresh_seconds``.
        """
        if self._node_degree_repo_factory is None:
            logger.debug("node_degree_refresh_skipped_no_factory")  # type: ignore[no-any-return]
            return
        refresh_start = time.monotonic()
        try:
            async with self._sf() as session:
                # PLAN-0112 W3 live-QA fix: the degree refresh is now PURE SQL over
                # the raw AGE storage tables (``_ag_label_edge`` + ``entity``),
                # using fully-qualified ``ag_catalog`` agtype helpers — it needs
                # NEITHER ``LOAD 'age'`` NOR any Cypher (the old Cypher ``-[r]-``
                # enumeration timed out at 50 s on the live graph).  We keep the
                # serial-plan GUC so the scan stays off the parallel path.
                await session.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
                repo = self._node_degree_repo_factory(session)
                stats = await repo.refresh_from_age()
                await session.commit()
            s7_node_degree_refresh_seconds.observe(time.monotonic() - refresh_start)
            logger.info(  # type: ignore[no-any-return]
                "node_degree_refresh_complete",
                total_edges=stats.total_edges,
                total_meaningful_edges=stats.total_meaningful_edges,
                max_degree=stats.max_degree,
                duration_s=round(time.monotonic() - refresh_start, 3),
            )
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "node_degree_refresh_error",
                exc_info=True,
            )

    # ── Watermark ─────────────────────────────────────────────────────────────

    async def _get_watermark(self) -> datetime:
        """Read the current watermark from Valkey; return epoch on missing or error.

        Falls back to epoch (full re-sync) on Valkey unavailability — AGE MERGE
        is idempotent so re-syncing already-synced data is safe.
        """
        try:
            raw = await self._valkey.get(_WATERMARK_KEY)
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_watermark_read_failed",
                message="Valkey unavailable; falling back to epoch watermark (full re-sync)",
                exc_info=True,
            )
            return _EPOCH
        if raw is None:
            return _EPOCH
        result = datetime.fromisoformat(raw)
        # Ensure the parsed watermark is always timezone-aware (UTC).
        if result.tzinfo is None:
            return result.replace(tzinfo=UTC)
        return result

    async def _set_watermark(self, dt: datetime) -> None:
        """Persist *dt* (ISO-8601 UTC) as the new watermark in Valkey.

        Logs and swallows Valkey errors — on next run the watermark falls
        back to epoch (full re-sync), which is safe since AGE MERGE is idempotent.
        """
        try:
            await self._valkey.set(_WATERMARK_KEY, dt.isoformat())
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_watermark_write_failed",
                message="Valkey unavailable; watermark not persisted — next run will re-sync from epoch",
                exc_info=True,
            )

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
                    " LIMIT :lim OFFSET :off",
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
            # Note: DISTINCT ON removed — relation_id is the PK, each row is unique.
            # ORDER BY updated_at ASC enables stable pagination across runs.
            rows = await session.execute(
                text(
                    "SELECT relation_id, subject_entity_id, object_entity_id,"
                    "       canonical_type, confidence, updated_at"
                    " FROM relations"
                    " WHERE updated_at > :since"
                    "   AND confidence > :min_conf"
                    " ORDER BY updated_at ASC, relation_id ASC"
                    " LIMIT :lim OFFSET :off",
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

    async def _sync_temporal_events(self, session: AsyncSession, since: datetime) -> int:
        """MERGE temporal events + EVENT_EXPOSES edges updated/created since *since*.

        Uses paginated fetches (same pattern as _sync_entities) to bound memory
        usage on large or first-run backlogs.

        Returns the total number of TemporalEvent vertices upserted.
        """
        event_batch = 2000
        exposure_batch = 5000
        events_total = 0
        exposures_total = 0

        # 1. TemporalEvent vertices — paginated
        offset = 0
        while True:
            rows = await session.execute(
                text(
                    "SELECT event_id, event_type, scope, region, title, confidence, updated_at"
                    " FROM temporal_events"
                    " WHERE updated_at > :since"
                    " ORDER BY updated_at ASC, event_id ASC"
                    " LIMIT :lim OFFSET :off",
                ),
                {"since": since, "lim": event_batch, "off": offset},
            )
            batch = rows.fetchall()
            if not batch:
                break
            for row in batch:
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
            events_total += len(batch)
            if len(batch) < event_batch:
                break
            offset += event_batch

        # 2. EVENT_EXPOSES edges — paginated
        # entity_event_exposures is immutable after creation (DO NOTHING on conflict),
        # so created_at is the correct watermark column (no updated_at exists).
        offset = 0
        while True:
            exp_rows = await session.execute(
                text(
                    "SELECT exposure_id, event_id, entity_id, exposure_type, confidence"
                    " FROM entity_event_exposures"
                    " WHERE created_at > :since"
                    " ORDER BY created_at ASC, exposure_id ASC"
                    " LIMIT :lim OFFSET :off",
                ),
                {"since": since, "lim": exposure_batch, "off": offset},
            )
            batch = exp_rows.fetchall()
            if not batch:
                break
            for row in batch:
                params = {
                    "event_id": str(row.event_id),
                    "entity_id": str(row.entity_id),
                    "exposure_id": str(row.exposure_id),
                    "exposure_type": row.exposure_type,
                    "confidence": float(row.confidence),
                }
                await session.execute(text(_SQL_EVENT_EXPOSES_MERGE), {"params": json.dumps(params)})
            exposures_total += len(batch)
            if len(batch) < exposure_batch:
                break
            offset += exposure_batch

        logger.debug(  # type: ignore[no-any-return]
            "age_sync_temporal_events_complete",
            temporal_events_synced=events_total,
            event_exposures_synced=exposures_total,
        )
        return events_total


# ── Session helpers ────────────────────────────────────────────────────────────


async def _setup_age_session(session: AsyncSession) -> None:
    """Load the AGE extension and set the search path for this session.

    Must be called once per DB session before any AGE Cypher queries.
    See migration 0004 and PRD-0018 §6.4 for the rationale.
    """
    await session.execute(text("LOAD 'age'"))
    # Include "$user" to match the migration-time search_path constant.
    await session.execute(text('SET search_path = ag_catalog, "$user", public'))


# ── Helpers ────────────────────────────────────────────────────────────────────


def _build_relation_merge_sql(edge_label: str) -> str:
    """Build the AGE Cypher SQL for a MERGE relation edge with the given *edge_label*.

    The *edge_label* MUST be whitelist-validated before calling this function.
    It is embedded into the Cypher string (not parameterized) because AGE
    Cypher does not support dynamic edge labels via params. All data values
    (entity IDs, confidence, etc.) are passed separately as :params.

    SECURITY: Defense-in-depth assertion — prevents any future caller from
    bypassing whitelist validation and injecting arbitrary Cypher edge labels.
    """
    # SECURITY: edge_label must be whitelist-validated; assert here as defense-in-depth.
    assert edge_label in _VALID_EDGE_LABELS, f"Cypher label injection guard: {edge_label!r} not in whitelist"
    # BP-SA5-001: use lowercase ``entity`` label (same as _SQL_ENTITY_MERGE and
    # path_discovery.py) so MATCHes resolve to the correct label namespace.
    cypher = (
        "MATCH (s:entity {entity_id: $subject_id}),"
        "      (o:entity {entity_id: $object_id})"
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

    Examples
    --------
        ``"competes_with"`` → ``"COMPETES_WITH"``
        ``"has executive"`` → ``"HAS_EXECUTIVE"``
        ``"unknown_type"``  → ``None``

    """
    label = canonical_type.upper().replace(" ", "_")
    return label if label in _VALID_EDGE_LABELS else None
