"""Unit tests for app.py lifespan — verifies scheduler/dispatcher removal (T-B-4-01)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestLifespanNoScheduler:
    def test_app_state_has_no_scheduler(self) -> None:
        """After T-B-4-01, app.state must NOT have a scheduler attribute."""
        from content_ingestion.app import create_app

        app = create_app()
        assert not hasattr(app.state, "scheduler")


class TestLifespanNoDispatcher:
    def test_app_state_has_no_dispatcher(self) -> None:
        """After T-B-4-01, app.state must NOT have a dispatcher attribute."""
        from content_ingestion.app import create_app

        app = create_app()
        assert not hasattr(app.state, "dispatcher")


class TestLifespanHasDualFactories:
    @patch("content_ingestion.app._build_factories")
    @patch("content_ingestion.app.create_valkey_client_from_url")
    @patch("content_ingestion.app.build_object_storage")
    @patch("content_ingestion.app.configure_logging")
    async def test_lifespan_sets_dual_factories(
        self,
        mock_logging: MagicMock,
        mock_storage: MagicMock,
        mock_valkey: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        """Lifespan stores write_factory and read_factory."""
        from content_ingestion.app import create_app, lifespan

        mock_engine = AsyncMock()
        mock_write = MagicMock()
        mock_read = MagicMock()
        mock_build.return_value = (mock_engine, mock_engine, mock_write, mock_read)
        mock_valkey.return_value = AsyncMock()

        app = create_app()

        async with lifespan(app):
            assert app.state.write_factory is mock_write
            assert app.state.read_factory is mock_read
            assert not hasattr(app.state, "session_factory")


class TestLifespanNoTriggerFn:
    def test_app_state_has_no_trigger_fn(self) -> None:
        """After T-B-4-01, app.state must NOT have a trigger_fn attribute."""
        from content_ingestion.app import create_app

        app = create_app()
        assert not hasattr(app.state, "trigger_fn")


class TestAppImportsClean:
    def test_no_scheduler_import(self) -> None:
        """app.py should not import IngestionScheduler."""
        import inspect

        import content_ingestion.app as app_module

        source = inspect.getsource(app_module)
        assert "IngestionScheduler" not in source

    def test_no_dispatcher_import(self) -> None:
        """app.py should not import ContentIngestionOutboxDispatcher."""
        import inspect

        import content_ingestion.app as app_module

        source = inspect.getsource(app_module)
        assert "ContentIngestionOutboxDispatcher" not in source

    def test_no_run_fetch_cycle(self) -> None:
        """app.py should not define _run_fetch_cycle."""
        import content_ingestion.app as app_module

        assert not hasattr(app_module, "_run_fetch_cycle")
