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

pytestmark = pytest.mark.unit


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
        # PLAN-0100 T-W5-02: default OFF in the test helper so legacy tests
        # that exercise ``_tick`` don't trigger live HTTP calls to
        # market-data. The W5-specific tests override this back to True.
        "fundamentals_refresh_use_internal_endpoint": False,
        "market_data_url": "http://market-data-test:8003",
        "internal_jwt_private_key": "",
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
    # PLAN-0100 W4-T03: default is now ``True``. Operators retain opt-out by
    # explicitly setting ``FUNDAMENTALS_REFRESH_ENABLED=false``; this test
    # exercises that explicit-False path.
    worker = FundamentalsRefreshWorker(settings=_settings(fundamentals_refresh_enabled=False))

    # If the worker tried to build DB factories we'd see _build_factories
    # called; patch it to a hard failure so any attempt would blow up.
    with patch(
        "market_ingestion.infrastructure.workers.fundamentals_refresh_worker._build_factories",
        side_effect=AssertionError("must not build infra when disabled"),
    ):
        await worker.run()  # Should return immediately; no AssertionError raised.

    assert worker.enabled is False


def test_real_settings_default_enables_worker() -> None:
    """PLAN-0100 W4-T03: the production ``Settings`` default must be ON.

    Regression guard against a silent re-flip back to ``False``. Reads the
    actual pydantic Settings class field default rather than the
    ``SimpleNamespace`` stub used by other tests, so a future revert is
    caught even when the test stub still says ``True``.
    """
    from market_ingestion.config import Settings

    assert Settings.model_fields["fundamentals_refresh_enabled"].default is True


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
# T-W5-02 (PLAN-0100) — symbol-source resolution via internal market-data endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_symbol_universe_uses_endpoint_when_no_csv_override() -> None:
    """Endpoint enabled + no CSV override → worker calls _fetch_top_n_symbols
    and uses the returned list verbatim (does not fall back to the default CSV).
    """
    worker = FundamentalsRefreshWorker(
        settings=_settings(
            fundamentals_refresh_top_n=3,
            fundamentals_refresh_use_internal_endpoint=True,
        ),
    )
    expected = ["NVDA", "MSFT", "AAPL"]
    with patch.object(worker, "_fetch_top_n_symbols", AsyncMock(return_value=expected)) as fetch:
        symbols = await worker._resolve_symbol_universe()
    assert symbols == expected
    fetch.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_resolve_symbol_universe_falls_back_to_default_when_endpoint_empty() -> None:
    """Endpoint returns empty list → worker falls back to the curated CSV."""
    worker = FundamentalsRefreshWorker(
        settings=_settings(
            fundamentals_refresh_top_n=5,
            fundamentals_refresh_use_internal_endpoint=True,
        ),
    )
    with patch.object(worker, "_fetch_top_n_symbols", AsyncMock(return_value=[])):
        symbols = await worker._resolve_symbol_universe()
    # Fallback list is mega-cap-first → AAPL leads, capped to 5.
    assert symbols[0] == "AAPL"
    assert len(symbols) == 5


@pytest.mark.asyncio
async def test_resolve_symbol_universe_csv_override_wins_over_endpoint() -> None:
    """CSV override → endpoint is NOT called, override list is used."""
    worker = FundamentalsRefreshWorker(
        settings=_settings(
            fundamentals_refresh_symbols="zzz,yyy,xxx",
            fundamentals_refresh_top_n=10,
            fundamentals_refresh_use_internal_endpoint=True,
        )
    )
    with patch.object(worker, "_fetch_top_n_symbols", AsyncMock(return_value=["A", "B"])) as fetch:
        symbols = await worker._resolve_symbol_universe()
    assert symbols == ["ZZZ", "YYY", "XXX"]
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_symbol_universe_skips_endpoint_when_flag_disabled() -> None:
    """``FUNDAMENTALS_REFRESH_USE_INTERNAL_ENDPOINT=false`` → endpoint is NOT called."""
    worker = FundamentalsRefreshWorker(
        settings=_settings(
            fundamentals_refresh_use_internal_endpoint=False,
            fundamentals_refresh_top_n=3,
        )
    )
    with patch.object(worker, "_fetch_top_n_symbols", AsyncMock(return_value=["X"])) as fetch:
        symbols = await worker._resolve_symbol_universe()
    fetch.assert_not_awaited()
    # Goes straight to CSV/default — default list, capped to 3.
    assert symbols == ["AAPL", "MSFT", "NVDA"]


@pytest.mark.asyncio
async def test_fetch_top_n_symbols_returns_symbols_on_200() -> None:
    """Successful HTTP call → uppercased symbols extracted from results,
    and the worker propagates the ``X-Internal-JWT`` header.
    """
    import httpx as _httpx
    from market_ingestion.infrastructure.workers import fundamentals_refresh_worker as mod

    worker = FundamentalsRefreshWorker(settings=_settings())
    fake_payload = {
        "total": 3,
        "offset": 0,
        "limit": 3,
        "results": [
            {"symbol": "aapl", "exchange": "US", "market_cap_usd": 3e12, "id": "x", "currency_code": "USD"},
            {"symbol": "msft", "exchange": "US", "market_cap_usd": 3e12, "id": "y", "currency_code": "USD"},
            {"symbol": "nvda", "exchange": "US", "market_cap_usd": 3e12, "id": "z", "currency_code": "USD"},
        ],
    }
    seen_headers: dict[str, str] = {}

    def _handler(req: _httpx.Request) -> _httpx.Response:
        seen_headers.update(dict(req.headers))
        return _httpx.Response(200, json=fake_payload)

    transport = _httpx.MockTransport(_handler)
    real_async_client = _httpx.AsyncClient

    def _client_factory(*args: Any, **kwargs: Any) -> _httpx.AsyncClient:
        kwargs.setdefault("transport", transport)
        return real_async_client(*args, **kwargs)

    with patch.object(mod.httpx, "AsyncClient", _client_factory):
        symbols = await worker._fetch_top_n_symbols(3)

    assert symbols == ["AAPL", "MSFT", "NVDA"]
    # X-Internal-JWT must be present so market-data accepts the call.
    assert "x-internal-jwt" in {k.lower() for k in seen_headers}


@pytest.mark.asyncio
async def test_fetch_top_n_symbols_returns_empty_on_5xx() -> None:
    """5xx from market-data → empty list (triggers the curated-CSV fallback)."""
    import httpx as _httpx
    from market_ingestion.infrastructure.workers import fundamentals_refresh_worker as mod

    worker = FundamentalsRefreshWorker(settings=_settings())

    def _handler(_req: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(503, json={"detail": "down"})

    transport = _httpx.MockTransport(_handler)
    real_async_client = _httpx.AsyncClient

    def _client_factory(*args: Any, **kwargs: Any) -> _httpx.AsyncClient:
        kwargs.setdefault("transport", transport)
        return real_async_client(*args, **kwargs)

    with patch.object(mod.httpx, "AsyncClient", _client_factory):
        symbols = await worker._fetch_top_n_symbols(10)

    assert symbols == []


@pytest.mark.asyncio
async def test_fetch_top_n_symbols_returns_empty_on_network_error() -> None:
    """Connection error → empty list (broad except catches; no exception escapes)."""
    import httpx as _httpx
    from market_ingestion.infrastructure.workers import fundamentals_refresh_worker as mod

    worker = FundamentalsRefreshWorker(settings=_settings())

    def _handler(_req: _httpx.Request) -> _httpx.Response:
        raise _httpx.ConnectError("connection refused")

    transport = _httpx.MockTransport(_handler)
    real_async_client = _httpx.AsyncClient

    def _client_factory(*args: Any, **kwargs: Any) -> _httpx.AsyncClient:
        kwargs.setdefault("transport", transport)
        return real_async_client(*args, **kwargs)

    with patch.object(mod.httpx, "AsyncClient", _client_factory):
        symbols = await worker._fetch_top_n_symbols(10)

    assert symbols == []


def test_sign_internal_jwt_returns_hs256_dev_token_when_no_key() -> None:
    """No RS256 key configured → worker emits a 3-segment HS256 dev token."""
    worker = FundamentalsRefreshWorker(settings=_settings())  # internal_jwt_private_key=""
    token = worker._sign_internal_jwt()
    # JWT structure: header.payload.signature.
    assert token.count(".") == 2
    assert len(token) > 20


def test_sign_internal_jwt_includes_aud_and_jti() -> None:
    """DEF-002: token MUST carry aud + a unique jti (required by middleware)."""
    import jwt as pyjwt

    worker = FundamentalsRefreshWorker(settings=_settings())
    decoded = pyjwt.decode(worker._sign_internal_jwt(), options={"verify_signature": False})
    assert decoded["aud"] == "worldview-internal"
    assert decoded["iss"] == "worldview-gateway"
    assert decoded["sub"] == "system:fundamentals-refresh-worker"
    assert decoded["jti"]


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
