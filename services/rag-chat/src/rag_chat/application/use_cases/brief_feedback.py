"""BriefFeedbackUseCase — persist user reactions to morning brief bullets and briefs.

PLAN-0066 Wave C T-W10-C-02.

WHY AsyncSession (not BriefArchivePort): feedback is a write operation that inserts
rows into brief_feedback. There is no read-side port for feedback — it only needs a
session for the INSERT. Using a session directly follows the same pattern as
PersistChatUseCase (which also takes a raw AsyncSession for chat_messages writes).

WHY ownership check (UserBriefModel lookup before insert): prevents a user from
posting feedback to another user's brief by guessing brief UUIDs. The check is a
simple point-lookup on the PK — fast index scan, not a table scan.

WHY structlog only: R10 — no stdlib logging.

WHY utc_now() (not datetime.utcnow()): R11 — all timestamps must be UTC-aware.
datetime.utcnow() returns a naive datetime; utc_now() returns a timezone.utc aware
datetime. The BriefFeedbackModel column is DateTime(timezone=True).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy import select

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from rag_chat.domain.errors import BriefNotFoundError
from rag_chat.infrastructure.db.models.user_brief import BriefFeedbackModel, UserBriefModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BriefFeedbackUseCase:
    """Persist user feedback reactions to morning brief bullets or whole briefs.

    Two entry points:
      submit_bullet_feedback — reaction to a specific bullet (scope='bullet')
      submit_brief_feedback  — reaction to the whole brief (scope='brief')

    Both methods validate that the target brief belongs to the requesting user
    before inserting the feedback row.

    WHY AsyncSession (not UoW): the feedback use case is a focused write adapter —
    it only needs to SELECT (ownership check) and INSERT (feedback row). It does not
    participate in a multi-repository transaction and does not need commit() — the
    API route's UoW calls commit() after the use case returns.
    """

    def __init__(self, session: AsyncSession) -> None:
        # WHY store raw session: same pattern as PersistChatUseCase. The DI container
        # provides the session from the write UoW; commit() is the UoW's responsibility.
        self._session = session

    async def submit_bullet_feedback(
        self,
        brief_id: UUID,
        user_id: UUID,
        section_idx: int,
        bullet_idx: int,
        reaction: str,
    ) -> tuple[UUID, datetime]:
        """Validate brief ownership, then insert a bullet-scoped feedback row.

        Args:
            brief_id:    Primary key of the target brief.
            user_id:     Authenticated user making the request.
            section_idx: 0-based index of the section containing the bullet.
            bullet_idx:  0-based index of the bullet within the section.
            reaction:    "helpful" | "unhelpful" (enforced at the API layer via Literal).

        Returns:
            (feedback_id, created_at) for the inserted row.

        Raises:
            BriefNotFoundError: if the brief does not exist or belongs to another user.
        """
        await self._assert_brief_owned_by(brief_id=brief_id, user_id=user_id)

        now = utc_now()
        fb = BriefFeedbackModel(
            id=new_uuid7(),  # R10: app-side UUIDv7
            brief_id=brief_id,
            user_id=user_id,
            scope="bullet",
            section_idx=section_idx,
            bullet_idx=bullet_idx,
            reaction=reaction,
            created_at=now,  # R11: UTC-aware timestamp from utc_now()
        )
        self._session.add(fb)

        log.info(  # type: ignore[no-any-return]
            "brief_bullet_feedback_submitted",
            brief_id=str(brief_id),
            user_id=str(user_id),
            section_idx=section_idx,
            bullet_idx=bullet_idx,
            reaction=reaction,
            feedback_id=str(fb.id),
        )

        return fb.id, now

    async def submit_brief_feedback(
        self,
        brief_id: UUID,
        user_id: UUID,
        reaction: str,
    ) -> tuple[UUID, datetime]:
        """Validate brief ownership, then insert a brief-level feedback row.

        Args:
            brief_id: Primary key of the target brief.
            user_id:  Authenticated user making the request.
            reaction: "1"-"5" star rating (enforced at API layer via Literal).

        Returns:
            (feedback_id, created_at) for the inserted row.

        Raises:
            BriefNotFoundError: if the brief does not exist or belongs to another user.
        """
        await self._assert_brief_owned_by(brief_id=brief_id, user_id=user_id)

        now = utc_now()
        fb = BriefFeedbackModel(
            id=new_uuid7(),  # R10: app-side UUIDv7
            brief_id=brief_id,
            user_id=user_id,
            scope="brief",
            section_idx=None,
            bullet_idx=None,
            reaction=reaction,
            created_at=now,  # R11: UTC-aware timestamp from utc_now()
        )
        self._session.add(fb)

        log.info(  # type: ignore[no-any-return]
            "brief_feedback_submitted",
            brief_id=str(brief_id),
            user_id=str(user_id),
            reaction=reaction,
            feedback_id=str(fb.id),
        )

        return fb.id, now

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _assert_brief_owned_by(self, brief_id: UUID, user_id: UUID) -> None:
        """Raise BriefNotFoundError if brief_id doesn't exist or belongs to another user.

        WHY check both id AND user_id: prevents IDOR (Insecure Direct Object Reference).
        Without the user_id check, a user who knows another user's brief UUID could post
        feedback to it. The WHERE clause ensures the PK lookup only succeeds when the
        requesting user is the owner.

        WHY scalar_one_or_none(): the query returns at most one row (PK + user_id filter).
        scalar_one() would raise MultipleResultsFound which can never happen here, but
        scalar_one_or_none() clearly signals intent: we expect zero or one result.
        """
        result = await self._session.execute(
            select(UserBriefModel).where(
                UserBriefModel.id == brief_id,
                UserBriefModel.user_id == user_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise BriefNotFoundError(f"Brief {brief_id} not found for user {user_id}")
