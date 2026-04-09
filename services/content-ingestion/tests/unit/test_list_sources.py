"""Unit tests for ListSourcesUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.list_sources import ListSourcesUseCase, SourceListItem

import common.ids
import common.time

pytestmark = pytest.mark.unit


def _make_source_model(
    *,
    name: str = "src",
    source_type: str = "eodhd",
    enabled: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.id = common.ids.new_uuid7()
    m.name = name
    m.source_type = source_type
    m.enabled = enabled
    return m


def _make_adapter_state(source_id: object, *, last_run_at: object = None) -> MagicMock:
    s = MagicMock()
    s.source_id = source_id
    s.last_run_at = last_run_at or common.time.utc_now()
    return s


def _make_uow(
    sources: list[MagicMock] | None = None,
    states: list[MagicMock] | None = None,
) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.sources = AsyncMock(get_all=AsyncMock(return_value=sources or []))
    uow.adapter_state = AsyncMock(get_all=AsyncMock(return_value=states or []))
    return uow


class TestListSourcesUseCase:
    async def test_empty_list_returns_empty(self) -> None:
        uow = _make_uow()
        use_case = ListSourcesUseCase(uow)

        result = await use_case.execute()

        assert result == []

    async def test_single_source_without_adapter_state(self) -> None:
        src = _make_source_model(name="eodhd-feed")
        uow = _make_uow(sources=[src], states=[])
        use_case = ListSourcesUseCase(uow)

        result = await use_case.execute()

        assert len(result) == 1
        item = result[0]
        assert isinstance(item, SourceListItem)
        assert item.name == "eodhd-feed"
        assert item.last_fetch_at is None

    async def test_source_with_adapter_state(self) -> None:
        src = _make_source_model()
        ts = common.time.utc_now()
        state = _make_adapter_state(src.id, last_run_at=ts)
        uow = _make_uow(sources=[src], states=[state])
        use_case = ListSourcesUseCase(uow)

        result = await use_case.execute()

        assert result[0].last_fetch_at == ts

    async def test_multiple_sources_with_mixed_state(self) -> None:
        s1 = _make_source_model(name="a")
        s2 = _make_source_model(name="b")
        state1 = _make_adapter_state(s1.id)
        # s2 has no state
        uow = _make_uow(sources=[s1, s2], states=[state1])
        use_case = ListSourcesUseCase(uow)

        result = await use_case.execute()

        assert len(result) == 2
        names = {r.name: r for r in result}
        assert names["a"].last_fetch_at is not None
        assert names["b"].last_fetch_at is None

    async def test_state_matched_by_source_id(self) -> None:
        s1 = _make_source_model(name="alpha")
        s2 = _make_source_model(name="beta")
        # Only provide state for s2 (not s1)
        state2 = _make_adapter_state(s2.id)
        uow = _make_uow(sources=[s1, s2], states=[state2])
        use_case = ListSourcesUseCase(uow)

        result = await use_case.execute()

        result_map = {r.name: r for r in result}
        assert result_map["alpha"].last_fetch_at is None
        assert result_map["beta"].last_fetch_at is not None

    async def test_result_fields_populated(self) -> None:
        src = _make_source_model(name="fin", source_type="finnhub", enabled=False)
        uow = _make_uow(sources=[src])
        use_case = ListSourcesUseCase(uow)

        result = await use_case.execute()

        item = result[0]
        assert item.id == src.id
        assert item.source_type == "finnhub"
        assert item.enabled is False
