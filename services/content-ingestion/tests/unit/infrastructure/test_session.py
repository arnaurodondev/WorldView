"""Unit tests for dual session factory (T-B-2-01)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestSameDbEndpoint:
    """Tests for _same_db_endpoint() URL comparison helper (F-QA-003).

    Mirrors the equivalent class in S5 test_session.py for consistent coverage.
    """

    def test_identical_urls_are_same(self) -> None:
        from content_ingestion.infrastructure.db.session import _same_db_endpoint

        url = "postgresql+asyncpg://user:pass@localhost:5432/mydb"
        assert _same_db_endpoint(url, url) is True

    def test_trailing_slash_ignored(self) -> None:
        from content_ingestion.infrastructure.db.session import _same_db_endpoint

        assert (
            _same_db_endpoint(
                "postgresql+asyncpg://localhost:5432/mydb",
                "postgresql+asyncpg://localhost:5432/mydb/",
            )
            is True
        )

    def test_different_host_is_not_same(self) -> None:
        from content_ingestion.infrastructure.db.session import _same_db_endpoint

        assert (
            _same_db_endpoint(
                "postgresql+asyncpg://primary:5432/db",
                "postgresql+asyncpg://replica:5432/db",
            )
            is False
        )

    def test_different_database_is_not_same(self) -> None:
        from content_ingestion.infrastructure.db.session import _same_db_endpoint

        assert (
            _same_db_endpoint(
                "postgresql+asyncpg://localhost:5432/write_db",
                "postgresql+asyncpg://localhost:5432/read_db",
            )
            is False
        )

    def test_different_credentials_still_same_endpoint(self) -> None:
        from content_ingestion.infrastructure.db.session import _same_db_endpoint

        # Credentials differ but host/port/db are the same → same endpoint
        assert (
            _same_db_endpoint(
                "postgresql+asyncpg://admin:secret@localhost:5432/db",
                "postgresql+asyncpg://readonly:pass@localhost:5432/db",
            )
            is True
        )

    def test_different_port_is_not_same(self) -> None:
        from content_ingestion.infrastructure.db.session import _same_db_endpoint

        assert (
            _same_db_endpoint(
                "postgresql+asyncpg://localhost:5432/db",
                "postgresql+asyncpg://localhost:5433/db",
            )
            is False
        )


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

        _engine, _read_engine, wf, rf = _build_factories(settings)

        assert wf is rf
        assert _read_engine is _engine  # same object when no read replica
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

        _engine, _read_engine, wf, rf = _build_factories(settings)

        assert wf is not rf
        assert wf is write_factory
        assert rf is read_factory
        assert mock_engine.call_count == 2  # two separate engine calls for dual-URL

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
