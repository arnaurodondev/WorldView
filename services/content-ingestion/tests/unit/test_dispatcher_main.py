"""Unit tests for standalone dispatcher_main.py (T-B-4-03)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestDispatcherMainImports:
    def test_module_imports_without_error(self) -> None:
        """dispatcher_main.py should import cleanly."""
        import content_ingestion.infrastructure.messaging.outbox.dispatcher_main  # noqa: F401


class TestDispatcherUsesNewFactory:
    def test_uses_build_factories_not_create_session_factory(self) -> None:
        """dispatcher_main.py should use _build_factories, not create_session_factory."""
        import inspect

        from content_ingestion.infrastructure.messaging.outbox import dispatcher_main

        source = inspect.getsource(dispatcher_main)
        assert "_build_factories" in source
        assert "create_session_factory" not in source
