"""Section repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nlp_pipeline.infrastructure.nlp_db.models import SectionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import Section


class SectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, section: Section) -> None:
        stmt = (
            pg_insert(SectionModel)
            .values(
                section_id=section.section_id,
                doc_id=section.doc_id,
                section_index=section.section_index,
                section_type=section.section_type,
                title=section.title,
                speaker=section.speaker,
                char_start=section.char_start,
                char_end=section.char_end,
                token_count=section.token_count,
                # PLAN-0086 Wave C-1: tenant isolation — NULL = public/global content.
                tenant_id=section.tenant_id,
            )
            .on_conflict_do_nothing(index_elements=["section_id"])
        )
        await self._session.execute(stmt)

    async def add_batch(self, sections: list[Section]) -> None:
        for section in sections:
            await self.add(section)

    async def get_by_doc(self, doc_id: UUID) -> list[SectionModel]:
        result = await self._session.execute(
            select(SectionModel).where(SectionModel.doc_id == doc_id).order_by(SectionModel.section_index),
        )
        return list(result.scalars().all())

    async def get(self, section_id: UUID) -> SectionModel | None:
        result = await self._session.execute(select(SectionModel).where(SectionModel.section_id == section_id))
        return result.scalar_one_or_none()  # type: ignore[no-any-return]
