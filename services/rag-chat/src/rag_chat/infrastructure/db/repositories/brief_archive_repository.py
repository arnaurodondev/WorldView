"""SQLAlchemy adapter implementing BriefArchivePort (PLAN-0066 Wave B T-W10-B-01).

WHY this file lives in infrastructure/: the adapter depends on SQLAlchemy
(infrastructure concern). The application layer only ever imports
BriefArchivePort (a Protocol) — never this concrete class. This preserves the
dependency-inversion rule (R25): use cases depend on the port, not the adapter.

WHY ON CONFLICT DO NOTHING for save(): morning briefs are idempotent — if the
upstream retry logic re-triggers a generation with the same (user_id, generated_at,
brief_type), we silently discard the duplicate rather than raising an integrity error
that would propagate up and mask the original success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from rag_chat.application.ports.brief_archive import UserBriefRecord
from rag_chat.infrastructure.db.models.user_brief import UserBriefModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class BriefArchiveRepository:
    """SQLAlchemy adapter implementing BriefArchivePort.

    Lives in infrastructure/ — never import from the application layer to avoid
    inverting the dependency arrow (R25). The DI container wires this adapter
    into use cases via the BriefArchivePort Protocol.

    WHY AsyncSession (not UnitOfWork): the session is provided by the DI
    container's UoW, which calls commit() AFTER the use case returns. The
    repository MUST NOT call commit() itself (R26).
    """

    def __init__(self, session: AsyncSession) -> None:
        # WHY store raw session (not UoW): this repository is a pure adapter —
        # it wraps a single SQLAlchemy AsyncSession. Transaction management
        # (commit/rollback) belongs to the use case layer via the UoW.
        self._session = session

    async def save(self, brief: UserBriefRecord) -> None:
        """Insert a new brief row with ON CONFLICT DO NOTHING for idempotency.

        WHY INSERT ... ON CONFLICT DO NOTHING (not session.add()): session.add()
        raises IntegrityError on duplicate (user_id, generated_at, brief_type)
        which would be swallowed by asyncio.shield in the use case — but would
        also invalidate the SQLAlchemy session. Using insert().on_conflict_do_nothing()
        keeps the session clean on duplicate inserts.

        R26: does NOT call commit(). The use case calls uow.commit() after this
        method returns.
        """
        stmt = (
            insert(UserBriefModel)
            .values(
                id=brief.id,
                user_id=brief.user_id,
                tenant_id=brief.tenant_id,
                brief_type=brief.brief_type,
                entity_id=brief.entity_id,
                generated_at=brief.generated_at,
                headline=brief.headline,
                lead=brief.lead,
                sections_json=brief.sections_json,
                citations_json=brief.citations_json,
                confidence=brief.confidence,
                source_version=brief.source_version,
            )
            .on_conflict_do_nothing()
        )
        await self._session.execute(stmt)
        # WHY no flush here: the UoW controls flushing. Explicit flush in a
        # repository method breaks the "one flush per transaction" invariant
        # and can cause partial-write confusion under retry conditions.
        log.debug(  # type: ignore[no-any-return]
            "brief_archive_save",
            brief_id=str(brief.id),
            user_id=str(brief.user_id),
            brief_type=brief.brief_type,
        )

    async def get_latest(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        limit: int = 2,
    ) -> list[UserBriefRecord]:
        """Return the most-recent ``limit`` briefs, ordered DESC by generated_at.

        WHY limit=2 default: the common caller (cache-check logic) needs the
        newest 2 rows to decide whether to regenerate. Using a LIMIT keeps the
        query an index-only scan on (user_id, tenant_id, brief_type, generated_at).
        """
        result = await self._session.execute(
            select(UserBriefModel)
            .where(UserBriefModel.user_id == user_id)
            .where(UserBriefModel.tenant_id == tenant_id)
            .where(UserBriefModel.brief_type == brief_type)
            .order_by(UserBriefModel.generated_at.desc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [self._to_record(m) for m in models]

    async def get_history(
        self,
        user_id: UUID,
        tenant_id: UUID,
        brief_type: str,
        page: int,
        page_size: int,
    ) -> tuple[list[UserBriefRecord], int]:
        """Return paginated brief history and the total row count.

        WHY two queries (count + data) instead of COUNT(*) OVER(): the window
        function approach works but forces the DB to materialise the full result
        set before pagination. For brief history (typically ≤100 rows) the
        two-query approach is simpler and easier to explain in code review.

        page is 0-based (page=0 returns the first page_size rows).
        """
        # ── Count query ────────────────────────────────────────────────────────
        count_result = await self._session.execute(
            select(func.count())
            .select_from(UserBriefModel)
            .where(UserBriefModel.user_id == user_id)
            .where(UserBriefModel.tenant_id == tenant_id)
            .where(UserBriefModel.brief_type == brief_type)
        )
        total: int = count_result.scalar_one()

        # ── Data query ─────────────────────────────────────────────────────────
        result = await self._session.execute(
            select(UserBriefModel)
            .where(UserBriefModel.user_id == user_id)
            .where(UserBriefModel.tenant_id == tenant_id)
            .where(UserBriefModel.brief_type == brief_type)
            .order_by(UserBriefModel.generated_at.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
        models = result.scalars().all()
        return [self._to_record(m) for m in models], total

    async def get_latest_entity_brief(
        self,
        entity_id: UUID,
        limit: int = 1,
    ) -> list[UserBriefRecord]:
        """Return the most-recent entity-scoped briefs for ``entity_id``.

        WHY (AI-brief-flag fix, 2026-06-19): mirrors the exact predicate the
        ``GetAiBriefFlagUseCase`` uses (``brief_type='entity' AND
        entity_id=:id``) so callers can do a cross-user freshness/idempotency
        check against the SAME rows the screener ``has_ai_brief`` flag reads.
        Ordered DESC by ``generated_at`` so callers can read element [0] as the
        newest.
        """
        result = await self._session.execute(
            select(UserBriefModel)
            .where(UserBriefModel.brief_type == "entity")
            .where(UserBriefModel.entity_id == entity_id)
            .order_by(UserBriefModel.generated_at.desc())
            .limit(limit)
        )
        models = result.scalars().all()
        return [self._to_record(m) for m in models]

    async def get_by_id(self, brief_id: UUID) -> UserBriefRecord | None:
        """Look up a single brief by primary key.

        WHY scalar_one_or_none(): avoids MultipleResultsFound (impossible by PK
        uniqueness, but explicit is better than implicit).
        Returns None when the brief does not exist.
        """
        result = await self._session.execute(select(UserBriefModel).where(UserBriefModel.id == brief_id))
        model = result.scalar_one_or_none()
        return self._to_record(model) if model else None

    def _to_record(self, model: UserBriefModel) -> UserBriefRecord:
        """Convert a UserBriefModel ORM row to a UserBriefRecord domain DTO.

        WHY defensive ``or []`` on JSONB columns: Postgres JSONB columns can
        return None when the server_default hasn't been applied (e.g. direct SQL
        insert without the default). The application contract requires list, not
        None, so we normalise here rather than in every caller.
        """
        return UserBriefRecord(
            id=model.id,
            user_id=model.user_id,
            tenant_id=model.tenant_id,
            brief_type=model.brief_type,
            entity_id=model.entity_id,
            generated_at=model.generated_at,
            headline=model.headline,
            lead=model.lead,
            sections_json=model.sections_json or [],
            citations_json=model.citations_json or [],
            confidence=model.confidence,
            source_version=model.source_version,
        )
