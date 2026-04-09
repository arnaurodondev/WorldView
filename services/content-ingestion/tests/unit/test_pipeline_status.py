"""Unit tests for GetPipelineStatusUseCase."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.pipeline_status import GetPipelineStatusUseCase, PipelineStatus

import common.ids
import common.time

pytestmark = pytest.mark.unit


def _make_source_model(name: str = "src") -> MagicMock:
    m = MagicMock()
    m.id = common.ids.new_uuid7()
    m.name = name
    return m


def _make_adapter_state(source_id: object) -> MagicMock:
    s = MagicMock()
    s.source_id = source_id
    s.last_run_at = common.time.utc_now()
    s.error_count = 0
    return s


def _make_uow(
    sources: list[MagicMock] | None = None,
    states: list[MagicMock] | None = None,
    fetch_count: int = 0,
    outbox_pending: int = 0,
    dlq_count: int = 0,
) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.sources = AsyncMock(get_all=AsyncMock(return_value=sources or []))
    uow.adapter_state = AsyncMock(get_all=AsyncMock(return_value=states or []))
    uow.fetch_logs = AsyncMock(count_by_source_since=AsyncMock(return_value=fetch_count))
    uow.outbox = AsyncMock(count_pending=AsyncMock(return_value=outbox_pending))
    uow.dlq = AsyncMock(count_failed=AsyncMock(return_value=dlq_count))
    return uow


class TestGetPipelineStatusUseCase:
    async def test_empty_pipeline(self) -> None:
        uow = _make_uow()
        use_case = GetPipelineStatusUseCase(uow)

        status = await use_case.execute()

        assert isinstance(status, PipelineStatus)
        assert status.sources == []
        assert status.outbox_pending == 0
        assert status.dlq_count == 0

    async def test_aggregates_outbox_and_dlq(self) -> None:
        uow = _make_uow(outbox_pending=5, dlq_count=2)
        use_case = GetPipelineStatusUseCase(uow)

        status = await use_case.execute()

        assert status.outbox_pending == 5
        assert status.dlq_count == 2

    async def test_source_without_adapter_state(self) -> None:
        src = _make_source_model("feed")
        uow = _make_uow(sources=[src], states=[])
        use_case = GetPipelineStatusUseCase(uow)

        status = await use_case.execute()

        assert len(status.sources) == 1
        info = status.sources[0]
        assert info.name == "feed"
        assert info.last_fetch_at is None
        assert info.errors_24h == 0

    async def test_source_with_adapter_state(self) -> None:
        src = _make_source_model("feed")
        state = _make_adapter_state(src.id)
        state.error_count = 3
        uow = _make_uow(sources=[src], states=[state], fetch_count=42)
        use_case = GetPipelineStatusUseCase(uow)

        status = await use_case.execute()

        info = status.sources[0]
        assert info.last_fetch_at is not None
        assert info.errors_24h == 3
        assert info.articles_fetched_24h == 42

    async def test_multiple_sources(self) -> None:
        s1 = _make_source_model("a")
        s2 = _make_source_model("b")
        uow = _make_uow(sources=[s1, s2])
        use_case = GetPipelineStatusUseCase(uow)

        status = await use_case.execute()

        assert len(status.sources) == 2

    async def test_fetch_count_queried_per_source(self) -> None:
        s1 = _make_source_model("a")
        s2 = _make_source_model("b")
        uow = _make_uow(sources=[s1, s2], fetch_count=10)
        use_case = GetPipelineStatusUseCase(uow)

        await use_case.execute()

        # count_by_source_since called once per source
        assert uow.fetch_logs.count_by_source_since.call_count == 2

    async def test_state_matched_by_source_id(self) -> None:
        s1 = _make_source_model("alpha")
        s2 = _make_source_model("beta")
        state_for_s2 = _make_adapter_state(s2.id)
        state_for_s2.error_count = 7
        uow = _make_uow(sources=[s1, s2], states=[state_for_s2])
        use_case = GetPipelineStatusUseCase(uow)

        status = await use_case.execute()

        info_map = {i.name: i for i in status.sources}
        assert info_map["alpha"].errors_24h == 0
        assert info_map["beta"].errors_24h == 7
