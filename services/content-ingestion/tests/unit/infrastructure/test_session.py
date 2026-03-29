"""Unit tests for dual session factory (T-B-2-01)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestBuildFactories:
    """Tests for _build_factories() dual session creation."""

    @patch("content_ingestion.infrastructure.db.session.create_async_engine")
    @patch("content_ingestion.infrastructure.db.session.async_sessionmaker")
    def test_build_factories_single_url(self, mock_sessionmaker: MagicMock, mock_engine: MagicMock) -> None:
        """When db_url_read is empty, read_factory == write_factory."""
        from content_ingestion.infrastructure.db.session import _build_factories

        settings = MagicMock()
        settings.db_url = "postgresql+asyncpg://localhost/test"
        settings.db_url_read = ""

        write_factory = MagicMock()
        mock_sessionmaker.return_value = write_factory

        _engine, wf, rf = _build_factories(settings)

        assert wf is rf
        mock_engine.assert_called_once()

    @patch("content_ingestion.infrastructure.db.session.create_async_engine")
    @patch("content_ingestion.infrastructure.db.session.async_sessionmaker")
    def test_build_factories_dual_url(self, mock_sessionmaker: MagicMock, mock_engine: MagicMock) -> None:
        """When db_url_read differs, two separate factories are created."""
        from content_ingestion.infrastructure.db.session import _build_factories

        settings = MagicMock()
        settings.db_url = "postgresql+asyncpg://localhost/write"
        settings.db_url_read = "postgresql+asyncpg://localhost/read"

        write_factory = MagicMock(name="write_factory")
        read_factory = MagicMock(name="read_factory")
        mock_sessionmaker.side_effect = [write_factory, read_factory]

        _engine, wf, rf = _build_factories(settings)

        assert wf is not rf
        assert wf is write_factory
        assert rf is read_factory
        assert mock_engine.call_count == 2

    @patch("content_ingestion.infrastructure.db.session.create_async_engine")
    @patch("content_ingestion.infrastructure.db.session.async_sessionmaker")
    def test_write_factory_pool_config(self, mock_sessionmaker: MagicMock, mock_engine: MagicMock) -> None:
        """Write engine has pool_size=10, pool_pre_ping=True, expire_on_commit=False."""
        from content_ingestion.infrastructure.db.session import _build_factories

        settings = MagicMock()
        settings.db_url = "postgresql+asyncpg://localhost/test"
        settings.db_url_read = ""

        _build_factories(settings)

        engine_kwargs = mock_engine.call_args
        assert engine_kwargs.kwargs["pool_size"] == 10
        assert engine_kwargs.kwargs["pool_pre_ping"] is True

        session_kwargs = mock_sessionmaker.call_args
        assert session_kwargs.kwargs["expire_on_commit"] is False


class TestCreateSessionFactory:
    """Tests for backward-compatible create_session_factory()."""

    @patch("content_ingestion.infrastructure.db.session._build_factories")
    def test_create_session_factory_returns_engine_and_write_factory(self, mock_build: MagicMock) -> None:
        """create_session_factory returns (engine, write_factory) tuple."""
        from content_ingestion.infrastructure.db.session import create_session_factory

        mock_engine = MagicMock()
        mock_write = MagicMock()
        mock_read = MagicMock()
        mock_build.return_value = (mock_engine, mock_write, mock_read)

        settings = MagicMock()
        engine, factory = create_session_factory(settings)

        assert engine is mock_engine
        assert factory is mock_write
