"""Unit tests for _expire_stale_embeddings startup function (PLAN-0031 B-2).

Validates that on startup the NLP Pipeline expires chunk_embeddings and
section_embeddings rows whose model_id differs from the current configured
embedding_model_id.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_result(rowcount: int) -> MagicMock:
    """Create a mock CursorResult with the given rowcount."""
    result = MagicMock()
    result.rowcount = rowcount
    return result


def _make_session_factory(
    chunk_rowcount: int = 0,
    section_rowcount: int = 0,
) -> tuple[Any, AsyncMock]:
    """Build an async session factory that returns a mock session.

    The session's ``execute`` method returns different rowcounts for
    the two UPDATE statements (chunk_embeddings first, section_embeddings second).

    Returns (factory_callable, mock_session) so tests can inspect the session.
    """
    session = AsyncMock()
    # First call = chunk_embeddings UPDATE, second = section_embeddings UPDATE
    session.execute = AsyncMock(
        side_effect=[
            _make_result(chunk_rowcount),
            _make_result(section_rowcount),
        ]
    )
    session.commit = AsyncMock()

    # SQLAlchemy async_sessionmaker() returns an async context manager directly
    @asynccontextmanager
    async def _factory() -> Any:
        yield session

    return _factory, session


def _make_config(embedding_model_id: str = "bge-large") -> MagicMock:
    """Create a minimal config mock with embedding_model_id."""
    config = MagicMock()
    config.embedding_model_id = embedding_model_id
    return config


class TestExpireStaleEmbeddings:
    """Tests for _expire_stale_embeddings."""

    def test_startup_expires_stale_embeddings(self) -> None:
        """When model_id changes, old embeddings get expires_at set to now()."""
        from nlp_pipeline.app import _expire_stale_embeddings

        factory, session = _make_session_factory(chunk_rowcount=15, section_rowcount=8)
        config = _make_config("new-model-v2")

        asyncio.run(_expire_stale_embeddings(factory, config))

        # session.execute should have been called twice (chunk + section)
        assert session.execute.call_count == 2

        # Verify both UPDATE statements used the correct model_id param
        for call in session.execute.call_args_list:
            params = call.args[1] if len(call.args) > 1 else call.kwargs.get("params", {})
            assert params["current"] == "new-model-v2"

        # commit was called once
        session.commit.assert_called_once()

    def test_startup_no_op_when_model_unchanged(self) -> None:
        """When model_id matches all rows, no rows are updated and no warning is logged."""
        from nlp_pipeline.app import _expire_stale_embeddings

        factory, session = _make_session_factory(chunk_rowcount=0, section_rowcount=0)
        config = _make_config("bge-large")

        # Patch structlog to capture log calls — the function imports structlog
        # at the top of the module (import structlog) so we patch the local ref.
        with patch("structlog.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            asyncio.run(_expire_stale_embeddings(factory, config))

            # No warning should have been emitted (rowcounts are both 0)
            mock_logger.warning.assert_not_called()

        # session.execute was still called (the UPDATEs ran but matched 0 rows)
        assert session.execute.call_count == 2
        session.commit.assert_called_once()

    def test_startup_logs_warning_when_rows_expired(self) -> None:
        """When stale rows are found, a warning is logged with counts."""
        from nlp_pipeline.app import _expire_stale_embeddings

        factory, _session = _make_session_factory(chunk_rowcount=10, section_rowcount=5)
        config = _make_config("upgraded-model")

        # The function imports structlog inside itself, so we patch at that level
        with patch("structlog.get_logger") as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            asyncio.run(_expire_stale_embeddings(factory, config))

            mock_logger.warning.assert_called_once_with(
                "embedding_model_changed",
                stale_chunk_count=10,
                stale_section_count=5,
                current_model="upgraded-model",
            )
