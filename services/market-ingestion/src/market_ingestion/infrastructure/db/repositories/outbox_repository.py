"""SQLAlchemy implementation of OutboxRepository."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import case, select, update

from common.ids import new_ulid  # type: ignore[import-untyped]
from market_ingestion.application.ports.repositories import OutboxRecord, OutboxRepository
from market_ingestion.infrastructure.db.models.outbox_event import OutboxEventModel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from market_ingestion.domain.events import DomainEvent

# Outbox status state machine (T-E1-2-02):
#   pending → in_flight (claimed for dispatch)
#   in_flight → published (successfully published to Kafka)
#   in_flight → retry (dispatch failed, retries remaining)
#   in_flight → dead (dispatch failed, max attempts exceeded)
#   retry → in_flight (re-claimed on next dispatch cycle)

_TOPIC_FOR_EVENT: dict[str, str] = {}  # populated lazily


def _get_topic(event_type: str) -> str:
    """Resolve the Kafka topic for a given event_type.

    Raises ValueError for unknown event types (BP-039) — no silent fallback
    to event_type as topic, which would silently publish to the wrong topic.
    """
    if not _TOPIC_FOR_EVENT:
        try:
            from messaging.topics import MARKET_DATASET_FETCHED  # type: ignore[import-untyped]

            _TOPIC_FOR_EVENT["market.dataset.fetched"] = MARKET_DATASET_FETCHED
        except ImportError:
            _TOPIC_FOR_EVENT["market.dataset.fetched"] = "market.dataset.fetched"
    topic = _TOPIC_FOR_EVENT.get(event_type)
    if topic is None:
        raise ValueError(
            f"Unknown event_type '{event_type}' — cannot resolve Kafka topic. "
            "Register the topic in _TOPIC_FOR_EVENT before adding this event to the outbox."
        )
    return topic


def _row_to_record(row: OutboxEventModel) -> OutboxRecord:
    return OutboxRecord(
        id=row.id,
        topic=row.topic,
        key=row.key,
        payload=row.payload,
        headers=row.headers or {},
        event_type=row.event_type,
        created_at=row.created_at,
        correlation_id=row.correlation_id,
        attempt=row.attempt,
    )


class SqlaOutboxRepository(OutboxRepository):
    """SQLAlchemy-backed OutboxRepository."""

    def __init__(self, write_session: AsyncSession, read_session: AsyncSession) -> None:
        self._w = write_session
        self._r = read_session

    async def add(self, *, events: Sequence[DomainEvent]) -> None:
        for event in events:
            if hasattr(event, "to_dict"):
                event_dict = cast("dict[str, Any]", cast("Any", event).to_dict())
            else:
                event_dict = {"event_type": event.EVENT_TYPE, "event_id": event.event_id}
            event_type = event_dict.get("event_type", "")
            topic = _get_topic(event_type)
            payload_bytes = json.dumps(event_dict).encode("utf-8")
            row = OutboxEventModel(
                id=new_ulid(),
                topic=topic,
                key=event.event_id.encode("utf-8") if hasattr(event, "event_id") else None,
                payload=payload_bytes,
                headers={"event_type": event_type},
                event_type=event_type,
                status="pending",
                attempt=0,
            )
            self._w.add(row)

    async def claim_batch(
        self,
        *,
        batch_size: int,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> list[OutboxRecord]:
        """Claim up to batch_size pending outbox rows using FOR UPDATE SKIP LOCKED."""
        lease_until = now + timedelta(seconds=lease_seconds)
        subq = (
            select(OutboxEventModel.id)
            .where(
                OutboxEventModel.status.in_(["pending", "retry"]),
                (OutboxEventModel.next_attempt_at.is_(None)) | (OutboxEventModel.next_attempt_at <= now),
            )
            .order_by(OutboxEventModel.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await self._w.execute(subq)
        ids = [row[0] for row in result.fetchall()]
        if not ids:
            return []

        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id.in_(ids))
            .values(
                status="in_flight",
                locked_by=worker_id,
                locked_until=lease_until,
            )
            .returning(OutboxEventModel)
        )
        rows = (await self._w.execute(stmt)).scalars().all()
        return [_row_to_record(row) for row in rows]

    async def mark_published(
        self,
        *,
        outbox_id: UUID | str,
        published_at: datetime,
        worker_id: str,
    ) -> bool:
        stmt = (
            update(OutboxEventModel)
            .where(
                OutboxEventModel.id == str(outbox_id),
                OutboxEventModel.locked_by == worker_id,
            )
            .values(
                status="published",
                published_at=published_at,
                # F-003: keep ``dispatched_at`` in lock-step with
                # ``published_at`` so cross-service SQL tooling that filters
                # on the canonical column sees this service's rows.
                dispatched_at=published_at,
                locked_by=None,
                locked_until=None,
            )
        )
        result = await self._w.execute(stmt)
        return int(cast("Any", result).rowcount) > 0

    async def mark_failed(
        self,
        *,
        outbox_id: UUID | str,
        error: str,
        worker_id: str,
        now: datetime,
        max_attempts: int,
        backoff_seconds: int,
    ) -> bool:
        # Single atomic UPDATE: increment attempt and decide status/next_at in SQL.
        # Avoids the read-modify-write race (M-011) where two workers could both read
        # the same attempt count and both decide to retry instead of dead-lettering.
        new_attempt = OutboxEventModel.attempt + 1
        exceeded = new_attempt >= max_attempts
        next_at = now + timedelta(seconds=backoff_seconds)

        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id == str(outbox_id))
            .values(
                attempt=new_attempt,
                status=case((exceeded, "dead"), else_="retry"),
                last_error=error,
                locked_by=None,
                locked_until=None,
                next_attempt_at=case((exceeded, None), else_=next_at),
            )
        )
        result = await self._w.execute(stmt)
        return int(cast("Any", result).rowcount) > 0

    # ── Dispatcher-protocol-compatible helpers ─────────────────────────────────

    async def fetch_pending_for_dispatch(
        self,
        worker_id: str,
        lease_seconds: int,
        batch_size: int,
    ) -> list[_DispatchableOutboxRecord]:
        """Claim records in a format suitable for BaseOutboxDispatcher."""
        now = datetime.now(UTC)
        records = await self.claim_batch(
            batch_size=batch_size,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=now,
        )
        return [_DispatchableOutboxRecord.from_outbox_record(r) for r in records]

    async def mark_published_simple(self, record_id: str, worker_id: str) -> None:
        """Mark published by ULID string + worker_id."""
        now = datetime.now(UTC)
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(
                status="published",
                published_at=now,
                # F-003: mirror into ``dispatched_at`` (canonical column) so
                # the dispatcher path matches ``mark_published`` above.
                dispatched_at=now,
                locked_by=None,
                locked_until=None,
            )
        )
        await self._w.execute(stmt)

    async def increment_attempts_simple(self, record_id: str) -> None:
        """Increment attempt count for a record (dispatcher retry path)."""
        stmt = (
            update(OutboxEventModel)
            .where(OutboxEventModel.id == record_id)
            .values(attempt=OutboxEventModel.attempt + 1, status="retry")
        )
        await self._w.execute(stmt)

    async def move_to_dead_letter_simple(self, record_id: str) -> None:
        """Move a record to the dead-letter state."""
        stmt = update(OutboxEventModel).where(OutboxEventModel.id == record_id).values(status="dead")
        await self._w.execute(stmt)

    # ── Operator requeue (BUG-5) ────────────────────────────────────────────────

    async def count_dead(self, *, topic: str | None = None, older_than: datetime | None = None) -> int:
        """Count ``dead`` rows, optionally scoped by *topic* / *older_than*.

        Backs the requeue operator script's ``--dry-run`` mode.
        """
        from sqlalchemy import func

        stmt = select(func.count()).select_from(OutboxEventModel).where(OutboxEventModel.status == "dead")
        if topic is not None:
            stmt = stmt.where(OutboxEventModel.topic == topic)
        if older_than is not None:
            stmt = stmt.where(OutboxEventModel.created_at <= older_than)
        result = await self._r.execute(stmt)
        return int(cast("Any", result).scalar() or 0)

    async def requeue_dead_to_pending(
        self,
        *,
        ids: list[str] | None = None,
        topic: str | None = None,
        older_than: datetime | None = None,
        reset_attempts: bool = True,
    ) -> int:
        """Move ``dead`` rows back to ``pending`` so ``claim_batch`` re-picks them.

        BUG-5: ``move_to_dead_letter_simple`` sets ``status='dead'`` but
        ``claim_batch`` only selects ``status IN ('pending','retry')`` — so the
        24,163 dead ``market.dataset.fetched`` rows can never be re-dispatched.
        This is the safe, operator-invokable recovery path used by
        ``scripts/requeue_dead_outbox.py``.

        Idempotency / safety:
        * Only rows currently in ``dead`` are touched — re-running is a no-op once
          they have moved to ``pending``.
        * The lease (``locked_by``/``locked_until``) is cleared and
          ``next_attempt_at`` is reset to NULL so the row is immediately claimable
          (and not held back by a stale backoff timestamp).
        * ``reset_attempts`` zeroes ``attempt`` so the row gets a full retry budget.

        Bounding: pass ``ids``, ``topic``, and/or ``older_than``. At least one
        bound MUST be supplied — an unbounded requeue is refused.

        Returns the number of rows transitioned.
        """
        if ids is None and topic is None and older_than is None:
            raise ValueError(
                "requeue_dead_to_pending requires a bound: pass ids=, topic=, or older_than=. "
                "An unbounded requeue is refused for safety."
            )

        values: dict[str, Any] = {
            "status": "pending",
            "locked_by": None,
            "locked_until": None,
            "next_attempt_at": None,
        }
        if reset_attempts:
            values["attempt"] = 0

        stmt = update(OutboxEventModel).where(OutboxEventModel.status == "dead")
        if ids is not None:
            stmt = stmt.where(OutboxEventModel.id.in_([str(i) for i in ids]))
        if topic is not None:
            stmt = stmt.where(OutboxEventModel.topic == topic)
        if older_than is not None:
            stmt = stmt.where(OutboxEventModel.created_at <= older_than)
        stmt = stmt.values(**values)

        result = await self._w.execute(stmt)
        return int(cast("Any", result).rowcount)


class _DispatchableOutboxRecord:
    """Adapts OutboxRecord to satisfy OutboxRecordProtocol for BaseOutboxDispatcher."""

    __slots__ = ("_attempts", "_event_type", "_id", "_leased_until", "_payload", "_topic")

    def __init__(
        self,
        event_type: str,
        topic: str,
        payload: dict[str, Any],
        attempts: int,
        leased_until: datetime | None,
        record_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        legacy_id = kwargs.pop("id", None)
        if kwargs:
            raise TypeError(f"Unexpected keyword arguments: {', '.join(kwargs.keys())}")
        resolved_id = record_id or legacy_id
        if resolved_id is None:
            raise TypeError("record_id is required")

        self._id = str(resolved_id)
        self._event_type = event_type
        self._topic = topic
        self._payload = payload
        self._attempts = attempts
        self._leased_until = leased_until

    @classmethod
    def from_outbox_record(cls, record: OutboxRecord) -> _DispatchableOutboxRecord:
        payload_dict = json.loads(record.payload) if isinstance(record.payload, bytes) else record.payload
        return cls(
            record_id=str(record.id),
            event_type=record.event_type,
            topic=record.topic,
            payload=payload_dict,
            attempts=record.attempt,
            leased_until=None,
        )

    @property
    def id(self) -> str:
        return self._id

    @property
    def event_type(self) -> str:
        return self._event_type

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def payload(self) -> dict[str, Any]:
        return self._payload

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def leased_until(self) -> datetime | None:
        return self._leased_until
