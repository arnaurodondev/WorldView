"""Unit tests for TriggerSourceUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.trigger_source import TriggerResult, TriggerSourceUseCase

import common.ids
import common.time

pytestmark = pytest.mark.unit


def _make_source_model(source_type: str = "eodhd") -> MagicMock:
    m = MagicMock()
    m.id = common.ids.new_uuid7()
    m.name = "test-source"
    m.source_type = source_type
    m.enabled = True
    m.config = {}
    m.created_at = common.time.utc_now()
    return m


def _make_uow(source_model: MagicMock | None = None) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.sources = AsyncMock(get_by_id=AsyncMock(return_value=source_model))
    uow.tasks = AsyncMock(add=AsyncMock())
    return uow


class TestTriggerSourceUseCase:
    async def test_source_not_found_returns_none(self) -> None:
        uow = _make_uow(source_model=None)
        use_case = TriggerSourceUseCase(uow)

        result = await use_case.execute(common.ids.new_uuid7())

        assert result is None

    async def test_happy_path_returns_result_dto(self) -> None:
        model = _make_source_model()
        uow = _make_uow(source_model=model)
        use_case = TriggerSourceUseCase(uow)

        result = await use_case.execute(model.id)

        assert isinstance(result, TriggerResult)
        assert result.source_id == model.id
        assert result.task_id is not None

    async def test_task_added_to_repository(self) -> None:
        model = _make_source_model()
        uow = _make_uow(source_model=model)
        use_case = TriggerSourceUseCase(uow)

        await use_case.execute(model.id)

        uow.tasks.add.assert_called_once()

    async def test_commit_called_when_source_found(self) -> None:
        model = _make_source_model()
        uow = _make_uow(source_model=model)
        use_case = TriggerSourceUseCase(uow)

        await use_case.execute(model.id)

        uow.commit.assert_called_once()

    async def test_commit_not_called_when_not_found(self) -> None:
        uow = _make_uow(source_model=None)
        use_case = TriggerSourceUseCase(uow)

        await use_case.execute(common.ids.new_uuid7())

        uow.commit.assert_not_called()

    async def test_all_valid_source_types(self) -> None:
        """Each SourceType enum value must be constructible from the trigger path."""
        for st in ("eodhd", "sec_edgar", "finnhub", "newsapi", "manual"):
            model = _make_source_model(source_type=st)
            uow = _make_uow(source_model=model)
            use_case = TriggerSourceUseCase(uow)

            result = await use_case.execute(model.id)

            assert result is not None, f"Expected result for source_type={st}"

    async def test_result_task_id_differs_each_invocation(self) -> None:
        """Each trigger creates a new UUIDv7 task ID."""
        model = _make_source_model()

        uow1 = _make_uow(source_model=model)
        uow2 = _make_uow(source_model=model)
        r1 = await TriggerSourceUseCase(uow1).execute(model.id)
        r2 = await TriggerSourceUseCase(uow2).execute(model.id)

        assert r1 is not None and r2 is not None
        assert r1.task_id != r2.task_id
