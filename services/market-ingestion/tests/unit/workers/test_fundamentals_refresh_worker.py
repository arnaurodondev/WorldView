"""Unit tests for FundamentalsRefreshWorker (PLAN-0099 W2-T02).

Covers:
- Disabled flag → ``run()`` returns immediately without touching infra.
- Successful trigger increments the ``ok`` counter.
- 429 / ``ProviderRateLimited`` triggers exponential backoff and retries.
- Symbol resolution respects the CSV override and the top-N cap.
- ``stop()`` halts the loop promptly.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import ProviderRateLimited
from market_ingestion.infrastructure.workers.fundamentals_refresh_worker import (
    FundamentalsRefreshWorker,
    fundamentals_refresh_attempts_total,
)


def _settings(**overrides: Any) -> SimpleNamespace:
    """Build a minimal settings stub. ``SimpleNamespace`` is enough because the
    worker only reads attributes via ``getattr`` — no pydantic validation needed.
    """
    base = {
        "fundamentals_refresh_enabled": True,
        "fundamentals_refresh_interval_hours": 6.0,
        "fundamentals_refresh_top_n": 500,
        "fundamentals_refresh_provider": "eodhd",
        "fundamentals_refresh_variant": "quarterly",
        "fundamentals_refresh_symbols": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _counter_value(symbol: str, status: str) -> float:
    """Read the current value of the per-symbol/per-status counter."""
    # Prometheus Counter exposes ._value.get() on the labeled child.
    return float(fundamentals_refresh_attempts_total.labels(symbol=symbol, status=status)._value.get())


# ---------------------------------------------------------------------------
# T4-c: disabled flag → worker doesn't start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_flag_returns_immediately_without_building_infra() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_enabled=False))

    # If the worker tried to build DB factories we'd see _build_factories
    # called; patch it to a hard failure so any attempt would blow up.
    with patch(
        "market_ingestion.infrastructure.workers.fundamentals_refresh_worker._build_factories",
        side_effect=AssertionError("must not build infra when disabled"),
    ):
        await worker.run()  # Should return immediately; no AssertionError raised.

    assert worker.enabled is False


# ---------------------------------------------------------------------------
# T4-a: top-N + CSV override + symbol-list resolution
# ---------------------------------------------------------------------------


def test_resolves_csv_override_and_caps_to_top_n() -> None:
    worker = FundamentalsRefreshWorker(
        settings=_settings(
            fundamentals_refresh_symbols="aapl,msft, nvda ,googl,amzn",
            fundamentals_refresh_top_n=3,
        )
    )
    symbols = worker._resolve_symbols()
    # Uppercased, trimmed, capped to top-N, order preserved.
    assert symbols == ["AAPL", "MSFT", "NVDA"]


def test_default_symbol_universe_when_no_override() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_top_n=5))
    symbols = worker._resolve_symbols()
    assert len(symbols) == 5
    # The built-in default list is mega-cap-first.
    assert symbols[0] == "AAPL"


def test_top_n_clamped_to_safety_range() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_top_n=10**9))
    # Caps at 5000 (the worker's hard upper bound).
    assert worker._top_n() == 5000

    worker_low = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_top_n=0))
    assert worker_low._top_n() == 1


# ---------------------------------------------------------------------------
# T4-d: successful trigger increments ``ok``
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_refresh_increments_ok_counter() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings())
    worker._write_factory = object()  # — populated lazily in run() in prod
    worker._read_factory = object()

    before = _counter_value("AAPL", "ok")

    # Patch the use case construction site so we don't actually hit any infra.
    fake_use_case = SimpleNamespace(execute=AsyncMock(return_value=None))
    with (
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.SqlaUnitOfWork",
            return_value=object(),
        ),
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.TriggerIngestionUseCase",
            return_value=fake_use_case,
        ),
    ):
        await worker._refresh_one(Provider.EODHD, "quarterly", "AAPL")

    after = _counter_value("AAPL", "ok")
    assert after == before + 1
    # And the use case was called exactly once with the right args.
    fake_use_case.execute.assert_awaited_once()
    call_kwargs = fake_use_case.execute.await_args.kwargs
    assert call_kwargs["provider"] is Provider.EODHD
    assert call_kwargs["dataset_type"] is DatasetType.FUNDAMENTALS
    assert call_kwargs["symbols"] == ["AAPL"]
    assert call_kwargs["variant"] == "quarterly"


# ---------------------------------------------------------------------------
# T4-b: 429 triggers backoff (mock the use case, fail then succeed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_then_success_uses_backoff_and_counts_both() -> None:
    """First call raises ProviderRateLimited → worker sleeps via backoff →
    second call succeeds. Verifies counter increments for both outcomes and
    that the test seam's ``sleep_fn`` was awaited (proves backoff ran).
    """
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    worker = FundamentalsRefreshWorker(settings=_settings(), sleep_fn=fake_sleep)
    worker._write_factory = object()
    worker._read_factory = object()

    rate_limited_before = _counter_value("NVDA", "rate_limited")
    ok_before = _counter_value("NVDA", "ok")

    call_count = {"n": 0}

    async def execute_side_effect(**_kwargs: Any) -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # No retry_after hint — exercises the pure exponential path.
            raise ProviderRateLimited("EODHD 429")
        return None

    fake_use_case = SimpleNamespace(execute=AsyncMock(side_effect=execute_side_effect))
    with (
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.SqlaUnitOfWork",
            return_value=object(),
        ),
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.TriggerIngestionUseCase",
            return_value=fake_use_case,
        ),
    ):
        await worker._refresh_one(Provider.EODHD, "quarterly", "NVDA")

    assert call_count["n"] == 2, "expected one retry after the 429"
    assert len(sleep_calls) == 1, "expected exactly one backoff sleep"
    # First attempt → base * factor**0 = 5s ± 20% jitter → range [4, 6] roughly.
    # We assert non-trivial sleep but allow jitter slack.
    assert 0.0 < sleep_calls[0] <= 60.0

    assert _counter_value("NVDA", "rate_limited") == rate_limited_before + 1
    assert _counter_value("NVDA", "ok") == ok_before + 1


@pytest.mark.asyncio
async def test_rate_limited_max_attempts_gives_up_without_ok_counter() -> None:
    """If every attempt raises 429 the worker stops after ``_BACKOFF_MAX_ATTEMPTS``
    and only the ``rate_limited`` counter advances.
    """
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    worker = FundamentalsRefreshWorker(settings=_settings(), sleep_fn=fake_sleep)
    worker._write_factory = object()
    worker._read_factory = object()

    rate_limited_before = _counter_value("AMD", "rate_limited")
    ok_before = _counter_value("AMD", "ok")

    fake_use_case = SimpleNamespace(execute=AsyncMock(side_effect=ProviderRateLimited("EODHD 429")))
    with (
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.SqlaUnitOfWork",
            return_value=object(),
        ),
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.TriggerIngestionUseCase",
            return_value=fake_use_case,
        ),
    ):
        await worker._refresh_one(Provider.EODHD, "quarterly", "AMD")

    # _BACKOFF_MAX_ATTEMPTS = 4 → 4 attempts, 3 sleeps (no sleep after the last fail).
    assert _counter_value("AMD", "rate_limited") == rate_limited_before + 4
    assert _counter_value("AMD", "ok") == ok_before, "must not record ok on full failure"
    assert len(sleep_calls) == 3


def test_compute_backoff_respects_retry_after_hint() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings())
    # Hint of 30s on attempt 1 — base would only be 5s, hint should win.
    # Worker clamps to _BACKOFF_MAX_SECONDS = 60s.
    delay = worker._compute_backoff_delay(attempt=1, hint_seconds=30.0)
    # 30 ± 20% jitter → [24, 36]; well below the 60s cap.
    assert 20.0 <= delay <= 40.0


def test_compute_backoff_clamps_to_max() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings())
    delay = worker._compute_backoff_delay(attempt=10, hint_seconds=None)
    # 5 * 2**9 = 2560s — must clamp to 60.
    assert delay <= 60.0


# ---------------------------------------------------------------------------
# Error path — non-rate-limit exception increments ``error`` and exits.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_error_increments_error_counter_and_does_not_retry() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings())
    worker._write_factory = object()
    worker._read_factory = object()

    error_before = _counter_value("TSLA", "error")

    fake_use_case = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("boom")))
    with (
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.SqlaUnitOfWork",
            return_value=object(),
        ),
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.TriggerIngestionUseCase",
            return_value=fake_use_case,
        ),
    ):
        await worker._refresh_one(Provider.EODHD, "quarterly", "TSLA")

    assert _counter_value("TSLA", "error") == error_before + 1
    # And no retries happened (called exactly once).
    fake_use_case.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# Invalid config — provider/variant mismatch logs an error and skips the tick.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_provider_skips_tick_without_calls() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_provider="nope"))
    worker._write_factory = object()
    worker._read_factory = object()

    fake_use_case = SimpleNamespace(execute=AsyncMock())
    with patch(
        "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.TriggerIngestionUseCase",
        return_value=fake_use_case,
    ):
        await worker._tick()

    fake_use_case.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_variant_skips_tick_without_calls() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_variant="hourly"))
    worker._write_factory = object()
    worker._read_factory = object()

    fake_use_case = SimpleNamespace(execute=AsyncMock())
    with patch(
        "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.TriggerIngestionUseCase",
        return_value=fake_use_case,
    ):
        await worker._tick()

    fake_use_case.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# stop() halts the loop promptly between symbols.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_event_short_circuits_symbol_loop() -> None:
    worker = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_symbols="A,B,C,D,E"))
    worker._write_factory = object()
    worker._read_factory = object()

    # Stop after the first refresh.
    seen: list[str] = []

    async def execute_side_effect(*, symbols: list[str], **_kwargs: Any) -> None:
        seen.extend(symbols)
        worker.stop()

    fake_use_case = SimpleNamespace(execute=AsyncMock(side_effect=execute_side_effect))
    with (
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.SqlaUnitOfWork",
            return_value=object(),
        ),
        patch(
            "market_ingestion.infrastructure.workers.fundamentals_refresh_worker.TriggerIngestionUseCase",
            return_value=fake_use_case,
        ),
    ):
        await worker._tick()

    # After the first symbol succeeded the loop checked _stop_event and broke.
    assert seen == ["A"]
