"""Unit tests for the Alpaca daily OHLCV backfill's pure + produce-path logic.

These cover the resumable-cursor, Alpaca-eligibility filter, horizon-windowing,
dry-run (fetch-nothing) and produce-path (task-claimed + provider=ALPACA)
behaviour. The full in-cluster I/O run is human-executed, not tested here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.unit

from market_ingestion.domain.entities.polling_policy import PollingPolicy
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.scripts.backfill_alpaca_daily_ohlcv import (
    CURSOR_KEY,
    dedupe_ohlcv_instruments,
    is_alpaca_eligible,
    remaining_instruments,
    resolve_horizon,
    symbol_sort_key,
)


class TestResolveHorizon:
    def test_years_default_spans_six_years(self) -> None:
        now = datetime(2026, 7, 16, tzinfo=UTC)
        from_dt, to_dt = resolve_horizon(years=None, from_date=None, to_date=None, now=now)
        assert to_dt == now
        # default 6 years == 6 * 365 days (Alpaca IEX daily depth ~2020-07-27)
        assert (to_dt - from_dt) == timedelta(days=6 * 365)

    def test_from_to_override_years(self) -> None:
        from_dt, to_dt = resolve_horizon(years=5, from_date="2020-07-27", to_date="2026-07-16")
        assert from_dt == datetime(2020, 7, 27, tzinfo=UTC)
        assert to_dt == datetime(2026, 7, 16, tzinfo=UTC)
        assert from_dt.tzinfo is not None and to_dt.tzinfo is not None

    def test_empty_window_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            resolve_horizon(years=None, from_date="2025-01-01", to_date="2024-01-01")


class TestAlpacaEligibility:
    def test_us_and_cc_eligible(self) -> None:
        assert is_alpaca_eligible("US")
        assert is_alpaca_eligible("CC")
        assert is_alpaca_eligible("us")  # case-insensitive

    def test_indices_forex_nonus_ineligible(self) -> None:
        assert not is_alpaca_eligible("INDX")
        assert not is_alpaca_eligible("FOREX")
        assert not is_alpaca_eligible("SHG")
        assert not is_alpaca_eligible(None)
        assert not is_alpaca_eligible("")


class TestResumeCursor:
    def test_symbol_sort_key_normalises_exchange(self) -> None:
        assert symbol_sort_key("AAPL", "US") == "AAPL|US"
        assert symbol_sort_key("AAPL", None) == "AAPL|"

    def test_remaining_none_cursor_returns_all(self) -> None:
        insts = [("AAPL", "US"), ("MSFT", "US")]
        assert remaining_instruments(insts, None) == insts

    def test_remaining_drops_completed_up_to_and_including_cursor(self) -> None:
        insts = [("AAPL", "US"), ("MSFT", "US"), ("NVDA", "US"), ("TSLA", "US")]
        cursor = symbol_sort_key("MSFT", "US")
        assert remaining_instruments(insts, cursor) == [("NVDA", "US"), ("TSLA", "US")]

    def test_remaining_idempotent_when_all_done(self) -> None:
        insts = [("AAPL", "US"), ("MSFT", "US")]
        cursor = symbol_sort_key("MSFT", "US")
        assert remaining_instruments(insts, cursor) == []


def _policy(symbol: str | None, *, dataset=DatasetType.OHLCV, exchange="US", enabled=True) -> PollingPolicy:
    return PollingPolicy(
        provider=Provider.ALPACA,
        dataset_type=dataset,
        symbol=symbol,
        exchange=exchange,
        timeframe="1d",
        is_enabled=enabled,
    )


class TestDedupeUniverse:
    def test_filters_non_ohlcv_disabled_wildcard_and_ineligible_exchange(self) -> None:
        policies = [
            _policy("AAPL"),
            _policy("MSFT", dataset=DatasetType.QUOTES),  # not OHLCV → dropped
            _policy("GOOGL", enabled=False),  # disabled → dropped
            _policy(None),  # wildcard (no symbol) → dropped
            _policy("SPX", exchange="INDX"),  # index → Alpaca-ineligible → dropped
            _policy("EURUSD", exchange="FOREX"),  # forex → dropped
            _policy("BTC-USD", exchange="CC"),  # crypto → kept
            _policy("NVDA"),
        ]
        assert dedupe_ohlcv_instruments(policies) == [
            ("AAPL", "US"),
            ("BTC-USD", "CC"),
            ("NVDA", "US"),
        ]

    def test_dedupes_on_symbol_exchange(self) -> None:
        policies = [_policy("AAPL"), _policy("AAPL"), _policy("NVDA")]
        assert dedupe_ohlcv_instruments(policies) == [("AAPL", "US"), ("NVDA", "US")]

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

        from market_ingestion.scripts import backfill_alpaca_daily_ohlcv as mod

        universe = [("AAPL", "US"), ("MSFT", "US"), ("NVDA", "US")]

        valkey = MagicMock()
        valkey.get = AsyncMock(return_value=symbol_sort_key("AAPL", "US"))
        valkey.set = AsyncMock()
        valkey.close = AsyncMock()

        monkeypatch.setattr(
            "market_ingestion.infrastructure.db.session._build_factories",
            lambda _s=None: (MagicMock(), MagicMock()),
        )
        monkeypatch.setattr(mod, "create_valkey_client_from_url", lambda _u: valkey)
        monkeypatch.setattr(mod, "_list_ohlcv_instruments", AsyncMock(return_value=universe))

        settings = SimpleNamespace(valkey_url="redis://x")
        args = mod._parse_cli(["--years", "6", "--resume", "--dry-run"])

        produced = asyncio.run(mod.run_backfill(settings, args))  # type: ignore[arg-type]

        assert produced == 0
        valkey.get.assert_awaited_once()
        valkey.set.assert_not_awaited()
        valkey.close.assert_awaited_once()


class _AsyncCM:
    """Minimal async context manager wrapper around a value."""

    def __init__(self, value: object) -> None:
        self._value = value

    async def __aenter__(self) -> object:
        return self._value

    async def __aexit__(self, *exc: object) -> bool:
        return False


class TestProducePath:
    """The synthetic backfill task must be CLAIMED (PENDING → RUNNING) and carry
    provider=ALPACA (so downstream ``source='alpaca'`` → priority 110 wins over
    the incumbent Yahoo/EODHD daily rows)."""

    def test_task_running_and_provider_alpaca_and_cursor_checkpointed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from market_ingestion.domain.enums import IngestionTaskStatus
        from market_ingestion.scripts import backfill_alpaca_daily_ohlcv as mod

        universe = [("AAPL", "US")]

        valkey = MagicMock()
        valkey.get = AsyncMock(return_value=None)
        valkey.set = AsyncMock()
        valkey.close = AsyncMock()

        fake_uow = MagicMock()
        fake_uow.tasks.add_many = AsyncMock()
        fake_uow.commit = AsyncMock()
        fake_uow.rollback = AsyncMock()

        seen: list[tuple[IngestionTaskStatus, str]] = []

        class _StubUseCase:
            def __init__(self, **_kw: object) -> None:
                pass

            async def execute_with_prefetched_result(self, task: object, _fr: object) -> None:
                seen.append((task.status, str(task.provider)))  # type: ignore[attr-defined]

        monkeypatch.setattr(
            "market_ingestion.application.use_cases.execute_task.ExecuteTaskUseCase",
            _StubUseCase,
        )
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
        monkeypatch.setattr(mod, "pg_advisory_lock", lambda *_a, **_k: _AsyncCM(True))

        alpaca_adapter = MagicMock()
        alpaca_adapter.fetch_ohlcv = AsyncMock(
            return_value=SimpleNamespace(bars_returned=1500, provider=Provider.ALPACA)
        )
        registry = MagicMock()
        registry.get = MagicMock(return_value=alpaca_adapter)
        registry.aclose = AsyncMock()
        monkeypatch.setattr(
            "market_ingestion.infrastructure.adapters.providers.build_provider_registry",
            lambda *_a, **_k: registry,
        )

        settings = SimpleNamespace(
            valkey_url="redis://x",
            provider_http_timeout_seconds=30.0,
            bronze_bucket="b",
            canonical_bucket="c",
        )
        args = mod._parse_cli(["--years", "6", "--sleep", "0"])

        produced = asyncio.run(mod.run_backfill(settings, args))  # type: ignore[arg-type]

        assert produced == 1
        assert seen == [(IngestionTaskStatus.RUNNING, Provider.ALPACA.value)]
        valkey.set.assert_any_await(CURSOR_KEY, symbol_sort_key("AAPL", "US"))

    def test_zero_bars_checkpoints_and_does_not_produce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A symbol Alpaca has no daily history for is checkpointed (so --resume
        skips it) but produces nothing downstream."""
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from market_ingestion.scripts import backfill_alpaca_daily_ohlcv as mod

        universe = [("NEWCO", "US")]

        valkey = MagicMock()
        valkey.get = AsyncMock(return_value=None)
        valkey.set = AsyncMock()
        valkey.close = AsyncMock()

        monkeypatch.setattr(
            "market_ingestion.infrastructure.db.session._build_factories",
            lambda _s=None: (MagicMock(return_value=_AsyncCM(MagicMock())), MagicMock()),
        )
        monkeypatch.setattr(mod, "create_valkey_client_from_url", lambda _u: valkey)
        monkeypatch.setattr(mod, "_list_ohlcv_instruments", AsyncMock(return_value=universe))
        monkeypatch.setattr(mod, "_build_object_store", lambda *_a, **_k: MagicMock())
        monkeypatch.setattr(mod, "pg_advisory_lock", lambda *_a, **_k: _AsyncCM(True))

        alpaca_adapter = MagicMock()
        alpaca_adapter.fetch_ohlcv = AsyncMock(return_value=SimpleNamespace(bars_returned=0, provider=Provider.ALPACA))
        registry = MagicMock()
        registry.get = MagicMock(return_value=alpaca_adapter)
        registry.aclose = AsyncMock()
        monkeypatch.setattr(
            "market_ingestion.infrastructure.adapters.providers.build_provider_registry",
            lambda *_a, **_k: registry,
        )

        settings = SimpleNamespace(
            valkey_url="redis://x",
            provider_http_timeout_seconds=30.0,
            bronze_bucket="b",
            canonical_bucket="c",
        )
        args = mod._parse_cli(["--years", "6", "--sleep", "0"])

        produced = asyncio.run(mod.run_backfill(settings, args))  # type: ignore[arg-type]

        assert produced == 0
        # zero-bar symbol is still checkpointed so a resume skips it
        valkey.set.assert_any_await(CURSOR_KEY, symbol_sort_key("NEWCO", "US"))
