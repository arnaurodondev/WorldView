"""Unit tests for citation-accuracy cron wiring in app lifespan — PLAN-0084 A-1 T-A-1-05."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_settings(**kwargs):  # type: ignore[no-untyped-def]
    """Build a minimal Settings for testing without connecting to real services."""
    from rag_chat.config import Settings

    base = {
        "database_url": "postgresql+asyncpg://test:test@localhost:5432/test_rag_db",
        "s1_internal_token": "test-token",
        "_env_file": None,
    }
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


# ── _wire_citation_cron directly ──────────────────────────────────────────────


def test_lifespan_starts_cron_when_enabled() -> None:
    """_wire_citation_cron creates a task and attaches it to app.state when enabled."""
    from rag_chat.app import _wire_citation_cron  # type: ignore[attr-defined]

    settings = _make_settings(citation_cron_enabled=True, citation_judge_provider="ollama")

    app = MagicMock()
    app.state = MagicMock()
    read_factory = MagicMock()
    log = MagicMock()

    # Patch start_citation_accuracy_cron to return a mock task
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.cancelled.return_value = False
    mock_task.exception.return_value = None

    with patch(
        "rag_chat.infrastructure.jobs.citation_accuracy_cron.start_citation_accuracy_cron",
        return_value=mock_task,
    ):
        _wire_citation_cron(app, settings, read_factory, log)

    # Task should be stored on app.state
    assert app.state.citation_cron_task is mock_task
    # Done callback registered
    mock_task.add_done_callback.assert_called_once()


def test_lifespan_disabled_does_not_call_start_citation_accuracy_cron() -> None:
    """When citation_cron_enabled=False, start_citation_accuracy_cron must NOT be called.

    F-005: the existing disabled test checks the flag only; this verifies that the
    actual scheduling function (and thus use_case.execute) is never reached.
    """
    from unittest.mock import patch

    settings = _make_settings(citation_cron_enabled=False)
    app = MagicMock()
    app.state = MagicMock()
    app.state.citation_cron_task = None
    read_factory = MagicMock()
    log = MagicMock()

    with patch(
        "rag_chat.infrastructure.jobs.citation_accuracy_cron.start_citation_accuracy_cron",
    ) as mock_start:
        from rag_chat.app import _wire_citation_cron  # type: ignore[attr-defined]

        # Always call _wire_citation_cron; the function itself must respect the setting
        _wire_citation_cron(app, settings, read_factory, log)

        mock_start.assert_not_called(), "start_citation_accuracy_cron must NOT be called when disabled"


def test_done_callback_logs_critical_on_crash() -> None:
    """BP-268: done callback logs critical when task raised an exception."""
    from rag_chat.app import _wire_citation_cron  # type: ignore[attr-defined]

    settings = _make_settings(citation_cron_enabled=True, citation_judge_provider="ollama")

    app = MagicMock()
    app.state = MagicMock()
    read_factory = MagicMock()
    log = MagicMock()

    captured_callback = None
    mock_task = MagicMock(spec=asyncio.Task)
    mock_task.cancelled.return_value = False
    crash_exc = RuntimeError("cron crashed badly")
    mock_task.exception.return_value = crash_exc

    def _capture_callback(cb):  # type: ignore[no-untyped-def]
        nonlocal captured_callback
        captured_callback = cb

    mock_task.add_done_callback.side_effect = _capture_callback

    with patch(
        "rag_chat.infrastructure.jobs.citation_accuracy_cron.start_citation_accuracy_cron",
        return_value=mock_task,
    ):
        _wire_citation_cron(app, settings, read_factory, log)

    assert captured_callback is not None
    # Fire the callback with the crashed task
    captured_callback(mock_task)

    # log.critical should have been called
    log.critical.assert_called_once()
    call_kwargs = log.critical.call_args
    # First positional arg is the event name
    assert "citation_cron_task_crashed" in str(call_kwargs)


def test_done_callback_does_not_log_on_cancel() -> None:
    """BP-268: done callback is silent when task is cancelled (normal shutdown)."""
    from rag_chat.app import _wire_citation_cron  # type: ignore[attr-defined]

    settings = _make_settings(citation_cron_enabled=True, citation_judge_provider="ollama")

    app = MagicMock()
    app.state = MagicMock()
    read_factory = MagicMock()
    log = MagicMock()

    captured_callback = None
    mock_task = MagicMock(spec=asyncio.Task)
    # Simulate cancellation
    mock_task.cancelled.return_value = True

    def _capture_callback(cb):  # type: ignore[no-untyped-def]
        nonlocal captured_callback
        captured_callback = cb

    mock_task.add_done_callback.side_effect = _capture_callback

    with patch(
        "rag_chat.infrastructure.jobs.citation_accuracy_cron.start_citation_accuracy_cron",
        return_value=mock_task,
    ):
        _wire_citation_cron(app, settings, read_factory, log)

    assert captured_callback is not None
    captured_callback(mock_task)

    # No critical logging on cancellation
    log.critical.assert_not_called()


async def test_lifespan_shutdown_cancels_task() -> None:
    """Lifespan teardown cancels the cron task and gathers it."""
    app = MagicMock()

    # Create a real asyncio task that sleeps forever
    async def _forever() -> None:
        await asyncio.sleep(9999)

    task = asyncio.create_task(_forever())
    app.state.citation_cron_task = task

    # Simulate shutdown logic from lifespan
    if app.state.citation_cron_task is not None:
        _cron_task: asyncio.Task = app.state.citation_cron_task
        _cron_task.cancel()
        await asyncio.gather(_cron_task, return_exceptions=True)

    assert task.cancelled()
