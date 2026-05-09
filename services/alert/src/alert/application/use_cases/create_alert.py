"""CreateAlertUseCase — user-initiated alert rule creation (PLAN-0082 Wave B).

Writes an Alert row + OutboxEvent row in a single DB transaction (R8 outbox
pattern). The OutboxDispatcher publishes to Kafka separately, ensuring that
the alert is never lost even if the Kafka broker is temporarily unavailable.

Design constraints:
- R8:  DB write + outbox event in one transaction — never separate commits.
- R10: UUIDv7 for all generated IDs (new_uuid7() from common.ids).
- R11: UTC-only timestamps (utc_now() from common.time).
- R25: use case depends on repository port protocols, never DB models directly.
- Domain layer is infrastructure-free — no SQLAlchemy imports here.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import fastavro  # type: ignore[import-untyped]
import fastavro.schema  # type: ignore[import-untyped]

from alert.domain.entities import Alert, OutboxEvent
from alert.domain.enums import AlertSeverity, AlertType
from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from alert.application.ports.repositories import AlertSaveRepositoryPort, OutboxRepositoryPort

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Avro schema cache ─────────────────────────────────────────────────────────
# Loaded once at module import time (like alert_fanout.py) so we don't re-parse
# on every request. None until first call to _get_parsed_schema().

_TOPIC = "alert.created.v1"


def _find_schema_path(schema_filename: str) -> Path:
    """Walk up the directory tree to find the Avro schema file.

    Mirrors the pattern used in alert_fanout.py so both use cases resolve
    schemas consistently regardless of working directory.
    """
    candidate = Path(__file__).resolve()
    for _ in range(10):
        candidate = candidate.parent
        schema_path = candidate / "infra" / "kafka" / "schemas" / schema_filename
        if schema_path.exists():
            return schema_path
    raise FileNotFoundError(f"Could not find Avro schema: {schema_filename}")


_SCHEMA_PATH = _find_schema_path("alert.created.v1.avsc")
_PARSED_SCHEMA: dict[str, Any] | None = None


def _get_parsed_schema() -> dict[str, Any]:
    """Return cached parsed Avro schema for alert.created.v1."""
    global _PARSED_SCHEMA
    if _PARSED_SCHEMA is None:
        _PARSED_SCHEMA = fastavro.schema.load_schema(str(_SCHEMA_PATH))  # type: ignore[assignment]
    return _PARSED_SCHEMA  # type: ignore[return-value]


def _serialize_alert_created(
    alert: Alert,
    user_id: str,
    tenant_id: str,
    condition: str,
    threshold: dict[str, Any],
    source: str = "llm_tool",
    correlation_id: str | None = None,
) -> bytes:
    """Serialize an alert.created.v1 Avro record (schemaless wire format).

    WHY schemaless_writer (not serialize_confluent_avro): S10 uses fastavro
    schemaless format throughout (matching alert_fanout.py). The outbox
    dispatcher reads raw bytes and publishes them without re-serialisation.
    """
    record: dict[str, Any] = {
        "event_id": str(new_uuid7()),
        "event_type": "alert.created",
        "schema_version": 1,
        "occurred_at": utc_now().isoformat(),
        "alert_id": str(alert.alert_id),
        "user_id": user_id,
        "tenant_id": tenant_id,
        "entity_id": str(alert.entity_id),
        "condition": condition,
        # threshold is JSON-encoded per the Avro schema doc field
        "threshold": json.dumps(threshold),
        "severity": str(alert.severity),
        "source": source,
        "correlation_id": correlation_id,
    }
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, _get_parsed_schema(), record)
    return buf.getvalue()


# ── Request / Result DTOs ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CreateAlertRequest:
    """Validated input for creating a user-initiated alert rule.

    ``condition`` identifies the trigger type (e.g. ``price_below``).
    ``threshold`` is a dict of condition parameters (e.g. ``{"value": 200.0}``).
    Both are stored in the Alert payload and serialised into the Avro event.
    """

    user_id: str
    tenant_id: str
    entity_id: str
    condition: str  # "price_below" | "price_above" | "volume_spike" | "percent_change"
    threshold: dict[str, Any]
    severity: str = "low"
    source: str = "llm_tool"
    correlation_id: str | None = None


@dataclass(frozen=True)
class CreateAlertResult:
    """Result returned by CreateAlertUseCase on success."""

    alert_id: str
    entity_id: str
    condition: str
    threshold: dict[str, Any]
    severity: str
    created_at: str


# ── Use case ──────────────────────────────────────────────────────────────────


class CreateAlertUseCase:
    """Persist a user-initiated alert rule + publish to Kafka via outbox (R8).

    WHY single-transaction: writing the Alert row and the OutboxEvent in one
    ``async with session:`` block guarantees the two are always in sync.
    If the commit fails, neither row is persisted.  If the Kafka broker is
    temporarily unavailable, the OutboxDispatcher will retry from the outbox
    table without data loss.

    Callers must inject the AsyncSession directly (not a factory) so the
    caller's session scope owns the transaction lifecycle (matching the DI
    pattern used by other S10 use cases).
    """

    def __init__(
        self,
        alert_repo: AlertSaveRepositoryPort,
        outbox_repo: OutboxRepositoryPort,
    ) -> None:
        # R25: depend on port interfaces (ABCs), not concrete infrastructure classes.
        # Concrete repos (AlertRepository, OutboxRepository) are injected by the
        # route-layer DI factory (api/dependencies.py), never imported here.
        self._alert_repo = alert_repo
        self._outbox_repo = outbox_repo

    async def execute(self, req: CreateAlertRequest) -> CreateAlertResult:
        """Create an alert rule and enqueue an outbox event in a single transaction.

        Steps:
          1. Build Alert domain entity (UUIDv7 ID, UTC timestamp).
          2. Compute dedup_key — prevents duplicate alert rules for the same
             entity + condition within the same 5-minute window.
          3. Persist Alert row via AlertRepository.save() (flush, no commit yet).
          4. Serialise alert.created.v1 Avro bytes.
          5. Persist OutboxEvent row via OutboxRepository.append() (flush).
          6. Session commit is delegated to the caller (route layer) — the
             use case holds no session reference and never calls commit() directly.

        Returns CreateAlertResult on success.
        Raises DuplicateAlertError if a matching dedup_key already exists.
        """
        import uuid as _uuid

        now = utc_now()

        # ── 1. Build Alert entity ─────────────────────────────────────────────
        try:
            entity_uuid = _uuid.UUID(req.entity_id)
        except ValueError:
            entity_uuid = new_uuid7()

        try:
            severity = AlertSeverity(req.severity)
        except ValueError:
            severity = AlertSeverity.LOW

        alert = Alert(
            alert_id=new_uuid7(),
            entity_id=entity_uuid,
            alert_type=AlertType.USER_RULE,
            severity=severity,
            source_event_id=new_uuid7(),
            source_topic=_TOPIC,
            payload={
                "condition": req.condition,
                "threshold": req.threshold,
                "source": req.source,
                "user_id": req.user_id,
            },
            dedup_key=Alert.compute_dedup_key(entity_uuid, AlertType.USER_RULE, now),
            created_at=now,
            tenant_id=_uuid.UUID(req.tenant_id) if req.tenant_id else None,
            title=f"Alert: {req.condition}",
            signal_label=req.condition,
        )

        # ── 2. Persist Alert row (flush but do not commit yet) ────────────────
        await self._alert_repo.save(alert)

        # ── 3. Serialise Avro event bytes ─────────────────────────────────────
        try:
            avro_bytes = _serialize_alert_created(
                alert=alert,
                user_id=req.user_id,
                tenant_id=req.tenant_id,
                condition=req.condition,
                threshold=req.threshold,
                source=req.source,
                correlation_id=req.correlation_id,
            )
        except Exception as exc:
            # Avro serialisation failure must not block the DB write.
            # Store a sentinel (b"") so the outbox row still exists and
            # the dispatcher can log the failure (BP-040 pattern).
            logger.warning(  # type: ignore[no-any-return]
                "alert_created_avro_serialization_failed",
                alert_id=str(alert.alert_id),
                error=str(exc),
            )
            avro_bytes = b""

        # ── 4. Persist OutboxEvent row (flush, no commit yet) ─────────────────
        outbox_event = OutboxEvent(
            event_id=new_uuid7(),
            topic=_TOPIC,
            partition_key=str(alert.alert_id),
            payload_avro=avro_bytes,
        )
        await self._outbox_repo.append(outbox_event)

        # ── 5. Commit is the caller's responsibility ───────────────────────────
        # The route-layer dependency (get_create_alert_uc) commits via the
        # write-session context manager after this method returns. Keeping commit
        # out of the use case preserves testability and R8 atomicity.

        logger.info(  # type: ignore[no-any-return]
            "alert_created",
            alert_id=str(alert.alert_id),
            entity_id=str(alert.entity_id),
            condition=req.condition,
            severity=req.severity,
            user_id=req.user_id,
            tenant_id=req.tenant_id,
        )

        return CreateAlertResult(
            alert_id=str(alert.alert_id),
            entity_id=str(alert.entity_id),
            condition=req.condition,
            threshold=req.threshold,
            severity=str(alert.severity),
            created_at=alert.created_at.isoformat(),
        )
