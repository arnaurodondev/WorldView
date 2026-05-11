"""Mention resolution audit trail repository for nlp_db."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

import common.ids  # type: ignore[import-untyped]
from nlp_pipeline.infrastructure.nlp_db.models import MentionResolutionModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from nlp_pipeline.domain.models import MentionResolution


class MentionResolutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, resolution: MentionResolution) -> None:
        row = MentionResolutionModel(
            resolution_id=common.ids.new_uuid7(),
            mention_id=resolution.mention_id,
            stage=resolution.stage,
            candidate_entity_id=resolution.candidate_entity_id,
            score=resolution.score,
            is_winner=resolution.is_winner,
            resolution_metadata=resolution.metadata,
        )
        self._session.add(row)

    async def add_batch(self, resolutions: list[MentionResolution]) -> None:
        for resolution in resolutions:
            await self.add(resolution)

    async def get_by_mention(self, mention_id: UUID) -> list[MentionResolutionModel]:
        result = await self._session.execute(
            select(MentionResolutionModel)
            .where(MentionResolutionModel.mention_id == mention_id)
            .order_by(MentionResolutionModel.stage),
        )
        return list(result.scalars().all())
