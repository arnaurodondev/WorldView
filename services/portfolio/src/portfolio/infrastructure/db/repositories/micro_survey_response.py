"""SQLAlchemy implementation of ``MicroSurveyRepo``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from portfolio.application.ports.feedback import MicroSurveyRecord, MicroSurveyRepo
from portfolio.infrastructure.db.models.micro_survey_response import MicroSurveyResponseModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyMicroSurveyRepo(MicroSurveyRepo):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: MicroSurveyRecord) -> None:
        row = MicroSurveyResponseModel(
            id=record.id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
            survey_key=record.survey_key,
            response=record.response,
            comment=record.comment,
            created_at=record.created_at,
        )
        self._session.add(row)
        await self._session.flush()
