"""Unit tests for AdapterStateRepository."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from content_ingestion.infrastructure.db.models import SourceAdapterStateModel
from content_ingestion.infrastructure.db.repositories.adapter_state import AdapterStateRepository

import common.time

pytestmark = pytest.mark.unit

_SOURCE_ID = UUID("00000000-0000-0000-0000-000000000001")


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


class TestAdapterStateGet:
    async def test_get_returns_model_when_found(self) -> None:
        session = _mock_session()
        state = SourceAdapterStateModel(source_id=_SOURCE_ID, error_count=0)
        result = MagicMock()
        result.scalar_one_or_none.return_value = state
        session.execute.return_value = result

        repo = AdapterStateRepository(session)  # type: ignore[arg-type]
        found = await repo.get(_SOURCE_ID)

        assert found is state

    async def test_get_returns_none_when_missing(self) -> None:
        session = _mock_session()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        repo = AdapterStateRepository(session)  # type: ignore[arg-type]
        found = await repo.get(_SOURCE_ID)

        assert found is None


class TestAdapterStateUpsert:
    async def test_upsert_creates_new_row_when_missing(self) -> None:
        session = _mock_session()
        # get() returns None → creates new row
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        repo = AdapterStateRepository(session)  # type: ignore[arg-type]
        now = common.time.utc_now()
        row = await repo.upsert(_SOURCE_ID, last_watermark=now, error_count=0)

        session.add.assert_called_once()
        assert row.source_id == _SOURCE_ID
        assert row.last_watermark == now

    async def test_upsert_updates_existing_row(self) -> None:
        session = _mock_session()
        existing = SourceAdapterStateModel(
            source_id=_SOURCE_ID,
            error_count=2,
            last_error="timeout",
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        session.execute.return_value = result

        repo = AdapterStateRepository(session)  # type: ignore[arg-type]
        row = await repo.upsert(_SOURCE_ID, error_count=0, last_cursor="page_3")

        assert row.error_count == 0
        assert row.last_cursor == "page_3"
        # add should NOT be called for an existing row
        session.add.assert_not_called()


class TestAdapterStateResetErrors:
    async def test_reset_errors_clears_error_fields(self) -> None:
        session = _mock_session()
        existing = SourceAdapterStateModel(
            source_id=_SOURCE_ID,
            error_count=5,
            last_error="connection refused",
        )
        result = MagicMock()
        result.scalar_one_or_none.return_value = existing
        session.execute.return_value = result

        repo = AdapterStateRepository(session)  # type: ignore[arg-type]
        await repo.reset_errors(_SOURCE_ID)

        assert existing.error_count == 0
        assert existing.last_error is None

    async def test_reset_errors_noop_when_missing(self) -> None:
        session = _mock_session()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        repo = AdapterStateRepository(session)  # type: ignore[arg-type]
        await repo.reset_errors(_SOURCE_ID)

        # No error — just a no-op
        session.flush.assert_not_awaited()
