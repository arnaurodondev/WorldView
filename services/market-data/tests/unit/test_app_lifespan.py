"""Unit tests for market-data app lifespan (PLAN-0013 Wave A-1).

Verifies that:
- The lifespan starts cleanly, initialising DB + Valkey + storage
- No asyncio.create_task() calls are present (R22 compliance, regression guard)
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def test_lifespan_starts_cleanly() -> None:
    """Lifespan initialises DB, Valkey, and object storage without error."""
    mock_engine = AsyncMock()
    mock_factory = MagicMock()
    mock_valkey = AsyncMock()

    with (
        patch("market_data.infrastructure.db.session.build_write_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_read_engine", return_value=mock_engine),
        patch("market_data.infrastructure.db.session.build_session_factory", return_value=mock_factory),
        patch("messaging.valkey.client.create_valkey_client_from_url", return_value=mock_valkey),
        # Storage intentionally degraded — lifespan handles this gracefully
        patch("storage.factory.build_object_storage", side_effect=Exception("no storage")),
    ):
        from market_data.app import create_app

        app = create_app()
        with TestClient(app):
            assert app.state.write_session_factory is mock_factory
            assert app.state.read_session_factory is mock_factory
            assert app.state.valkey_client is mock_valkey
            assert hasattr(app.state, "quote_cache")
            assert app.state.object_storage is None  # degraded gracefully


def test_lifespan_does_not_start_consumers() -> None:
    """app.py lifespan must not call asyncio.create_task() — R22 regression guard.

    Consumers and outbox dispatchers run as standalone OS processes (see
    *_consumer_main.py and dispatcher_main.py). They must never be embedded as
    background tasks inside the API process lifespan.
    """
    app_py = Path(__file__).parent.parent.parent / "src" / "market_data" / "app.py"
    source = app_py.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(app_py))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "create_task":
                pytest.fail(
                    f"asyncio.create_task() found in app.py at line {node.lineno}. "
                    "Background processes must run as standalone entry points, "
                    "not as tasks inside the API lifespan (R22)."
                )
