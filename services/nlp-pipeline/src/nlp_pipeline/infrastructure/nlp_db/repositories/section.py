"""Section repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import SectionModel

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import Section


class SectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, section: Section) -> None:
        row = SectionModel(
            section_id=section.section_id,
            doc_id=section.doc_id,
            section_index=section.section_index,
            section_type=section.section_type,
            title=section.title,
            speaker=section.speaker,
            char_start=section.char_start,
            char_end=section.char_end,
            token_count=section.token_count,
        )
        self._session.add(row)

    async def add_batch(self, sections: list[Section]) -> None:
        for section in sections:
            await self.add(section)

    async def get_by_doc(self, doc_id: UUID) -> list[SectionModel]:
        result = await self._session.execute(
            select(SectionModel).where(SectionModel.doc_id == doc_id).order_by(SectionModel.section_index)
        )
        return list(result.scalars().all())

    async def get(self, section_id: UUID) -> SectionModel | None:
        result = await self._session.execute(select(SectionModel).where(SectionModel.section_id == section_id))
        return result.scalar_one_or_none()  # type: ignore[no-any-return]

    def _new_id(self) -> UUID:
        return common.ids.new_uuid7()
