"""Unit tests for the daily OHLCV backfill's pure windowing / resume / budget logic.

These cover the resumable-cursor, universe-dedup, horizon-windowing, and
credit-budget helpers of ``backfill_daily_ohlcv`` — the parts that must be
correct for the K8s Job to be safely re-runnable without re-spending credits or
double-fetching. The I/O runner is exercised in-cluster (human-run), not here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.unit

from market_ingestion.domain.entities.polling_policy import PollingPolicy
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.scripts.backfill_daily_ohlcv import (
    CURSOR_KEY,
    RunBudget,
    _parse_cli,
    dedupe_ohlcv_instruments,
    filter_instruments_by_exchange,
    remaining_instruments,
    resolve_horizon,
    resolve_produced_provider,
    symbol_sort_key,
)

_EXCH_UNIVERSE = [("AAPL", "US"), ("SPY", "US"), ("GSPC", "INDX"), ("BTC-USD", "CC"), ("EURUSD", "FOREX")]


class TestExchangeFilter:
    def test_none_keeps_whole_universe(self) -> None:
        assert filter_instruments_by_exchange(_EXCH_UNIVERSE, None) == _EXCH_UNIVERSE

    def test_allowlist_excludes_crypto_and_forex(self) -> None:
        kept = filter_instruments_by_exchange(_EXCH_UNIVERSE, "US,INDX,SHG")
        assert ("BTC-USD", "CC") not in kept
        assert ("EURUSD", "FOREX") not in kept
        assert ("AAPL", "US") in kept and ("GSPC", "INDX") in kept

    def test_allowlist_is_case_insensitive(self) -> None:
        assert filter_instruments_by_exchange(_EXCH_UNIVERSE, "us") == [("AAPL", "US"), ("SPY", "US")]


class TestAuthoritativeMode:
    def test_default_is_deep_history_eodhd(self) -> None:
        assert resolve_produced_provider(authoritative=False) is Provider.EODHD

    def test_authoritative_stamps_eodhd_bulk(self) -> None:
        # eodhd_bulk resolves to market-data priority 120 (> Alpaca 110), so the
        # corrected bars overwrite the Alpaca-won daily rows.
        assert resolve_produced_provider(authoritative=True) is Provider.EODHD_BULK

    def test_cli_authoritative_flag_defaults_off(self) -> None:
        assert _parse_cli([]).authoritative is False
        assert _parse_cli(["--authoritative"]).authoritative is True


class TestResolveHorizon:
    def test_years_default_spans_two_years(self) -> None:
        now = datetime(2026, 7, 15, tzinfo=UTC)
        from_dt, to_dt = resolve_horizon(years=None, from_date=None, to_date=None, now=now)
        assert to_dt == now
        # default 2 years == 730 days
        assert (to_dt - from_dt) == timedelta(days=730)

    def test_explicit_years(self) -> None:
        now = datetime(2026, 7, 15, tzinfo=UTC)
        from_dt, to_dt = resolve_horizon(years=1, from_date=None, to_date=None, now=now)
        assert (to_dt - from_dt) == timedelta(days=365)

    def test_from_to_override_years(self) -> None:
        from_dt, to_dt = resolve_horizon(years=5, from_date="2024-01-01", to_date="2024-12-31")
        assert from_dt == datetime(2024, 1, 1, tzinfo=UTC)
        assert to_dt == datetime(2024, 12, 31, tzinfo=UTC)
        # both boundaries are tz-aware (DateRange requires it)
        assert from_dt.tzinfo is not None and to_dt.tzinfo is not None

    def test_days_trailing_window_overrides_years(self) -> None:
        now = datetime(2026, 7, 15, tzinfo=UTC)
        from_dt, to_dt = resolve_horizon(years=2, from_date=None, to_date=None, days=5, now=now)
        assert to_dt == now
        assert (to_dt - from_dt) == timedelta(days=5)

    def test_from_date_overrides_days(self) -> None:
        from_dt, to_dt = resolve_horizon(years=None, from_date="2024-01-01", to_date="2024-12-31", days=5)
        assert from_dt == datetime(2024, 1, 1, tzinfo=UTC)
        assert to_dt == datetime(2024, 12, 31, tzinfo=UTC)

    def test_empty_window_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            resolve_horizon(years=None, from_date="2025-01-01", to_date="2024-01-01")


class TestResumeCursor:
    def test_symbol_sort_key_normalises_exchange(self) -> None:
        assert symbol_sort_key("AAPL", "US") == "AAPL|US"
        assert symbol_sort_key("AAPL", None) == "AAPL|"

    def test_remaining_none_cursor_returns_all(self) -> None:
        insts = [("AAPL", "US"), ("MSFT", "US")]
        assert remaining_instruments(insts, None) == insts

    def test_remaining_drops_completed_up_to_and_including_cursor(self) -> None:
        insts = [("AAPL", "US"), ("MSFT", "US"), ("NVDA", "US"), ("TSLA", "US")]
        # cursor is the last COMPLETED key → resume strictly after it.
        cursor = symbol_sort_key("MSFT", "US")
        assert remaining_instruments(insts, cursor) == [("NVDA", "US"), ("TSLA", "US")]

    def test_remaining_idempotent_when_all_done(self) -> None:
        insts = [("AAPL", "US"), ("MSFT", "US")]
        cursor = symbol_sort_key("MSFT", "US")
        assert remaining_instruments(insts, cursor) == []


def _policy(symbol: str | None, *, dataset=DatasetType.OHLCV, exchange="US", enabled=True) -> PollingPolicy:
    return PollingPolicy(
        provider=Provider.EODHD,
        dataset_type=dataset,
        symbol=symbol,
        exchange=exchange,
        timeframe="1d",
        is_enabled=enabled,
    )


class TestDedupeUniverse:
    def test_filters_non_ohlcv_disabled_and_wildcard(self) -> None:
        policies = [
            _policy("AAPL"),
            _policy("MSFT", dataset=DatasetType.QUOTES),  # not OHLCV → dropped
            _policy("GOOGL", enabled=False),  # disabled → dropped
            _policy(None),  # wildcard (no symbol) → dropped
            _policy("NVDA"),
        ]
        assert dedupe_ohlcv_instruments(policies) == [("AAPL", "US"), ("NVDA", "US")]

    def test_dedupes_on_symbol_exchange(self) -> None:
        policies = [_policy("AAPL"), _policy("AAPL"), _policy("AAPL", exchange="LSE")]
        # (AAPL, US) deduped once; (AAPL, LSE) is a distinct instrument.
        assert dedupe_ohlcv_instruments(policies) == [("AAPL", "LSE"), ("AAPL", "US")]

    def test_output_sorted_for_monotonic_cursor(self) -> None:
        policies = [_policy("TSLA"), _policy("AAPL"), _policy("MSFT")]
        result = dedupe_ohlcv_instruments(policies)
        assert result == sorted(result, key=lambda p: symbol_sort_key(p[0], p[1]))


class TestDryRunFetchesNothing:
    def test_dry_run_resumes_and_fetches_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--dry-run + --resume: applies the cursor, prints the plan, calls no
        provider fetch and no Valkey writes (fetch-nothing guarantee)."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from market_ingestion.scripts import backfill_daily_ohlcv as mod

        universe = [("AAPL", "US"), ("MSFT", "US"), ("NVDA", "US")]

        # Fake Valkey: resume cursor = AAPL (so only MSFT, NVDA remain).
        valkey = MagicMock()
        valkey.get = AsyncMock(return_value=symbol_sort_key("AAPL", "US"))
        valkey.set = AsyncMock()
        valkey.close = AsyncMock()

        # ``_build_factories`` is imported locally inside run_backfill, so patch it
        # at its source module (rebound at call time).
        monkeypatch.setattr(
            "market_ingestion.infrastructure.db.session._build_factories",
            lambda _s=None: (MagicMock(), MagicMock()),
        )
        monkeypatch.setattr(mod, "create_valkey_client_from_url", lambda _u: valkey)
        monkeypatch.setattr(mod, "_list_ohlcv_instruments", AsyncMock(return_value=universe))

        settings = SimpleNamespace(valkey_url="redis://x", eodhd_daily_quota=100_000, eodhd_monthly_quota=100_000)
        args = mod._parse_cli(["--years", "2", "--resume", "--dry-run"])

        produced = asyncio.run(mod.run_backfill(settings, args))  # type: ignore[arg-type]

        assert produced == 0
        valkey.get.assert_awaited_once()  # cursor read (resume)
        valkey.set.assert_not_awaited()  # dry-run writes no checkpoint
        valkey.close.assert_awaited_once()


class _AsyncCM:
    """Minimal async context manager wrapper around a value."""

    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *exc: object) -> bool:
        return False


class TestProducePathClaimsTask:
    """Regression (2026-07-16 prod review): the synthetic backfill task must be
    CLAIMED (PENDING → RUNNING) before ``execute_with_prefetched_result``.

    Root cause found live: run1 produced 0/96 with
    ``Cannot succeed task in status PENDING; must be RUNNING`` — the terminal
    ``task.succeed()`` in ``commit_transaction`` raised, rolling back the whole
    Step-5 transaction incl. the ``MarketDatasetFetched`` outbox event, so the
    backfill spent an EODHD credit per symbol and advanced no cursor while
    materialising nothing downstream. This test pins the task's status at the
    moment it is handed to the produce path.
    """

    def test_task_is_running_when_produced_and_cursor_checkpointed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from market_ingestion.domain.enums import IngestionTaskStatus
        from market_ingestion.scripts import backfill_daily_ohlcv as mod

        universe = [("AAPL", "US")]

        valkey = MagicMock()
        valkey.get = AsyncMock(return_value=None)
        valkey.set = AsyncMock()
        valkey.close = AsyncMock()

        # A fake unit-of-work: the enqueue path calls tasks.add_many + commit.
        fake_uow = MagicMock()
        fake_uow.tasks.add_many = AsyncMock()
        fake_uow.commit = AsyncMock()
        fake_uow.rollback = AsyncMock()

        # ExecuteTaskUseCase is imported *inside* run_backfill from its source
        # module — patch it there. The stub records the task status at call time,
        # which is exactly what the fix guarantees is RUNNING (not PENDING).
        seen_status: list[IngestionTaskStatus] = []

        class _StubUseCase:
            def __init__(self, **_kw: object) -> None:
                pass

            async def execute_with_prefetched_result(self, task: object, _fr: object) -> None:
                seen_status.append(task.status)  # type: ignore[attr-defined]

        monkeypatch.setattr(
            "market_ingestion.application.use_cases.execute_task.ExecuteTaskUseCase",
            _StubUseCase,
        )
        # SqlaUnitOfWork() (the enqueue uow) and the write_factory lock session.
        monkeypatch.setattr(
            "market_ingestion.infrastructure.db.unit_of_work.SqlaUnitOfWork",
            lambda *_a, **_k: _AsyncCM(fake_uow),
        )
        write_factory = MagicMock(return_value=_AsyncCM(MagicMock()))
        monkeypatch.setattr(
            "market_ingestion.infrastructure.db.session._build_factories",
            lambda _s=None: (write_factory, MagicMock()),
        )
        monkeypatch.setattr(mod, "create_valkey_client_from_url", lambda _u: valkey)
        monkeypatch.setattr(mod, "_list_ohlcv_instruments", AsyncMock(return_value=universe))
        monkeypatch.setattr(mod, "_build_object_store", lambda *_a, **_k: MagicMock())
        # Advisory lock: acquired.
        monkeypatch.setattr(mod, "pg_advisory_lock", lambda *_a, **_k: _AsyncCM(True))

        quota = MagicMock()
        quota.get_daily_credits_used = AsyncMock(return_value=0)
        quota.record_usage = AsyncMock()
        monkeypatch.setattr(mod, "EodhdQuotaService", lambda **_k: quota)

        eodhd_adapter = MagicMock()
        eodhd_adapter.fetch_ohlcv = AsyncMock(return_value=SimpleNamespace(bars_returned=1, provider=Provider.EODHD))
        registry = MagicMock()
        registry.get = MagicMock(return_value=eodhd_adapter)
        registry.aclose = AsyncMock()
        monkeypatch.setattr(
            "market_ingestion.infrastructure.adapters.providers.build_provider_registry",
            lambda *_a, **_k: registry,
        )

        settings = SimpleNamespace(
            valkey_url="redis://x",
            eodhd_daily_quota=100_000,
            eodhd_monthly_quota=100_000,
            provider_http_timeout_seconds=30.0,
            bronze_bucket="b",
            canonical_bucket="c",
        )
        args = mod._parse_cli(["--years", "2"])

        produced = asyncio.run(mod.run_backfill(settings, args))  # type: ignore[arg-type]

        assert produced == 1
        # The core regression guard: the task was RUNNING (claimed), never PENDING.
        assert seen_status == [IngestionTaskStatus.RUNNING]
        # Progress was checkpointed so --resume advances (no infinite credit burn).
        valkey.set.assert_any_await(CURSOR_KEY, symbol_sort_key("AAPL", "US"))


class TestRunBudget:
    def test_run_cap_blocks_when_exceeded(self) -> None:
        b = RunBudget(max_credits=3, daily_cap=100_000, daily_headroom=0)
        assert not b.run_budget_exhausted(1)
        b.spent = 3
        assert b.run_budget_exhausted(1)  # 3 + 1 > 3

    def test_daily_headroom_guard(self) -> None:
        b = RunBudget(max_credits=10_000, daily_cap=100_000, daily_headroom=5_000)
        # remaining daily allowance = 100_000 - 5_000 = 95_000
        assert not b.daily_budget_exhausted(daily_used=94_999, next_estimate=1)
        assert b.daily_budget_exhausted(daily_used=95_000, next_estimate=1)  # 95_000 + 1 > 95_000

    def test_record_symbol_accumulates_one_credit(self) -> None:
        b = RunBudget(max_credits=10, daily_cap=100_000, daily_headroom=0)
        assert b.record_symbol() == 1
        assert b.record_symbol() == 1
        assert b.spent == 2
