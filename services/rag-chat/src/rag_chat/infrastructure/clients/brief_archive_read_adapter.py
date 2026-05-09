"""BriefArchiveReadAdapter — session-factory-backed read adapter for tool handlers (PLAN-0081 Wave A).

WHY this exists: ToolExecutorFactory is a startup-time singleton. BriefArchiveRepository
needs a per-call AsyncSession. This adapter wraps the read_factory (Callable[[], AsyncSession])
so that get_morning_brief can read user_briefs without acquiring a UnitOfWork (R27).

WHY R27 compliant: each method creates a fresh read-only session, executes the read,
and closes the session in a finally block. No write operations are performed here.

WHY lazy import of BriefArchiveRepository inside methods (not at module level):
R25 requires that application layer does not import from infrastructure. Since this file IS
in infrastructure, it can import BriefArchiveRepository. However, we use a lazy import to
avoid circular dependencies at module load time (this module is imported by app.py before
the DB session factory is fully wired).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from rag_chat.application.ports.brief_archive import UserBriefRecord

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BriefArchiveReadAdapter:
    """BriefArchivePort-compatible read adapter backed by a read session factory.

    Only implements get_latest (the only method needed by get_morning_brief).
    All other methods return safe empty values (NullBriefArchive semantics).

    R27: creates read-only sessions via the read replica factory — never writes.
    R9: all methods catch exceptions and return empty values — never raise to caller.
    """

    def __init__(self, read_factory: Callable[[], AsyncSession]) -> None:
        # WHY store factory (not a single session): each call must create a fresh
        # session so that read isolation is maintained across concurrent tool calls.
        # Reusing a single session would cause asyncio concurrency issues.
        self._read_factory = read_factory

    async def save(self, brief: UserBriefRecord) -> None:
        # WHY no-op: this adapter is read-only (R27). Tool handlers must never
        # write briefs — they are read-only consumers of the archive.
        log.warning(
            "brief_archive_read_adapter_save_noop",
            reason="read-only adapter — tool handlers must not write briefs",
        )

    async def get_latest(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        limit: int = 2,
    ) -> list[UserBriefRecord]:
        """Create a read session, fetch the latest briefs, then close the session.

        WHY create-and-close per call: ToolExecutorFactory is a long-lived singleton
        with no SQLAlchemy session lifecycle management. Each call must create and
        close its own session to avoid holding open connections unnecessarily.

        Returns [] on any error (R9 safe degradation).
        """
        # WHY lazy import inside method: avoids circular imports at module load time
        # (app.py imports this adapter before the DB models are fully registered).
        from rag_chat.infrastructure.db.repositories.brief_archive_repository import BriefArchiveRepository

        session = self._read_factory()
        try:
            repo = BriefArchiveRepository(session=session)
            return await repo.get_latest(
                user_id=user_id,
                tenant_id=tenant_id,
                brief_type=brief_type,
                limit=limit,
            )
        except Exception as exc:
            log.warning(
                "brief_archive_read_adapter_error",
                method="get_latest",
                error=str(exc),
            )
            return []
        finally:
            # WHY always close: prevent session/connection leaks even on error paths.
            await session.close()

    async def get_history(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        page: int,
        page_size: int,
    ) -> tuple[list[UserBriefRecord], int]:
        # WHY not implemented: tool handlers only need get_latest.
        # Returning empty tuple satisfies the BriefArchivePort Protocol contract.
        return [], 0

    async def get_by_id(self, brief_id: UUID) -> UserBriefRecord | None:
        # WHY not implemented: tool handlers only need get_latest.
        return None
