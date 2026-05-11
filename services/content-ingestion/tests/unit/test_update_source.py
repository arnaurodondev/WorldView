"""Unit tests for UpdateSourceUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.update_source import UpdateSourceResult, UpdateSourceUseCase

import common.ids

pytestmark = pytest.mark.unit


def _make_source_model(
    *,
    name: str = "my-source",
    source_type: str = "eodhd",
    enabled: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.id = common.ids.new_uuid7()
    m.name = name
    m.source_type = source_type
    m.enabled = enabled
    return m


def _make_uow(
    existing: MagicMock | None = None,
    updated: MagicMock | None = None,
) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    get_result = existing  # if None → source not found
    update_result = updated or existing or _make_source_model()
    uow.sources = AsyncMock(
        get_by_id=AsyncMock(return_value=get_result),
        update=AsyncMock(return_value=update_result),
    )
    return uow


class TestUpdateSourceUseCase:
    async def test_source_not_found_returns_none(self) -> None:
        uow = _make_uow(existing=None)
        use_case = UpdateSourceUseCase(uow)

        result = await use_case.execute(common.ids.new_uuid7(), name="new")

        assert result is None

    async def test_happy_path_returns_dto(self) -> None:
        model = _make_source_model(name="old")
        updated = _make_source_model(name="new-name")
        uow = _make_uow(existing=model, updated=updated)
        use_case = UpdateSourceUseCase(uow)

        result = await use_case.execute(model.id, name="new-name")

        assert isinstance(result, UpdateSourceResult)
        assert result.name == "new-name"

    async def test_no_updates_returns_existing_source(self) -> None:
        model = _make_source_model(name="same")
        uow = _make_uow(existing=model)
        use_case = UpdateSourceUseCase(uow)

        result = await use_case.execute(model.id)  # no kwargs

        assert result is not None
        assert result.name == "same"
        # update() should NOT be called when no kwargs passed
        uow.sources.update.assert_not_called()

    async def test_commit_called_when_source_found(self) -> None:
        model = _make_source_model()
        uow = _make_uow(existing=model)
        use_case = UpdateSourceUseCase(uow)

        await use_case.execute(model.id, enabled=False)

        uow.commit.assert_called_once()

    async def test_commit_not_called_when_source_not_found(self) -> None:
        uow = _make_uow(existing=None)
        use_case = UpdateSourceUseCase(uow)

        await use_case.execute(common.ids.new_uuid7())

        uow.commit.assert_not_called()

    async def test_update_called_with_correct_kwargs(self) -> None:
        source_id = common.ids.new_uuid7()
        model = _make_source_model()
        model.id = source_id
        uow = _make_uow(existing=model)
        use_case = UpdateSourceUseCase(uow)

        await use_case.execute(source_id, enabled=False, name="updated")

        uow.sources.update.assert_called_once_with(source_id, enabled=False, name="updated")

    async def test_result_fields_map_from_updated_model(self) -> None:
        original = _make_source_model(name="orig", source_type="finnhub", enabled=True)
        new_model = _make_source_model(name="renamed", source_type="finnhub", enabled=False)
        uow = _make_uow(existing=original, updated=new_model)
        use_case = UpdateSourceUseCase(uow)

        result = await use_case.execute(original.id, name="renamed", enabled=False)

        assert result is not None
        assert result.name == "renamed"
        assert result.enabled is False
        assert result.source_type == "finnhub"
