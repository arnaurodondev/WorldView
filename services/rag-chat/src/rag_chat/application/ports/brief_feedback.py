"""BriefFeedbackPort — application-layer interface for brief feedback persistence.

PLAN-0066 Wave C T-W10-C-02 (R25 fix: extracted from use case to separate port).

WHY Protocol (not ABC): same pattern as BriefArchivePort / thread_repository in this
service. runtime_checkable lets tests use isinstance() checks without concrete subclass.

WHY separate port from BriefArchivePort: feedback writes are logically distinct from
brief archive reads. Keeping them separate allows read/write session injection to be
scoped correctly (R27) at the DI layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class BriefFeedbackPort(Protocol):
    """Port for persisting per-bullet and per-brief user reactions."""

    async def brief_owned_by(self, brief_id: UUID, user_id: UUID) -> bool:
        """Return True iff brief_id exists and belongs to user_id.

        Used for IDOR protection before inserting feedback rows. Returns False
        (not raises) so the use case can raise a domain error with full context.
        """
        ...

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
        """Insert a feedback row. Does NOT commit — caller's UoW commits."""
        ...
