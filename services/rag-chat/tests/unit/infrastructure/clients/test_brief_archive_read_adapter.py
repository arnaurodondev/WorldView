"""Unit tests for BriefArchiveReadAdapter (PLAN-0081 Wave A)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_USER_ID = UUID("018f0000-0000-7000-8000-000000000001")
_TENANT_ID = UUID("018f0000-0000-7000-8000-000000000002")


def _make_adapter():
    from rag_chat.infrastructure.clients.brief_archive_read_adapter import BriefArchiveReadAdapter

    mock_session = AsyncMock()
    mock_factory = MagicMock(return_value=mock_session)

    adapter = BriefArchiveReadAdapter(read_factory=mock_factory)
    return adapter, mock_factory, mock_session


@pytest.mark.asyncio
async def test_get_latest_creates_and_closes_session():
    """Session must always be closed (R27 — no connection leak)."""
    adapter, _factory, mock_session = _make_adapter()

    mock_repo = AsyncMock()
    mock_repo.get_latest = AsyncMock(return_value=[])

    with patch(
        "rag_chat.infrastructure.db.repositories.brief_archive_repository.BriefArchiveRepository",
        return_value=mock_repo,
    ):
        result = await adapter.get_latest(user_id=_USER_ID, tenant_id=_TENANT_ID, brief_type="morning", limit=1)
    # Session close must be called
    mock_session.close.assert_awaited_once()
    assert result == []


@pytest.mark.asyncio
async def test_get_latest_closes_session_on_exception():
    """Session must close even if repo raises (finally block)."""
    adapter, _factory, mock_session = _make_adapter()

    mock_repo = AsyncMock()
    mock_repo.get_latest = AsyncMock(side_effect=RuntimeError("db error"))

    with patch(
        "rag_chat.infrastructure.db.repositories.brief_archive_repository.BriefArchiveRepository",
        return_value=mock_repo,
    ):
        result = await adapter.get_latest(user_id=_USER_ID, tenant_id=_TENANT_ID, brief_type="morning")
    # Should return [] on error, not raise
    assert result == []
    # Session still closed despite exception
    mock_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_is_noop():
    """save() is read-only adapter — must not write."""
    adapter, _, _ = _make_adapter()
    # Just ensure no exception is raised
    # (save is intentionally a no-op that logs a warning)
    await adapter.save(MagicMock())


@pytest.mark.asyncio
async def test_get_history_returns_empty():
    adapter, _, _ = _make_adapter()
    rows, total = await adapter.get_history(
        user_id=_USER_ID, tenant_id=_TENANT_ID, brief_type="morning", page=1, page_size=10
    )
    assert rows == []
    assert total == 0


@pytest.mark.asyncio
async def test_get_by_id_returns_none():
    adapter, _, _ = _make_adapter()
    result = await adapter.get_by_id(UUID("018f0000-0000-7000-8000-000000000099"))
    assert result is None
