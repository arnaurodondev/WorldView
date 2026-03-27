"""SQLAlchemy implementation of TaskRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from market_ingestion.application.ports.repositories import TaskRepository
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import DatasetType, IngestionTaskStatus, Provider
from market_ingestion.infrastructure.db.models.ingestion_task import IngestionTaskModel

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


def _to_domain(row: IngestionTaskModel) -> IngestionTask:
    """Map an ORM row to a domain IngestionTask."""
    result_ref: ObjectRef | None = None
    if row.result_ref_bucket and row.result_ref_key:
        from market_ingestion.domain.value_objects import ObjectRef

        result_ref = ObjectRef(
            bucket=row.result_ref_bucket,
            key=row.result_ref_key,
            sha256=row.result_ref_sha256 or "",
            # byte_length not stored in DB — use 0 as sentinel; field is informational only
            byte_length=0,
            mime_type=row.result_ref_mime_type or "",
        )
    task = IngestionTask(
        id=row.id,
        provider=Provider(row.provider),
        dataset_type=DatasetType(row.dataset_type),
        symbol=row.symbol,
        exchange=row.exchange,
        timeframe=row.timeframe,
        variant=row.dataset_variant,
        range_start=row.range_start,
        range_end=row.range_end,
        dedupe_key=row.dedupe_key,
        status=IngestionTaskStatus(row.status),
        lease_owner=row.locked_by,
        lease_expires=row.locked_until,
        attempt_count=row.attempt,
        error_message=row.last_error,
        next_attempt_at=row.next_attempt_at,
        result_ref=result_ref,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )
    return task


def _to_model(task: IngestionTask) -> IngestionTaskModel:
    """Map a domain IngestionTask to an ORM model row."""
    return IngestionTaskModel(
        id=task.id,
        provider=task.provider.value,
        dataset_type=task.dataset_type.value,
        dataset_variant=task.variant,
        symbol=task.symbol,
        exchange=task.exchange,
        timeframe=task.timeframe,
        range_start=task.range_start,
        range_end=task.range_end,
        status=task.status.value,
        attempt=task.attempt_count,
        next_attempt_at=task.next_attempt_at,
        last_error=task.error_message,
        locked_by=task.lease_owner,
        locked_until=task.lease_expires,
        dedupe_key=task.dedupe_key,
        is_backfill=task.range_start is not None,
        created_at=task.created_at,
    )


class SqlaTaskRepository(TaskRepository):
    """SQLAlchemy-backed TaskRepository."""

    def __init__(
        self,
        write_session: AsyncSession,
        read_session: AsyncSession,
    ) -> None:
        self._w = write_session
        self._r = read_session

    async def get(self, task_id: str) -> IngestionTask | None:
        row = await self._r.get(IngestionTaskModel, task_id)
        return _to_domain(row) if row else None

    async def add(self, task: IngestionTask) -> None:
        stmt = (
            pg_insert(IngestionTaskModel)
            .values(
                id=task.id,
                provider=task.provider.value,
                dataset_type=task.dataset_type.value,
                dataset_variant=task.variant,
                symbol=task.symbol,
                exchange=task.exchange,
                timeframe=task.timeframe,
                range_start=task.range_start,
                range_end=task.range_end,
                status=task.status.value,
                attempt=task.attempt_count,
                next_attempt_at=task.next_attempt_at,
                last_error=task.error_message,
                locked_by=task.lease_owner,
                locked_until=task.lease_expires,
                dedupe_key=task.dedupe_key,
                is_backfill=task.range_start is not None,
                created_at=task.created_at,
            )
            .on_conflict_do_nothing(index_elements=["provider", "dedupe_key"])
        )
        await self._w.execute(stmt)

    async def add_many(self, tasks: Sequence[IngestionTask]) -> int:
        if not tasks:
            return 0
        inserted = 0
        for task in tasks:
            stmt = (
                pg_insert(IngestionTaskModel)
                .values(
                    id=task.id,
                    provider=task.provider.value,
                    dataset_type=task.dataset_type.value,
                    dataset_variant=task.variant,
                    symbol=task.symbol,
                    exchange=task.exchange,
                    timeframe=task.timeframe,
                    range_start=task.range_start,
                    range_end=task.range_end,
                    status=task.status.value,
                    attempt=task.attempt_count,
                    next_attempt_at=task.next_attempt_at,
                    last_error=task.error_message,
                    locked_by=task.lease_owner,
                    locked_until=task.lease_expires,
                    dedupe_key=task.dedupe_key,
                    is_backfill=task.range_start is not None,
                    created_at=task.created_at,
                )
                .on_conflict_do_nothing(index_elements=["provider", "dedupe_key"])
            )
            result = await self._w.execute(stmt)
            inserted += cast("Any", result).rowcount
        return inserted

    async def save(self, task: IngestionTask) -> None:
        stmt = (
            update(IngestionTaskModel)
            .where(IngestionTaskModel.id == task.id)
            .values(
                status=task.status.value,
                attempt=task.attempt_count,
                next_attempt_at=task.next_attempt_at,
                last_error=task.error_message,
                locked_by=task.lease_owner,
                locked_until=task.lease_expires,
                result_ref_bucket=task.result_ref.bucket if task.result_ref else None,
                result_ref_key=task.result_ref.key if task.result_ref else None,
                result_ref_sha256=task.result_ref.sha256 if task.result_ref else None,
                result_ref_mime_type=task.result_ref.mime_type if task.result_ref else None,
                completed_at=task.completed_at,
            )
        )
        await self._w.execute(stmt)

    async def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int,
        lease_seconds: int,
    ) -> list[IngestionTask]:
        """Atomically claim PENDING/RETRY tasks using FOR UPDATE SKIP LOCKED."""
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=lease_seconds)

        claimable_statuses = (
            IngestionTaskStatus.PENDING.value,
            IngestionTaskStatus.RETRY.value,
        )

        # Select claimable rows with skip-locked
        subq = (
            select(IngestionTaskModel.id)
            .where(
                IngestionTaskModel.status.in_(claimable_statuses),
                (IngestionTaskModel.next_attempt_at.is_(None)) | (IngestionTaskModel.next_attempt_at <= now),
            )
            .order_by(IngestionTaskModel.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._w.execute(subq)
        ids = [row[0] for row in result.fetchall()]
        if not ids:
            return []

        # Update claimed rows
        stmt = (
            update(IngestionTaskModel)
            .where(IngestionTaskModel.id.in_(ids))
            .values(
                status=IngestionTaskStatus.RUNNING.value,
                locked_by=worker_id,
                locked_until=lease_until,
                attempt=IngestionTaskModel.attempt + 1,
            )
            .returning(IngestionTaskModel)
        )
        rows = (await self._w.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]

    async def has_active_task(
        self,
        *,
        provider: Provider,
        dataset_type: DatasetType,
        symbol: str,
        exchange: str | None,
        timeframe: str | None,
        variant: str | None,
    ) -> bool:
        active = (
            IngestionTaskStatus.PENDING.value,
            IngestionTaskStatus.RUNNING.value,
            IngestionTaskStatus.RETRY.value,
        )

        exchange_predicate = (
            IngestionTaskModel.exchange.is_(None) if exchange is None else IngestionTaskModel.exchange == exchange
        )
        timeframe_predicate = (
            IngestionTaskModel.timeframe.is_(None) if timeframe is None else IngestionTaskModel.timeframe == timeframe
        )
        variant_predicate = (
            IngestionTaskModel.dataset_variant.is_(None)
            if variant is None
            else IngestionTaskModel.dataset_variant == variant
        )

        stmt = (
            select(IngestionTaskModel.id)
            .where(
                IngestionTaskModel.provider == provider.value,
                IngestionTaskModel.dataset_type == dataset_type.value,
                IngestionTaskModel.symbol == symbol,
                exchange_predicate,
                timeframe_predicate,
                variant_predicate,
                IngestionTaskModel.status.in_(active),
            )
            .limit(1)
        )
        result = await self._r.execute(stmt)
        return result.first() is not None

    async def list_by_status(self, status: str, limit: int = 100) -> list[IngestionTask]:
        stmt = (
            select(IngestionTaskModel)
            .where(IngestionTaskModel.status == status)
            .order_by(IngestionTaskModel.created_at.desc())
            .limit(limit)
        )
        rows = (await self._r.execute(stmt)).scalars().all()
        return [_to_domain(row) for row in rows]

    async def count_by_status(self) -> dict[str, int]:
        stmt = select(IngestionTaskModel.status, func.count()).group_by(IngestionTaskModel.status)
        result = await self._r.execute(stmt)
        return {row[0]: row[1] for row in result.fetchall()}
