"""Construction tests for unresolved_resolution_worker_main (PLAN-0057 T-A-5-02).

Asserts the entry point wires a non-None ``usage_logger`` into the
UnresolvedResolutionWorker — closing audit finding F-CRIT-03 (the worker
previously received ``usage_logger=None``, leaving llm_usage_log empty).
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_main_constructs_worker_with_usage_logger() -> None:
    """``main()`` must instantiate the worker with a non-None usage_logger.

    We stub out:
      - Settings (no env reads)
      - configure_logging (no log handler registration)
      - _build_*_factories (no real DB engines)
      - signal handler registration (loop.add_signal_handler)
      - the run-loop (cancelled immediately so main returns)

    Then we assert that UnresolvedResolutionWorker received a non-None
    usage_logger kwarg via SessionScopedNlpUsageLogger.
    """
    from nlp_pipeline.workers import unresolved_resolution_worker_main as main_mod

    # Stub Settings — only needs to be a sentinel we can pass through.
    settings_obj = MagicMock(name="Settings")
    settings_obj.log_level = "INFO"
    settings_obj.log_json = False
    settings_obj.unresolved_resolution_interval_s = 60
    settings_obj.unresolved_resolution_batch_size = 5

    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()
    fake_factory = MagicMock(name="session_factory")

    # Worker stub — captures kwargs at construction time.
    worker_instance = MagicMock(name="worker")
    worker_instance.recover_stale_escalated = AsyncMock(return_value=0)
    # run_loop must be cancellable; raising CancelledError mimics graceful shutdown.
    worker_instance.run_loop = AsyncMock(side_effect=asyncio.CancelledError())
    worker_cls = MagicMock(return_value=worker_instance)

    sentinel_logger = MagicMock(name="SessionScopedNlpUsageLogger_instance")
    logger_cls = MagicMock(return_value=sentinel_logger)

    # add_signal_handler isn't allowed in pytest-asyncio's default loop on macOS;
    # patch it on the running loop to a no-op so we don't crash.
    loop = asyncio.get_running_loop()
    with (
        patch.object(main_mod, "Settings", create=True),
        patch(
            "nlp_pipeline.workers.unresolved_resolution_worker_main.configure_logging",
            create=True,
        ),
        patch.object(loop, "add_signal_handler", lambda *a, **k: None),
    ):
        # Patch the imports done inside main() — they are local imports so we
        # must patch on the module they're imported from.
        with (
            patch("nlp_pipeline.config.Settings", return_value=settings_obj, create=True),
            patch(
                "nlp_pipeline.infrastructure.intelligence_db.session._build_intelligence_factories",
                return_value=(fake_engine, MagicMock(), fake_factory, MagicMock()),
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.session._build_nlp_factories",
                return_value=(fake_engine, MagicMock(), fake_factory, MagicMock()),
            ),
            patch(
                "nlp_pipeline.infrastructure.nlp_db.usage_log_factory.SessionScopedNlpUsageLogger",
                logger_cls,
            ),
            patch(
                "nlp_pipeline.infrastructure.workers.unresolved_resolution_worker.UnresolvedResolutionWorker",
                worker_cls,
            ),
        ):
            with contextlib.suppress(asyncio.CancelledError):
                await main_mod.main()

    # The wrapper was constructed once — the worker received the wrapper
    # (NOT None) as its usage_logger.
    logger_cls.assert_called_once()
    worker_cls.assert_called_once()
    kwargs = worker_cls.call_args.kwargs
    assert "usage_logger" in kwargs
    assert kwargs["usage_logger"] is sentinel_logger
