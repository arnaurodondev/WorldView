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
            assert hasattr(app.state, "screen_fields_cache")
            assert app.state.object_storage is None  # degraded gracefully


def test_lifespan_does_not_start_consumers() -> None:
    """app.py lifespan must not embed Kafka consumers or outbox dispatchers — R22 guard.

    Consumers and outbox dispatchers run as standalone OS processes (see
    *_consumer_main.py and dispatcher_main.py). They must never be embedded as
    ``asyncio.create_task()`` inside the API process lifespan.

    Deliberate exception (Wave B-2 / PRD-0017 §6.2): the lightweight
    ``_screen_fields_refresh_loop`` cache-warm-up task IS an in-process background
    task by design — it is read-only, has no side effects outside the service,
    and is not a Kafka consumer or outbox dispatcher.  Only consumer/dispatcher
    coroutine names are prohibited.
    """
    # Consumer/dispatcher function names that must NEVER appear as create_task args.
    _PROHIBITED_TASK_NAMES = {
        "run",  # SchedulerProcess.run / ConsumerProcess.run
        "consume",
        "dispatch",
        "outbox",
        "kafka",
        "consumer",
    }

    app_py = Path(__file__).parent.parent.parent / "src" / "market_data" / "app.py"
    source = app_py.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(app_py))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "create_task"):
            continue
        # Inspect the first argument of create_task — it must not be a
        # consumer/dispatcher coroutine.
        if node.args:
            arg = node.args[0]
            # Extract the function name being called inside create_task(fn(...))
            task_name = ""
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                task_name = arg.func.id.lower()
            elif isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute):
                task_name = arg.func.attr.lower()
            for prohibited in _PROHIBITED_TASK_NAMES:
                if prohibited in task_name:
                    pytest.fail(
                        f"asyncio.create_task({task_name!r}) found in app.py at "
                        f"line {node.lineno}. Consumers and outbox dispatchers must "
                        "run as standalone entry points, not tasks inside the API "
                        "lifespan (R22)."
                    )
