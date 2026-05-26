"""Unit tests for MorningBriefPregenerationWorker (PLAN-0094 W2, T-W2-04).

The worker has only one public method (``run``) but its behaviour is the heart
of W2.  These tests cover the six scenarios from the plan:

  1. Happy path — N users → N fresh + N lastgood writes.
  2. Per-user failure isolation — one bad user does not overwrite their lastgood
     and does not abort the others.
  3. Run-level metrics — started + completed counters fire on a healthy run.
  4. Run continues after a per-user exception.
  5. Concurrency limit — never more than ``brief_pregen_concurrency`` users in
     flight at once.
  6. Empty user list — exits cleanly with gauge=0.

WHY mock everything:  The worker is pure orchestration over the
:class:`IActiveUsersPort` and :class:`GenerateBriefingUseCase` ports.  All
ports/clients are mocked; we never touch a real Valkey or LLM.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from rag_chat.application.workers.morning_brief_pregeneration_worker import (
    MorningBriefPregenerationWorker,
)
from rag_chat.config import Settings

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_settings(*, batch_size: int = 50, concurrency: int = 4) -> Settings:
    """Build a minimal :class:`Settings` for the worker."""
    return Settings(
        database_url="postgresql+asyncpg://x:y@localhost/z",  # type: ignore[arg-type]
        brief_pregen_batch_size=batch_size,
        brief_pregen_concurrency=concurrency,
        brief_fresh_ttl_hours=30,
        brief_last_good_ttl_days=7,
    )


def _result(user_index: int) -> dict[str, object]:
    """Realistic GenerateBriefingUseCase.execute_public_morning() return."""
    return {
        "content": f"Brief for user {user_index}",
        "risk_summary": {"concentration_score": 0.0},
        "citations": [],
        "generated_at": "2026-05-25T08:00:00+00:00",
        "confidence": 0.9,
        "lead": "Markets stable.",
        "sections": [],
    }


def _make_worker(
    *,
    users: list[UUID],
    settings: Settings | None = None,
    uc: MagicMock | None = None,
    valkey: MagicMock | None = None,
) -> tuple[MorningBriefPregenerationWorker, MagicMock, MagicMock, MagicMock]:
    """Build a worker plus the three mocks driving it.

    Returns ``(worker, active_users_mock, uc_mock, valkey_mock)`` so tests can
    inspect each mock without re-extracting from the worker.
    """
    settings = settings or _make_settings()

    active_users = MagicMock()
    active_users.list_active = AsyncMock(return_value=users)

    if uc is None:
        uc = MagicMock()
        uc.execute_public_morning = AsyncMock(side_effect=lambda user_id, tenant_id, internal_jwt: _result(0))

    if valkey is None:
        valkey = MagicMock()
        valkey.set = AsyncMock()

    worker = MorningBriefPregenerationWorker(
        active_users=active_users,
        briefing_uc=uc,
        valkey_client=valkey,
        settings=settings,
    )
    return worker, active_users, uc, valkey


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_run_processes_all_eligible_users() -> None:
    """3 users → 6 valkey.set calls (fresh + lastgood for each)."""
    users = [
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000003"),
    ]
    worker, _active, uc, valkey = _make_worker(users=users)

    await worker.run()

    # 3 users x 2 writes (fresh + lastgood) = 6 set calls
    assert valkey.set.await_count == 6
    # All UC calls happened
    assert uc.execute_public_morning.await_count == 3

    # Sanity-check the keys written — extract the cache key from each call
    keys_written = [call.args[0] for call in valkey.set.await_args_list]
    for user_id in users:
        assert f"briefing:morning:v2:{user_id}" in keys_written
        assert f"briefing:morning:lastgood:{user_id}" in keys_written


async def test_run_skips_user_on_generation_failure_keeps_lastgood() -> None:
    """User 2 raises; lastgood for user 2 is NOT written. Users 1 + 3 succeed."""
    users = [
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
        UUID("00000000-0000-0000-0000-000000000003"),
    ]

    # Build a UC that raises only for user 2.
    uc = MagicMock()

    async def _side_effect(user_id: str, tenant_id: str, internal_jwt: str | None) -> dict[str, object]:
        if user_id == "00000000-0000-0000-0000-000000000002":
            raise RuntimeError("simulated LLM failure")
        return _result(0)

    uc.execute_public_morning = AsyncMock(side_effect=_side_effect)

    # Force concurrency=1 so the assertion below is deterministic.
    worker, _active, _uc, valkey = _make_worker(
        users=users,
        uc=uc,
        settings=_make_settings(concurrency=1),
    )

    await worker.run()

    # 2 successes x 2 writes = 4 set calls; user 2 contributes 0.
    keys_written = [call.args[0] for call in valkey.set.await_args_list]
    assert any("00000000-0000-0000-0000-000000000001" in k for k in keys_written)
    assert any("00000000-0000-0000-0000-000000000003" in k for k in keys_written)
    # User 2 must have NO writes at all (not fresh, not lastgood).
    assert not any("00000000-0000-0000-0000-000000000002" in k for k in keys_written)


async def test_run_emits_metrics_for_started_completed() -> None:
    """A clean run increments both runs_total{started} and runs_total{completed}."""
    from rag_chat.application.metrics.prometheus import rag_brief_pregeneration_runs_total

    started_before = rag_brief_pregeneration_runs_total.labels(status="started")._value.get()
    completed_before = rag_brief_pregeneration_runs_total.labels(status="completed")._value.get()

    users = [UUID("00000000-0000-0000-0000-000000000001")]
    worker, *_ = _make_worker(users=users)
    await worker.run()

    assert rag_brief_pregeneration_runs_total.labels(status="started")._value.get() == started_before + 1
    assert rag_brief_pregeneration_runs_total.labels(status="completed")._value.get() == completed_before + 1


async def test_run_continues_after_per_user_exception() -> None:
    """Per-user exception does not break the gather; all users are attempted."""
    users = [UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 5)]

    uc = MagicMock()

    # The middle user blows up; the others succeed.
    async def _se(user_id: str, tenant_id: str, internal_jwt: str | None) -> dict[str, object]:
        if user_id.endswith("3"):
            raise ValueError("kaboom")
        return _result(0)

    uc.execute_public_morning = AsyncMock(side_effect=_se)
    worker, _, _u, _v = _make_worker(users=users, uc=uc)

    # No exception bubbles out of run().
    await worker.run()

    # All 4 UC attempts were made (the broken one still counts as an attempt).
    assert uc.execute_public_morning.await_count == 4


async def test_run_respects_concurrency_limit() -> None:
    """Concurrency=2, 5 users → never more than 2 concurrent UC calls observed."""
    users = [UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]

    concurrent_now = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def _slow_uc(user_id: str, tenant_id: str, internal_jwt: str | None) -> dict[str, object]:
        nonlocal concurrent_now, max_concurrent
        async with lock:
            concurrent_now += 1
            max_concurrent = max(max_concurrent, concurrent_now)
        # Sleep enough for parallelism to materialise.
        await asyncio.sleep(0.01)
        async with lock:
            concurrent_now -= 1
        return _result(0)

    uc = MagicMock()
    uc.execute_public_morning = AsyncMock(side_effect=_slow_uc)

    worker, *_ = _make_worker(
        users=users,
        uc=uc,
        settings=_make_settings(concurrency=2, batch_size=10),
    )
    await worker.run()

    assert max_concurrent <= 2, f"observed max_concurrent={max_concurrent}, expected <= 2"
    assert uc.execute_public_morning.await_count == 5


async def test_run_handles_empty_active_users_cleanly() -> None:
    """0 eligible users → no UC calls, gauge=0, no exceptions, completed metric fires."""
    from rag_chat.application.metrics.prometheus import (
        rag_brief_pregeneration_eligible_users,
        rag_brief_pregeneration_runs_total,
    )

    completed_before = rag_brief_pregeneration_runs_total.labels(status="completed")._value.get()
    worker, _active, uc, valkey = _make_worker(users=[])

    await worker.run()

    assert uc.execute_public_morning.await_count == 0
    assert valkey.set.await_count == 0
    assert rag_brief_pregeneration_eligible_users._value.get() == 0
    assert rag_brief_pregeneration_runs_total.labels(status="completed")._value.get() == completed_before + 1


async def test_run_does_not_raise_when_active_users_throws() -> None:
    """Run-level exception (active_users source down) → metric fires, no raise."""
    from rag_chat.application.metrics.prometheus import rag_brief_pregeneration_runs_total

    failed_before = rag_brief_pregeneration_runs_total.labels(status="failed")._value.get()

    active_users = MagicMock()
    active_users.list_active = AsyncMock(side_effect=RuntimeError("valkey down"))

    worker = MorningBriefPregenerationWorker(
        active_users=active_users,
        briefing_uc=MagicMock(),
        valkey_client=MagicMock(),
        settings=_make_settings(),
    )

    # No exception bubbles out — that's the contract.
    await worker.run()

    assert rag_brief_pregeneration_runs_total.labels(status="failed")._value.get() == failed_before + 1
