"""Unit tests for CreateSourceUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.create_source import CreateSourceResult, CreateSourceUseCase

import common.ids
import common.time

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


def _make_uow(source_model: MagicMock | None = None) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    model = source_model or _make_source_model()
    uow.sources = AsyncMock(create=AsyncMock(return_value=model))
    return uow


class TestCreateSourceUseCase:
    async def test_happy_path_returns_result(self) -> None:
        model = _make_source_model(name="news", source_type="newsapi", enabled=True)
        uow = _make_uow(model)
        use_case = CreateSourceUseCase(uow)

        result = await use_case.execute(name="news", source_type="newsapi", config={"key": "v"})

        assert isinstance(result, CreateSourceResult)
        assert result.name == "news"
        assert result.source_type == "newsapi"
        assert result.enabled is True
        assert result.id == model.id

    async def test_commit_called_once(self) -> None:
        uow = _make_uow()
        use_case = CreateSourceUseCase(uow)

        await use_case.execute(name="s", source_type="eodhd", config={})

        uow.commit.assert_called_once()

    async def test_sources_create_called_with_correct_args(self) -> None:
        uow = _make_uow()
        use_case = CreateSourceUseCase(uow)

        await use_case.execute(name="test", source_type="finnhub", config={"x": 1}, enabled=False)

        uow.sources.create.assert_called_once_with(
            name="test",
            source_type="finnhub",
            config={"x": 1},
            enabled=False,
        )

    async def test_enabled_defaults_to_true(self) -> None:
        model = _make_source_model(enabled=True)
        uow = _make_uow(model)
        use_case = CreateSourceUseCase(uow)

        result = await use_case.execute(name="s", source_type="eodhd", config={})

        assert result.enabled is True

    async def test_result_id_matches_model(self) -> None:
        model = _make_source_model()
        uow = _make_uow(model)
        use_case = CreateSourceUseCase(uow)

        result = await use_case.execute(name="s", source_type="eodhd", config={})

        assert result.id == model.id

    async def test_repository_error_propagates(self) -> None:
        uow = AsyncMock()
        uow.__aenter__ = AsyncMock(return_value=uow)
        uow.__aexit__ = AsyncMock(return_value=None)
        uow.sources = AsyncMock(create=AsyncMock(side_effect=RuntimeError("DB error")))

        use_case = CreateSourceUseCase(uow)

        with pytest.raises(RuntimeError, match="DB error"):
            await use_case.execute(name="s", source_type="eodhd", config={})
