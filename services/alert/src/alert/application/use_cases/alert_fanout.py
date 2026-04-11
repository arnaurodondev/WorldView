"""Alert fan-out use case.

Resolves watchers for an incoming intelligence event, writes alert +
pending rows + outbox event in a single DB transaction, then pushes via
WebSocket *after* commit.

Backfill suppression rules (PRD AD-10):
- nlp.signal.detected.v1 / graph.state.changed.v1: suppress ALL backfill.
- intelligence.contradiction.v1: suppress only if is_backfill AND the event
  is older than 30 days (recent-impact contradictions are still useful).

Dedup key (PRD AD-9): sha256(entity_id:alert_type:window_bucket)
where window_bucket = epoch_seconds // dedup_window_seconds.
source_event_id is intentionally excluded so that multiple events about
the same entity+type within one window are collapsed into one alert.

Severity (PRD-0021 §6.5):
- nlp.signal.detected.v1: severity = SeverityThresholds.classify(market_impact_score)
- graph.state.changed.v1 / intelligence.contradiction.v1: severity = MEDIUM (F-13 override)
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import fastavro  # type: ignore[import-untyped]
import fastavro.schema  # type: ignore[import-untyped]

from alert.domain.entities import Alert, OutboxEvent, PendingAlert, SeverityThresholds
from alert.domain.enums import AlertSeverity, AlertType
from alert.domain.errors import DuplicateAlertError
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from alert.application.ports.notification import INotificationPublisher
    from alert.application.ports.repositories import (
        AlertSaveRepositoryPort,
        DedupRepositoryPort,
        OutboxRepositoryPort,
        PendingAlertRepositoryPort,
    )
    from alert.application.ports.watchlist import IWatchlistCache

    class RepoFactory:
        """Protocol for constructing repos from a session."""

        def __call__(
            self,
            session: AsyncSession,
        ) -> tuple[
            AlertSaveRepositoryPort,
            PendingAlertRepositoryPort,
            DedupRepositoryPort,
            OutboxRepositoryPort,
        ]: ...


logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Constants ──────────────────────────────────────────────────────────────────

_BACKFILL_MAX_AGE = timedelta(days=30)

TOPIC_ALERT_TYPE: dict[str, AlertType] = {
    "nlp.signal.detected.v1": AlertType.SIGNAL,
    "graph.state.changed.v1": AlertType.GRAPH_CHANGE,
    "intelligence.contradiction.v1": AlertType.CONTRADICTION,
}

# Topics that always get MEDIUM severity regardless of market_impact_score (PRD-0021 F-13)
_MEDIUM_OVERRIDE_TOPICS: frozenset[str] = frozenset({"graph.state.changed.v1", "intelligence.contradiction.v1"})

# Schema file path — C-04 / BP-119: load from .avsc, never define inline
# Layout: services/alert/src/alert/application/use_cases/alert_fanout.py
#                                                          ^ parents[0]
# parents[6] = repo root
_SCHEMA_PATH = Path(__file__).parents[6] / "infra" / "kafka" / "schemas" / "alert.delivered.v1.avsc"

_PARSED_SCHEMA: dict[str, Any] | None = None


def _get_parsed_schema() -> dict[str, Any]:
    global _PARSED_SCHEMA
    if _PARSED_SCHEMA is None:
        _PARSED_SCHEMA = fastavro.schema.load_schema(_SCHEMA_PATH)  # type: ignore[assignment, arg-type]
    return _PARSED_SCHEMA  # type: ignore[return-value]


# ── Data classes ───────────────────────────────────────────────────────────────


@dataclass
class FanoutResult:
    """Outcome of one :meth:`AlertFanoutUseCase.execute` call."""

    suppressed: bool = False
    suppression_reason: str = ""  # "backfill" | "dedup" | "no_entity_id" | ""
    watchers_count: int = 0
    alert_id: UUID | None = None
    pending_count: int = 0


# ── Private helpers ────────────────────────────────────────────────────────────


def _should_suppress(event: dict[str, Any], topic: str) -> bool:
    """Return ``True`` if the event should be suppressed (PRD AD-10)."""
    is_backfill: bool = bool(event.get("is_backfill", False))
    if not is_backfill:
        return False

    if topic in ("nlp.signal.detected.v1", "graph.state.changed.v1"):
        return True

    if topic == "intelligence.contradiction.v1":
        occurred_at_str: str = str(event.get("occurred_at", ""))
        try:
            occurred_at = datetime.fromisoformat(occurred_at_str)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
        except (ValueError, AttributeError):
            return True  # malformed date → suppress conservatively
        age: timedelta = utc_now() - occurred_at  # type: ignore[assignment]
        return age > _BACKFILL_MAX_AGE

    return False


def _extract_entity_id(event: dict[str, Any], topic: str) -> str | None:
    """Return the primary entity_id string from the event, or ``None``."""
    if topic == "nlp.signal.detected.v1":
        raw = event.get("subject_entity_id") or event.get("claimer_entity_id")
    elif topic == "graph.state.changed.v1":
        raw = event.get("primary_entity_id")
    elif topic == "intelligence.contradiction.v1":
        raw = event.get("subject_entity_id")
    else:
        return None
    return str(raw) if raw else None


def _serialize_alert_delivered(
    alert: Alert,
    user_id: UUID,
    correlation_id: str | None,
) -> bytes:
    """Serialize an ``alert.delivered`` event to Avro bytes (schemaless)."""
    record = {
        "event_id": str(new_uuid7()),
        "event_type": "alert.delivered",
        "schema_version": 2,
        "occurred_at": alert.created_at.isoformat(),
        "alert_id": str(alert.alert_id),
        "user_id": str(user_id),
        "entity_id": str(alert.entity_id),
        "alert_type": str(alert.alert_type),
        "channel": "websocket",
        "correlation_id": correlation_id,
        "severity": str(alert.severity),
    }
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, _get_parsed_schema(), record)
    return buf.getvalue()


# ── Use case ───────────────────────────────────────────────────────────────────


class AlertFanoutUseCase:
    """Fan-out one intelligence event to all watching users.

    Args:
    ----
        session_factory: SQLAlchemy async session factory for alert_db.
        watchlist_cache: Cache-aside wrapper for S1 watchlist lookups.
        notification_publisher: Real-time notification publisher port (Valkey pub/sub or in-process).
        repo_factory: Factory to build repos from a session.
        dedup_window_seconds: Deduplication window length (default 300 s).
        alert_delivered_topic: Kafka topic for outbox events.
        severity_thresholds: Value object for score→severity classification.
            Defaults to ``SeverityThresholds()`` (PRD-0021 §6.5 defaults).

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        watchlist_cache: IWatchlistCache,
        notification_publisher: INotificationPublisher,
        repo_factory: RepoFactory,
        dedup_window_seconds: int = 300,
        alert_delivered_topic: str = "alert.delivered.v1",
        severity_thresholds: SeverityThresholds | None = None,
    ) -> None:
        self._sf = session_factory
        self._cache = watchlist_cache
        self._notification_publisher = notification_publisher
        self._repo_factory = repo_factory
        self._dedup_window = dedup_window_seconds
        self._alert_delivered_topic = alert_delivered_topic
        self._thresholds = severity_thresholds if severity_thresholds is not None else SeverityThresholds()

    async def execute(
        self,
        event: dict[str, Any],
        topic: str,
        correlation_id: str | None = None,
        market_impact_score: float = 0.0,
    ) -> FanoutResult:
        """Fan-out one event to all watchers.

        Args:
        ----
            event: Deserialized Kafka message value.
            topic: Source Kafka topic name.
            correlation_id: Optional tracing correlation ID.
            market_impact_score: Market impact score from the event (0.0-1.0).
                Used to compute severity for signal events; ignored for
                graph/contradiction events (F-13 MEDIUM override).

        Returns:
        -------
            :class:`FanoutResult` describing what happened.

        """
        # ── 1. Backfill suppression ──────────────────────────────────────────
        if _should_suppress(event, topic):
            logger.info(  # type: ignore[no-any-return]
                "alert_fanout.suppressed_backfill",
                topic=topic,
                event_id=event.get("event_id"),
            )
            return FanoutResult(suppressed=True, suppression_reason="backfill")

        # ── 2. Extract entity_id ─────────────────────────────────────────────
        entity_id_str = _extract_entity_id(event, topic)
        if not entity_id_str:
            logger.warning(  # type: ignore[no-any-return]
                "alert_fanout.no_entity_id",
                topic=topic,
                event_id=event.get("event_id"),
            )
            return FanoutResult(suppressed=True, suppression_reason="no_entity_id")

        try:
            entity_uuid = UUID(entity_id_str)
        except ValueError:
            logger.warning(  # type: ignore[no-any-return]
                "alert_fanout.invalid_entity_id",
                entity_id=entity_id_str,
            )
            return FanoutResult(suppressed=True, suppression_reason="no_entity_id")

        # ── 3. Resolve alert type ────────────────────────────────────────────
        alert_type = TOPIC_ALERT_TYPE.get(topic, AlertType.SIGNAL)

        # ── 4. Compute severity (PRD-0021 §6.5) ─────────────────────────────
        # Clamp score to [0.0, 1.0] (belt-and-suspenders; consumer also clamps)
        score = max(0.0, min(1.0, market_impact_score))
        # F-13: graph/contradiction always MEDIUM; signal events use score
        severity = AlertSeverity.MEDIUM if topic in _MEDIUM_OVERRIDE_TOPICS else self._thresholds.classify(score)

        # ── 5. Resolve watchers ──────────────────────────────────────────────
        watchers = await self._cache.get_watchers(entity_id_str)
        if not watchers:
            logger.debug(  # type: ignore[no-any-return]
                "alert_fanout.no_watchers",
                entity_id=entity_id_str,
                topic=topic,
            )
            return FanoutResult(suppressed=False, watchers_count=0)

        # ── 6. Dedup check ───────────────────────────────────────────────────
        now = utc_now()
        # Use event's occurred_at for the dedup window bucket (stable across re-deliveries).
        # If re-delivered in a different 300s window, the same event still hashes to the
        # same dedup_key, preventing duplicate alerts.  Fall back to now() on parse failure.
        occurred_at_raw = event.get("occurred_at", "")
        try:
            event_time = datetime.fromisoformat(str(occurred_at_raw))
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=UTC)
        except (ValueError, AttributeError, TypeError):
            event_time = now
        dedup_key = Alert.compute_dedup_key(entity_uuid, alert_type, event_time, self._dedup_window)

        async with self._sf() as session:
            alert_repo, pending_repo, dedup_repo, outbox_repo = self._repo_factory(session)
            if await dedup_repo.exists(dedup_key):
                logger.debug(  # type: ignore[no-any-return]
                    "alert_fanout.dedup_suppressed",
                    entity_id=entity_id_str,
                    alert_type=str(alert_type),
                    dedup_key=dedup_key,
                )
                return FanoutResult(
                    suppressed=True,
                    suppression_reason="dedup",
                    watchers_count=len(watchers),
                )

            # ── 7. Build alert entity ────────────────────────────────────────
            source_event_id_raw = event.get("event_id", "")
            try:
                source_event_id = UUID(str(source_event_id_raw))
            except (ValueError, AttributeError):
                source_event_id = new_uuid7()

            alert = Alert(
                entity_id=entity_uuid,
                alert_type=alert_type,
                severity=severity,
                source_event_id=source_event_id,
                source_topic=topic,
                payload=dict(event),
                dedup_key=dedup_key,
                created_at=now,
            )

            # ── 8. Single transaction: alert + pending rows + outbox ─────────
            try:
                await alert_repo.save(alert)
            except DuplicateAlertError:
                # Race condition: another worker wrote same dedup_key first.
                logger.info("alert_fanout.dedup_race", dedup_key=dedup_key)  # type: ignore[no-any-return]
                return FanoutResult(
                    suppressed=True,
                    suppression_reason="dedup",
                    watchers_count=len(watchers),
                )

            watcher_user_ids: list[UUID] = []
            for watcher in watchers:
                try:
                    user_uuid = UUID(str(watcher.user_id))
                except (ValueError, AttributeError):
                    continue

                await pending_repo.save(PendingAlert(user_id=user_uuid, alert_id=alert.alert_id))

                payload_avro = _serialize_alert_delivered(alert, user_uuid, correlation_id)
                await outbox_repo.append(
                    OutboxEvent(
                        topic=self._alert_delivered_topic,
                        partition_key=str(user_uuid),
                        payload_avro=payload_avro,
                    ),
                )
                watcher_user_ids.append(user_uuid)

            await session.commit()

        # ── 9. Post-commit WebSocket push (never inside transaction) ─────────
        ws_payload = {
            "alert_id": str(alert.alert_id),
            "entity_id": entity_id_str,
            "alert_type": str(alert_type),
            "severity": str(severity),
            "topic": topic,
            "occurred_at": now.isoformat(),
        }
        for user_uuid in watcher_user_ids:
            await self._notification_publisher.send_to_user(user_uuid, ws_payload)

        # ── 10. Metrics ──────────────────────────────────────────────────────
        # Metrics are fire-and-forget: must never affect the correctness path.
        try:
            from alert.infrastructure.metrics.prometheus import (
                s10_alerts_by_severity_total,
                s10_flash_overlays_triggered_total,
            )

            s10_alerts_by_severity_total.labels(severity=str(severity), alert_type=str(alert_type)).inc(
                len(watcher_user_ids)
            )
            if severity == AlertSeverity.CRITICAL and watcher_user_ids:
                s10_flash_overlays_triggered_total.inc()
        except Exception:
            logger.warning("alert_fanout.metrics_error", exc_info=True)  # type: ignore[no-any-return]

        logger.info(  # type: ignore[no-any-return]
            "alert_fanout.completed",
            alert_id=str(alert.alert_id),
            entity_id=entity_id_str,
            topic=topic,
            severity=str(severity),
            watchers=len(watcher_user_ids),
        )
        return FanoutResult(
            suppressed=False,
            watchers_count=len(watcher_user_ids),
            alert_id=alert.alert_id,
            pending_count=len(watcher_user_ids),
        )
