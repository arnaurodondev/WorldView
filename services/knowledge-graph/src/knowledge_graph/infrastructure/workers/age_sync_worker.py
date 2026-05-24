"""Worker 13F: Apache AGE Shadow Sync (PRD-0018 §6 Worker 13F).

APScheduler interval job — every 15 minutes by default.

Performs a watermark-based incremental sync from the relational tables
in ``intelligence_db`` to the Apache AGE property-graph extension.

PLAN-0093 Wave B-1 changes:
  - On worker startup, ``_bootstrap_age_labels`` ensures every vlabel and
    elabel used by the worker exists in the graph before any MERGE attempt.
    Previously a missing label silently crashed the sync inside the outer
    try/except, leaving 100% of temporal events out of AGE.
  - The single ``s7:age:sync:watermark`` Valkey key is replaced by three
    per-phase keys: ``...:entities``, ``...:relations``, ``...:temporal_events``.
    Each phase has its own try/except + watermark — a failure in one phase no
    longer poisons the others.
  - A stall detector compares ``synced_count == 0`` against
    ``COUNT(*) WHERE updated_at > watermark`` and bumps
    ``s7_age_sync_phase_stalled_total`` + emits ``age_sync_phase_stalled``
    when the worker silently fell behind.

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

import contextlib
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from common.time import utc_now  # type: ignore[import-untyped]
from knowledge_graph.infrastructure.metrics.prometheus import (
    s7_age_sync_duration_seconds,
    s7_age_sync_entities_total,
    s7_age_sync_phase_stalled_total,
    s7_age_sync_relations_total,
)
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from knowledge_graph.config import Settings
    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ─────────────────────────────────────────────────────────────────

# Legacy single watermark key — kept for one-shot migration support (reset
# scripts DEL all four).  New code reads/writes the per-phase keys below.
_WATERMARK_KEY = "s7:age:sync:watermark"

# PLAN-0093 B-1 T-B-1-02: per-phase watermark keys.  Each phase reads + writes
# its own key so a transient failure in one phase does not stall the others.
_PHASE_ENTITIES = "entities"
_PHASE_RELATIONS = "relations"
_PHASE_TEMPORAL_EVENTS = "temporal_events"
_PHASE_WATERMARK_KEYS: dict[str, str] = {
    _PHASE_ENTITIES: "s7:age:sync:watermark:entities",
    _PHASE_RELATIONS: "s7:age:sync:watermark:relations",
    _PHASE_TEMPORAL_EVENTS: "s7:age:sync:watermark:temporal_events",
}

# Source-table watermark column per phase — used by the stall detector.
_PHASE_SOURCE_TABLES: dict[str, tuple[str, str]] = {
    _PHASE_ENTITIES: ("canonical_entities", "updated_at"),
    _PHASE_RELATIONS: ("relations", "updated_at"),
    _PHASE_TEMPORAL_EVENTS: ("temporal_events", "updated_at"),
}

_AGE_GRAPH_NAME = "worldview_graph"

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

# Confidence threshold — relations BELOW this AND with non-NULL confidence are not synced (noise filter).
# NULL-confidence relations (provisional evidence, not yet computed) ARE synced with confidence=0.0
# so Cypher path queries see the full graph. BP-539 fix: the previous hard filter excluded 72% of
# relations because their evidence was still provisional (entity_provisional=true), causing AGE to
# reflect only 27% of the true graph structure.
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
        # migration 0041 — Lever-4 financial taxonomy expansion
        "APPOINTED_AS",
        "DIVESTED_FROM",
        "DOWNGRADED_BY",
        "FILED_LAWSUIT_AGAINST",
        "REPORTED_REVENUE_OF",
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
    ) -> None:
        self._sf = session_factory
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
        # PLAN-0093 B-1 T-B-1-01: label bootstrap runs exactly once per worker
        # process startup.  ``True`` here means the bootstrap has not yet been
        # attempted; the first successful run() flips it to ``False``.
        self._labels_bootstrap_pending = True

    async def run(self) -> None:
        """Execute one full AGE shadow sync cycle.

        PLAN-0093 B-1 rewrite: each phase has its own try/except + watermark.
        A ProgrammingError in one phase logs ``age_sync_phase_failed`` and skips
        only that phase's watermark advance — the other phases continue normally.
        Non-Programming exceptions are re-raised so APScheduler (and the
        container orchestrator) can react.
        """
        if not self._settings.cypher_enabled:
            logger.debug("age_sync_worker_disabled")  # type: ignore[no-any-return]
            return

        start = time.monotonic()
        new_watermark = utc_now()  # type: ignore[no-any-return]

        logger.info(  # type: ignore[no-any-return]
            "age_sync_worker_start",
            new_watermark=new_watermark.isoformat(),
        )

        entities_synced = 0
        relations_synced = 0
        temporal_events_synced = 0

        async with self._sf() as session:
            # T-B-1-01: bootstrap labels on first successful session before
            # touching any MERGE — once per process lifetime.
            if self._labels_bootstrap_pending:
                try:
                    await self._bootstrap_age_labels(session)
                    self._labels_bootstrap_pending = False
                except ProgrammingError as exc:
                    # AGE extension itself is missing (LOAD 'age' fails) — log
                    # and skip the whole cycle; mirrors the old F-159 path.
                    logger.warning(  # type: ignore[no-any-return]
                        "age_sync_age_unavailable",
                        error=type(exc).__name__,
                        message=(
                            "AGE extension unavailable during label bootstrap — "
                            "skipping sync cycle; set KNOWLEDGE_GRAPH_CYPHER_ENABLED=false to suppress"
                        ),
                    )
                    return

            # Phase 1 — entities
            entities_synced = await self._run_phase(
                session=session,
                phase=_PHASE_ENTITIES,
                sync_fn=self._sync_entities,
                new_watermark=new_watermark,
            )

            # Phase 2 — relations
            relations_synced = await self._run_phase(
                session=session,
                phase=_PHASE_RELATIONS,
                sync_fn=self._sync_relations,
                new_watermark=new_watermark,
            )

            # Phase 3 — temporal events (also covers EVENT_EXPOSES edges)
            temporal_events_synced = await self._run_phase(
                session=session,
                phase=_PHASE_TEMPORAL_EVENTS,
                sync_fn=self._sync_temporal_events,
                new_watermark=new_watermark,
            )

        elapsed = time.monotonic() - start
        s7_age_sync_entities_total.inc(entities_synced)
        s7_age_sync_relations_total.inc(relations_synced)
        s7_age_sync_duration_seconds.observe(elapsed)

        # Log a warning when nothing was synced — may indicate the relational
        # tables are empty or the watermarks are ahead of all rows.
        if entities_synced == 0 and relations_synced == 0 and temporal_events_synced == 0:
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_worker_no_changes",
                duration_s=round(elapsed, 2),
                message=(
                    "all AGE MERGE operations were no-ops — relational tables may be empty " "or watermarks are stale"
                ),
            )

        logger.info(  # type: ignore[no-any-return]
            "age_sync_worker_complete",
            entities_synced=entities_synced,
            relations_synced=relations_synced,
            temporal_events_synced=temporal_events_synced,
            duration_s=round(elapsed, 2),
            new_watermark=new_watermark.isoformat(),
        )

    # ── Per-phase execution ───────────────────────────────────────────────────

    async def _run_phase(
        self,
        *,
        session: AsyncSession,
        phase: str,
        sync_fn: Any,
        new_watermark: datetime,
    ) -> int:
        """Run one sync phase with its own watermark + try/except + stall check.

        Behaviour contract:
          - Reads the phase's own watermark from Valkey (epoch on miss).
          - Re-runs ``_setup_age_session`` (LOAD age + SET search_path) on the
            shared session because each commit clears it.
          - Calls ``sync_fn(session, watermark)`` and commits.
          - On ``ProgrammingError`` (AGE label missing, type mismatch, …) logs
            ``age_sync_phase_failed`` and returns 0 WITHOUT advancing the phase
            watermark — the other phases continue.
          - On any other exception, re-raises so APScheduler can react.
          - On success, persists ``new_watermark`` to the phase's key and
            invokes the stall detector.
        """
        watermark = await self._get_phase_watermark(phase)
        try:
            await _setup_age_session(session)
            synced_count = await sync_fn(session, watermark)
            await session.commit()
        except ProgrammingError as exc:
            # Roll back the session so subsequent phases get a clean slate.
            # Best-effort cleanup: if rollback itself fails we still want to
            # log + return — never crash run() on a cleanup-of-cleanup failure.
            with contextlib.suppress(Exception):
                await session.rollback()
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_phase_failed",
                phase=phase,
                error=type(exc).__name__,
                message=(
                    f"AGE sync phase '{phase}' raised ProgrammingError — "
                    "watermark not advanced; other phases continue"
                ),
                exc_info=True,
            )
            return 0

        # Phase succeeded — advance its own watermark.
        await self._set_phase_watermark(phase, new_watermark)

        logger.info(  # type: ignore[no-any-return]
            "age_sync_phase_complete",
            phase=phase,
            synced_count=synced_count,
            new_watermark=new_watermark.isoformat(),
        )

        # T-B-1-03 stall detector: if we synced nothing yet the source table
        # has rows newer than the previous watermark, bump the counter.
        if synced_count == 0:
            await self._check_phase_stalled(session=session, phase=phase, watermark=watermark)

        return int(synced_count)

    async def _check_phase_stalled(
        self,
        *,
        session: AsyncSession,
        phase: str,
        watermark: datetime,
    ) -> None:
        """Emit a stall warning + counter bump when no rows synced but the
        source table has rows newer than the previous watermark.

        Helps surface silent failures: a phase appears healthy (returns 0,
        no exception) but the underlying data has moved on.
        """
        table, ts_column = _PHASE_SOURCE_TABLES[phase]
        try:
            row = await session.execute(
                # Static identifiers (table, column) come from a server-side
                # whitelist (_PHASE_SOURCE_TABLES) — never from user input.
                text(  # - identifiers from server-side whitelist
                    f"SELECT COUNT(*) AS c FROM {table} WHERE {ts_column} > :since",  # noqa: S608
                ),
                {"since": watermark},
            )
            newer = int(row.scalar() or 0)
        except Exception as exc:
            # Stall detector is best-effort observability — never crash run().
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_phase_stall_check_failed",
                phase=phase,
                error=type(exc).__name__,
                exc_info=True,
            )
            return

        if newer > 0:
            lag_seconds = round((utc_now() - watermark).total_seconds())  # type: ignore[no-any-return]
            s7_age_sync_phase_stalled_total.labels(phase=phase).inc()
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_phase_stalled",
                phase=phase,
                newer_rows=newer,
                lag_seconds=lag_seconds,
                watermark=watermark.isoformat(),
                message=(
                    f"AGE sync phase '{phase}' synced 0 rows but {newer} source rows "
                    f"are newer than the watermark — possible silent failure"
                ),
            )

    # ── Label bootstrap ───────────────────────────────────────────────────────

    async def _bootstrap_age_labels(self, session: AsyncSession) -> None:
        """Create all vlabels and elabels used by the sync worker.

        AGE requires labels to exist before MERGE can target them.  Without
        this bootstrap the ``TemporalEvent`` vlabel and ``EVENT_EXPOSES``
        elabel were never created in fresh environments, so every sync attempt
        raised ProgrammingError and was silently swallowed by the outer
        try-except — leaving 0 events and 0 exposure edges in AGE.

        Idempotent: ``already exists`` ProgrammingErrors are swallowed.
        """
        statements = [
            # Vertex labels — entity already exists; ensure all needed types
            f"SELECT create_vlabel('{_AGE_GRAPH_NAME}', 'entity')",
            f"SELECT create_vlabel('{_AGE_GRAPH_NAME}', 'TemporalEvent')",
            # Edge labels — every value in _VALID_EDGE_LABELS (includes EVENT_EXPOSES)
            *[f"SELECT create_elabel('{_AGE_GRAPH_NAME}', '{lbl}')" for lbl in sorted(_VALID_EDGE_LABELS)],
        ]
        await _setup_age_session(session)
        for stmt in statements:
            try:
                # Static graph name + whitelist-validated labels — no user input.
                await session.execute(text(stmt))
            except ProgrammingError as exc:
                # "label already exists" is the desired idempotent path.
                msg = str(exc).lower()
                if "already exists" in msg:
                    continue
                # Any other ProgrammingError (e.g. AGE extension missing) is
                # propagated so run() can mark the cycle skipped.
                raise
        await session.commit()
        logger.info(  # type: ignore[no-any-return]
            "age_sync_labels_bootstrapped",
            vlabels=2,
            elabels=len(_VALID_EDGE_LABELS),
        )

    # ── Watermark ─────────────────────────────────────────────────────────────

    async def _get_phase_watermark(self, phase: str) -> datetime:
        """Read the per-phase watermark from Valkey; epoch on miss or error.

        Falls back to epoch (full re-sync for that phase) on Valkey
        unavailability — AGE MERGE is idempotent so re-syncing is safe.
        """
        key = _PHASE_WATERMARK_KEYS[phase]
        try:
            raw = await self._valkey.get(key)
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_watermark_read_failed",
                phase=phase,
                key=key,
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

    async def _set_phase_watermark(self, phase: str, dt: datetime) -> None:
        """Persist *dt* (ISO-8601 UTC) as the new per-phase watermark in Valkey.

        Logs and swallows Valkey errors — on next run the phase watermark
        falls back to epoch (full re-sync), which is safe since AGE MERGE is
        idempotent.
        """
        key = _PHASE_WATERMARK_KEYS[phase]
        try:
            await self._valkey.set(key, dt.isoformat())
        except Exception:
            logger.warning(  # type: ignore[no-any-return]
                "age_sync_watermark_write_failed",
                phase=phase,
                key=key,
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
                    "       canonical_type, COALESCE(confidence, 0.0) AS confidence, updated_at"
                    " FROM relations"
                    " WHERE updated_at > :since"
                    # BP-539: include NULL-confidence relations (provisional evidence not yet resolved).
                    # COALESCE above maps NULL→0.0 so the AGE edge gets a valid confidence float.
                    # The filter keeps rows where confidence exceeds the threshold OR is NULL (provisional).
                    "   AND (confidence > :min_conf OR confidence IS NULL)"
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
    # SECURITY: edge_label must be whitelist-validated. Use if/raise (not assert) so the
    # guard is never stripped by python -O optimized mode in production containers.
    if edge_label not in _VALID_EDGE_LABELS:
        raise ValueError(f"Cypher label injection guard: {edge_label!r} not in whitelist")
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
