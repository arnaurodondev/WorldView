"""BriefFeedbackRepository — SQLAlchemy adapter for brief feedback persistence.

PLAN-0066 Wave C T-W10-C-02 (R25 fix: ORM model imports live in infrastructure/).

Implements BriefFeedbackPort from application/ports/brief_feedback.py. This is the
ONLY module outside the ORM model file that imports UserBriefModel / BriefFeedbackModel
— the application layer never sees these classes directly (R25 / LAYER-APP-ISOLATION).

WHY brief_owned_by returns bool (not raises): the use case owns the decision to raise
BriefNotFoundError. The repository stays dumb: returns True/False based on the DB query.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from rag_chat.infrastructure.db.models.user_brief import BriefFeedbackModel, UserBriefModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class BriefFeedbackRepository:
    """Infrastructure adapter: brief feedback persistence via SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def brief_owned_by(self, brief_id: UUID, user_id: UUID) -> bool:
        """Return True iff brief_id exists and user_id matches."""
        result = await self._session.execute(
            select(UserBriefModel.id).where(
                UserBriefModel.id == brief_id,
                UserBriefModel.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def save_feedback(
        self,
        *,
        feedback_id: UUID,
        brief_id: UUID,
        user_id: UUID,
        scope: str,
        section_idx: int | None,
        bullet_idx: int | None,
        reaction: str,
        created_at: datetime,
    ) -> None:
        """Add a BriefFeedbackModel row to the session. Caller commits."""
        fb = BriefFeedbackModel(
            id=feedback_id,
            brief_id=brief_id,
            user_id=user_id,
            scope=scope,
            section_idx=section_idx,
            bullet_idx=bullet_idx,
            reaction=reaction,
            created_at=created_at,
        )
        self._session.add(fb)
