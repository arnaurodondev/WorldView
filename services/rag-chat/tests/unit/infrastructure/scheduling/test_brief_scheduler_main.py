"""Smoke tests for the brief pre-generation scheduler entry-point (PLAN-0094 W2).

The entry-point is mostly thin wiring; we only test the kill-switch (disabled
mode) here because behavioural tests for the worker live in
``tests/unit/application/workers/test_morning_brief_pregeneration_worker.py``.
"""

from __future__ import annotations

import pytest
from rag_chat.config import Settings
from rag_chat.infrastructure.scheduling.brief_scheduler_main import _run_loop

pytestmark = pytest.mark.unit


async def test_scheduler_main_exits_when_disabled() -> None:
    """``brief_pregen_enabled=False`` → ``_run_loop`` returns immediately, no scheduler started.

    Without this kill-switch operators would have to delete the docker compose
    service to silence the scheduler.  The test ensures the flag actually works.
    """
    settings = Settings(
        database_url="postgresql+asyncpg://x:y@localhost/z",  # type: ignore[arg-type]
        brief_pregen_enabled=False,
        log_json=False,
    )
    # Must return (not hang).  If we reach the ``await asyncio.sleep(3600)``
    # the test will hang and pytest's timeout would catch it — but the early
    # return path keeps us well clear of any blocking call.
    await _run_loop(settings)
