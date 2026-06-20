"""Unit tests for InstrumentBriefPregenerationWorker (AI-brief-flag fix, 2026-06-19).

Covers:
  1. Happy path — N active instruments → N persist-enabled generations.
  2. The worker drives execute_public_instrument with persist=True + skip_if_fresh=True.
  3. Per-instrument failure isolation — one bad instrument does not abort the batch.
  4. Empty active set — exits cleanly with the eligible gauge at 0.
  5. Concurrency cap — never more than brief_pregen_concurrency in flight.

The worker is pure orchestration; the active-instruments port + use case are
mocked so we never touch a real Valkey or LLM.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from rag_chat.application.workers.instrument_brief_pregeneration_worker import (
    InstrumentBriefPregenerationWorker,
)
from rag_chat.config import Settings

pytestmark = pytest.mark.unit


def _make_settings(*, batch_size: int = 50, concurrency: int = 4) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x:y@localhost/z",  # type: ignore[arg-type]
        brief_pregen_batch_size=batch_size,
        brief_pregen_concurrency=concurrency,
    )


def _result(*, skipped: bool = False) -> dict[str, object]:
    return {
        "content": "Brief body",
        "generated_at": "2026-06-19T08:00:00+00:00",
        "sections": [],
        "citations": [],
        "lead": "Lead.",
        "confidence": 0.9,
        "skipped_fresh": skipped,
    }


@pytest.mark.asyncio
async def test_happy_path_generates_for_each_instrument() -> None:
    """N active instruments → execute_public_instrument called N times with persist+skip flags."""
    instruments = ["e1", "e2", "e3"]
    active = MagicMock()
    active.list_active = AsyncMock(return_value=instruments)

    uc = MagicMock()
    uc.execute_public_instrument = AsyncMock(return_value=_result())

    worker = InstrumentBriefPregenerationWorker(
        active_instruments=active,
        briefing_uc=uc,
        settings=_make_settings(),
        jwt_minter=None,
    )

    await worker.run()

    assert uc.execute_public_instrument.await_count == 3
    # Every call MUST request persistence + freshness-skip (this is what
    # populates has_ai_brief proactively and avoids redundant LLM spend).
    for call in uc.execute_public_instrument.await_args_list:
        assert call.kwargs["persist"] is True
        assert call.kwargs["skip_if_fresh"] is True


@pytest.mark.asyncio
async def test_per_instrument_failure_isolated() -> None:
    """One failing instrument does not stop the others."""
    active = MagicMock()
    active.list_active = AsyncMock(return_value=["good1", "bad", "good2"])

    async def _maybe_fail(entity_id: str, **kwargs: object) -> dict[str, object]:
        if entity_id == "bad":
            raise RuntimeError("KG lookup failed")
        return _result()

    uc = MagicMock()
    uc.execute_public_instrument = AsyncMock(side_effect=_maybe_fail)

    worker = InstrumentBriefPregenerationWorker(
        active_instruments=active,
        briefing_uc=uc,
        settings=_make_settings(),
    )

    # Must not raise despite the bad instrument.
    await worker.run()
    assert uc.execute_public_instrument.await_count == 3


@pytest.mark.asyncio
async def test_empty_active_set_exits_cleanly() -> None:
    """No active instruments → no generation calls, no error."""
    active = MagicMock()
    active.list_active = AsyncMock(return_value=[])
    uc = MagicMock()
    uc.execute_public_instrument = AsyncMock(return_value=_result())

    worker = InstrumentBriefPregenerationWorker(
        active_instruments=active,
        briefing_uc=uc,
        settings=_make_settings(),
    )
    await worker.run()
    uc.execute_public_instrument.assert_not_called()


@pytest.mark.asyncio
async def test_concurrency_cap_respected() -> None:
    """Never more than brief_pregen_concurrency instruments in flight at once."""
    active = MagicMock()
    active.list_active = AsyncMock(return_value=[f"e{i}" for i in range(10)])

    in_flight = 0
    peak = 0

    async def _slow(entity_id: str, **kwargs: object) -> dict[str, object]:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return _result()

    uc = MagicMock()
    uc.execute_public_instrument = AsyncMock(side_effect=_slow)

    worker = InstrumentBriefPregenerationWorker(
        active_instruments=active,
        briefing_uc=uc,
        settings=_make_settings(concurrency=3),
    )
    await worker.run()

    assert peak <= 3, f"concurrency cap violated: peak={peak}"
    assert uc.execute_public_instrument.await_count == 10


@pytest.mark.asyncio
async def test_active_window_passed_to_reader() -> None:
    """The reader the worker depends on is consulted exactly once per run."""
    active = MagicMock()
    active.list_active = AsyncMock(return_value=["e1"])
    uc = MagicMock()
    uc.execute_public_instrument = AsyncMock(return_value=_result())

    worker = InstrumentBriefPregenerationWorker(
        active_instruments=active,
        briefing_uc=uc,
        settings=_make_settings(),
    )
    await worker.run()
    active.list_active.assert_awaited_once()
