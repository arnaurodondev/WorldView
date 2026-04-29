"""SQLAlchemy implementation of ``FeedbackSubmissionRepo``."""

from __future__ import annotations

import builtins  # — used in string annotation for `tags: builtins.list[str]`
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from portfolio.application.ports.feedback import (
    FeedbackSubmissionRecord,
    FeedbackSubmissionRepo,
)
from portfolio.infrastructure.db.models.feedback_submission import FeedbackSubmissionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyFeedbackSubmissionRepo(FeedbackSubmissionRepo):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_record(row: FeedbackSubmissionModel) -> FeedbackSubmissionRecord:
        return FeedbackSubmissionRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            email=row.email,
            kind=row.kind,
            severity=row.severity,
            description=row.description,
            console_logs=row.console_logs,
            screenshot_url=row.screenshot_url,
            page_url=row.page_url,
            user_agent=row.user_agent,
            status=row.status,
            tags=list(row.tags) if row.tags else [],
            assigned_to=row.assigned_to,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, record: FeedbackSubmissionRecord) -> None:
        row = FeedbackSubmissionModel(
            id=record.id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            email=record.email,
            kind=record.kind,
            severity=record.severity,
            description=record.description,
            console_logs=record.console_logs,
            screenshot_url=record.screenshot_url,
            page_url=record.page_url,
            user_agent=record.user_agent,
            status=record.status,
            tags=record.tags,
            assigned_to=record.assigned_to,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
        self._session.add(row)
        await self._session.flush()

    async def get(self, submission_id: UUID, tenant_id: UUID) -> FeedbackSubmissionRecord | None:
        result = await self._session.execute(
            select(FeedbackSubmissionModel).where(
                FeedbackSubmissionModel.id == submission_id,
                FeedbackSubmissionModel.tenant_id == tenant_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_record(row) if row else None

    async def list(
        self,
        tenant_id: UUID,
        *,
        user_id: UUID | None = None,
        status: str | None = None,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[FeedbackSubmissionRecord], int]:
        # WHY two queries: counting in the same SELECT via window function works
        # but adds a column to every row; with separate count() we keep the
        # data SELECT lean and the planner can optimise each independently.
        base = select(FeedbackSubmissionModel).where(FeedbackSubmissionModel.tenant_id == tenant_id)
        count_q = (
            select(func.count())
            .select_from(FeedbackSubmissionModel)
            .where(
                FeedbackSubmissionModel.tenant_id == tenant_id,
            )
        )
        if user_id is not None:
            base = base.where(FeedbackSubmissionModel.user_id == user_id)
            count_q = count_q.where(FeedbackSubmissionModel.user_id == user_id)
        if status is not None:
            base = base.where(FeedbackSubmissionModel.status == status)
            count_q = count_q.where(FeedbackSubmissionModel.status == status)
        if kind is not None:
            base = base.where(FeedbackSubmissionModel.kind == kind)
            count_q = count_q.where(FeedbackSubmissionModel.kind == kind)

        base = base.order_by(FeedbackSubmissionModel.created_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(base)).scalars().all()
        total = (await self._session.execute(count_q)).scalar_one()
        return [self._to_record(r) for r in rows], int(total)

    async def update(
        self,
        submission_id: UUID,
        tenant_id: UUID,
        *,
        status: str | None = None,
        # WHY ``builtins.list``: this method is named ``list`` (above), so
        # bare ``list[str]`` resolves to the method, not the type.
        tags: builtins.list[str] | None = None,
        assigned_to: UUID | None = None,
    ) -> FeedbackSubmissionRecord | None:
        row = await self._session.get(FeedbackSubmissionModel, submission_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        if status is not None:
            row.status = status
        if tags is not None:
            row.tags = tags
        if assigned_to is not None:
            row.assigned_to = assigned_to
        # Bump updated_at via Python so callers see fresh value without a re-fetch.
        from common.time import utc_now  # type: ignore[import-untyped]

        row.updated_at = utc_now()
        await self._session.flush()
        return self._to_record(row)

    async def delete(self, submission_id: UUID, tenant_id: UUID) -> bool:
        row = await self._session.get(FeedbackSubmissionModel, submission_id)
        if row is None or row.tenant_id != tenant_id:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True
