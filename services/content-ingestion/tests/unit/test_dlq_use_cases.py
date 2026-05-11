"""Unit tests for DLQ use cases: List, Get, Retry, Resolve."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from content_ingestion.application.use_cases.dlq_list import (
    DLQEntryDTO,
    DLQListResult,
    GetDLQEntryUseCase,
    ListDLQEntriesUseCase,
)
from content_ingestion.application.use_cases.dlq_resolve import ResolveDLQEntryUseCase
from content_ingestion.application.use_cases.dlq_retry import RetryDLQEntryUseCase

import common.ids
import common.time

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dlq_model(*, dlq_id: object = None, status: str = "failed") -> MagicMock:
    m = MagicMock()
    m.dlq_id = dlq_id or common.ids.new_uuid7()
    m.original_event_id = common.ids.new_uuid7()
    m.topic = "content.article.raw.v1"
    m.error_detail = "some error"
    m.status = status
    m.created_at = common.time.utc_now()
    m.resolved_at = None
    m.resolution_note = None
    return m


def _make_read_uow(
    entries: list[MagicMock] | None = None,
    total: int = 0,
    single: MagicMock | None = None,
) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.dlq = AsyncMock(
        list_open=AsyncMock(return_value=(entries or [], total)),
        get_by_id=AsyncMock(return_value=single),
    )
    return uow


def _make_write_uow(*, entry: MagicMock | None = None, new_event_id: object = None) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    new_id = new_event_id or common.ids.new_uuid7()
    uow.dlq = AsyncMock(
        get_by_id=AsyncMock(return_value=entry),
        requeue=AsyncMock(return_value=new_id),
        mark_resolved=AsyncMock(),
    )
    return uow


# ---------------------------------------------------------------------------
# ListDLQEntriesUseCase
# ---------------------------------------------------------------------------


class TestListDLQEntriesUseCase:
    async def test_empty_list(self) -> None:
        uow = _make_read_uow(entries=[], total=0)
        use_case = ListDLQEntriesUseCase(uow)

        result = await use_case.execute()

        assert isinstance(result, DLQListResult)
        assert result.entries == []
        assert result.count == 0

    async def test_returns_mapped_dtos(self) -> None:
        e1 = _make_dlq_model()
        e2 = _make_dlq_model()
        uow = _make_read_uow(entries=[e1, e2], total=2)
        use_case = ListDLQEntriesUseCase(uow)

        result = await use_case.execute()

        assert result.count == 2
        assert len(result.entries) == 2
        assert all(isinstance(e, DLQEntryDTO) for e in result.entries)

    async def test_dto_fields_mapped_correctly(self) -> None:
        model = _make_dlq_model()
        uow = _make_read_uow(entries=[model], total=1)
        use_case = ListDLQEntriesUseCase(uow)

        result = await use_case.execute()

        dto = result.entries[0]
        assert dto.dlq_id == model.dlq_id
        assert dto.original_event_id == model.original_event_id
        assert dto.topic == model.topic
        assert dto.error_detail == model.error_detail
        assert dto.status == model.status
        assert dto.created_at == model.created_at
        assert dto.resolved_at is None
        assert dto.resolution_note is None

    async def test_pagination_args_forwarded(self) -> None:
        uow = _make_read_uow()
        use_case = ListDLQEntriesUseCase(uow)

        await use_case.execute(limit=10, offset=5)

        uow.dlq.list_open.assert_called_once_with(limit=10, offset=5)

    async def test_default_pagination(self) -> None:
        uow = _make_read_uow()
        use_case = ListDLQEntriesUseCase(uow)

        await use_case.execute()

        uow.dlq.list_open.assert_called_once_with(limit=100, offset=0)


# ---------------------------------------------------------------------------
# GetDLQEntryUseCase
# ---------------------------------------------------------------------------


class TestGetDLQEntryUseCase:
    async def test_entry_not_found_returns_none(self) -> None:
        uow = _make_read_uow(single=None)
        use_case = GetDLQEntryUseCase(uow)

        result = await use_case.execute(common.ids.new_uuid7())

        assert result is None

    async def test_entry_found_returns_dto(self) -> None:
        model = _make_dlq_model()
        uow = _make_read_uow(single=model)
        use_case = GetDLQEntryUseCase(uow)

        result = await use_case.execute(model.dlq_id)

        assert isinstance(result, DLQEntryDTO)
        assert result.dlq_id == model.dlq_id

    async def test_get_called_with_dlq_id(self) -> None:
        target_id = common.ids.new_uuid7()
        uow = _make_read_uow(single=None)
        use_case = GetDLQEntryUseCase(uow)

        await use_case.execute(target_id)

        uow.dlq.get_by_id.assert_called_once_with(target_id)


# ---------------------------------------------------------------------------
# RetryDLQEntryUseCase
# ---------------------------------------------------------------------------


class TestRetryDLQEntryUseCase:
    async def test_entry_not_found_returns_none(self) -> None:
        uow = _make_write_uow(entry=None)
        use_case = RetryDLQEntryUseCase(uow)

        result = await use_case.execute(common.ids.new_uuid7())

        assert result is None

    async def test_happy_path_returns_new_event_id(self) -> None:
        model = _make_dlq_model()
        new_id = common.ids.new_uuid7()
        uow = _make_write_uow(entry=model, new_event_id=new_id)
        use_case = RetryDLQEntryUseCase(uow)

        result = await use_case.execute(model.dlq_id)

        assert result is not None
        assert result.new_event_id == new_id

    async def test_commit_called_on_success(self) -> None:
        model = _make_dlq_model()
        uow = _make_write_uow(entry=model)
        use_case = RetryDLQEntryUseCase(uow)

        await use_case.execute(model.dlq_id)

        uow.commit.assert_called_once()

    async def test_commit_not_called_when_not_found(self) -> None:
        uow = _make_write_uow(entry=None)
        use_case = RetryDLQEntryUseCase(uow)

        await use_case.execute(common.ids.new_uuid7())

        uow.commit.assert_not_called()

    async def test_requeue_called_with_dlq_id(self) -> None:
        model = _make_dlq_model()
        uow = _make_write_uow(entry=model)
        use_case = RetryDLQEntryUseCase(uow)

        await use_case.execute(model.dlq_id)

        uow.dlq.requeue.assert_called_once_with(model.dlq_id)


# ---------------------------------------------------------------------------
# ResolveDLQEntryUseCase
# ---------------------------------------------------------------------------


class TestResolveDLQEntryUseCase:
    async def test_entry_not_found_returns_false(self) -> None:
        uow = _make_write_uow(entry=None)
        use_case = ResolveDLQEntryUseCase(uow)

        result = await use_case.execute(common.ids.new_uuid7(), note="fixed")

        assert result is False

    async def test_happy_path_returns_true(self) -> None:
        model = _make_dlq_model()
        uow = _make_write_uow(entry=model)
        use_case = ResolveDLQEntryUseCase(uow)

        result = await use_case.execute(model.dlq_id, note="resolved manually")

        assert result is True

    async def test_mark_resolved_called_with_note(self) -> None:
        model = _make_dlq_model()
        uow = _make_write_uow(entry=model)
        use_case = ResolveDLQEntryUseCase(uow)

        await use_case.execute(model.dlq_id, note="my note")

        uow.dlq.mark_resolved.assert_called_once_with(model.dlq_id, note="my note")

    async def test_commit_called_on_success(self) -> None:
        model = _make_dlq_model()
        uow = _make_write_uow(entry=model)
        use_case = ResolveDLQEntryUseCase(uow)

        await use_case.execute(model.dlq_id, note="ok")

        uow.commit.assert_called_once()

    async def test_commit_not_called_when_not_found(self) -> None:
        uow = _make_write_uow(entry=None)
        use_case = ResolveDLQEntryUseCase(uow)

        await use_case.execute(common.ids.new_uuid7(), note="n/a")

        uow.commit.assert_not_called()
