"""BriefFeedbackUseCase — persist user reactions to morning brief bullets and briefs.

PLAN-0066 Wave C T-W10-C-02.

WHY BriefFeedbackPort (not AsyncSession): R25 requires application layer to depend on
port interfaces, not infrastructure ORM models. BriefFeedbackPort is the Protocol
defined in application/ports/brief_feedback.py; BriefFeedbackRepository (infrastructure/)
is the concrete implementation injected at DI time.

WHY ownership check (brief_owned_by before insert): prevents IDOR (Insecure Direct
Object Reference). Without the check, a user who knows another user's brief UUID could
post feedback to it.

WHY structlog only: STANDARDS.md §5 — no stdlib logging.

WHY utc_now() (not datetime.utcnow()): R11 — all timestamps must be UTC-aware.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from common.ids import new_uuid7  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from rag_chat.domain.errors import BriefNotFoundError

if TYPE_CHECKING:
    from rag_chat.application.ports.brief_feedback import BriefFeedbackPort

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BriefFeedbackUseCase:
    """Persist user feedback reactions to morning brief bullets or whole briefs.

    Two entry points:
      submit_bullet_feedback — reaction to a specific bullet (scope='bullet')
      submit_brief_feedback  — reaction to the whole brief (scope='brief')

    Both methods validate brief ownership before inserting the feedback row.
    """

    def __init__(self, feedback: BriefFeedbackPort) -> None:
        # WHY BriefFeedbackPort: R25 — application layer depends on ports, not
        # infrastructure. BriefFeedbackRepository is injected from api/dependencies.py.
        self._feedback = feedback

    async def submit_bullet_feedback(
        self,
        brief_id: UUID,
        user_id: UUID,
        section_idx: int,
        bullet_idx: int,
        reaction: str,
    ) -> tuple[UUID, datetime]:
        """Validate brief ownership, then insert a bullet-scoped feedback row."""
        await self._assert_brief_owned_by(brief_id=brief_id, user_id=user_id)

        feedback_id = new_uuid7()  # R10: app-side UUIDv7
        now = utc_now()  # R11: UTC-aware timestamp
        await self._feedback.save_feedback(
            feedback_id=feedback_id,
            brief_id=brief_id,
            user_id=user_id,
            scope="bullet",
            section_idx=section_idx,
            bullet_idx=bullet_idx,
            reaction=reaction,
            created_at=now,
        )

        log.info(  # type: ignore[no-any-return]
            "brief_bullet_feedback_submitted",
            brief_id=str(brief_id),
            user_id=str(user_id),
            section_idx=section_idx,
            bullet_idx=bullet_idx,
            reaction=reaction,
            feedback_id=str(feedback_id),
        )

        return feedback_id, now

    async def submit_brief_feedback(
        self,
        brief_id: UUID,
        user_id: UUID,
        reaction: str,
    ) -> tuple[UUID, datetime]:
        """Validate brief ownership, then insert a brief-level feedback row."""
        await self._assert_brief_owned_by(brief_id=brief_id, user_id=user_id)

        feedback_id = new_uuid7()  # R10
        now = utc_now()  # R11
        await self._feedback.save_feedback(
            feedback_id=feedback_id,
            brief_id=brief_id,
            user_id=user_id,
            scope="brief",
            section_idx=None,
            bullet_idx=None,
            reaction=reaction,
            created_at=now,
        )

        log.info(  # type: ignore[no-any-return]
            "brief_feedback_submitted",
            brief_id=str(brief_id),
            user_id=str(user_id),
            reaction=reaction,
            feedback_id=str(feedback_id),
        )

        return feedback_id, now

    async def _assert_brief_owned_by(self, brief_id: UUID, user_id: UUID) -> None:
        """Raise BriefNotFoundError if brief_id doesn't exist or belongs to another user."""
        owned = await self._feedback.brief_owned_by(brief_id=brief_id, user_id=user_id)
        if not owned:
            raise BriefNotFoundError(f"Brief {brief_id} not found for user {user_id}")
