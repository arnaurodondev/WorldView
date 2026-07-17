"""Unit tests for market_data domain value objects."""

from __future__ import annotations

import dataclasses

import pytest
from market_data.domain.enums import Provider
from market_data.domain.value_objects import InstrumentFlags, ProviderPriority

pytestmark = pytest.mark.unit


class TestInstrumentFlags:
    def test_construction_all_false(self) -> None:
        flags = InstrumentFlags()
        assert flags.has_ohlcv is False
        assert flags.has_quotes is False
        assert flags.has_fundamentals is False

    def test_construction_with_values(self) -> None:
        flags = InstrumentFlags(has_ohlcv=True, has_quotes=False, has_fundamentals=True)
        assert flags.has_ohlcv is True
        assert flags.has_quotes is False
        assert flags.has_fundamentals is True

    def test_field_access(self) -> None:
        flags = InstrumentFlags(has_ohlcv=True, has_quotes=True, has_fundamentals=True)
        assert flags.has_ohlcv
        assert flags.has_quotes
        assert flags.has_fundamentals

    def test_immutability(self) -> None:
        flags = InstrumentFlags(has_ohlcv=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            flags.has_ohlcv = False  # type: ignore[misc]

    def test_equality_structural(self) -> None:
        f1 = InstrumentFlags(has_ohlcv=True)
        f2 = InstrumentFlags(has_ohlcv=True)
        assert f1 == f2

    def test_inequality(self) -> None:
        f1 = InstrumentFlags(has_ohlcv=True)
        f2 = InstrumentFlags(has_ohlcv=False)
        assert f1 != f2

    def test_hashable(self) -> None:
        f1 = InstrumentFlags(has_ohlcv=True)
        f2 = InstrumentFlags(has_ohlcv=True)
        assert hash(f1) == hash(f2)
        # usable as dict key / set member
        s: set[InstrumentFlags] = {f1, f2}
        assert len(s) == 1


class TestProviderPriority:
    def test_construction(self) -> None:
        pp = ProviderPriority(provider="polygon", priority=100)
        assert pp.provider == "polygon"
        assert pp.priority == 100

    def test_field_access(self) -> None:
        pp = ProviderPriority(provider="yahoo", priority=80)
        assert pp.provider == "yahoo"
        assert pp.priority == 80

    def test_immutability(self) -> None:
        pp = ProviderPriority(provider="test", priority=50)
        with pytest.raises(dataclasses.FrozenInstanceError):
            pp.priority = 99  # type: ignore[misc]

    def test_for_provider_polygon(self) -> None:
        pp = ProviderPriority.for_provider(Provider.POLYGON)
        assert pp.provider == "polygon"
        assert pp.priority == 100

    def test_for_provider_yahoo(self) -> None:
        pp = ProviderPriority.for_provider(Provider.YAHOO)
        assert pp.provider == "yahoo"
        assert pp.priority == 80

    def test_for_provider_unknown(self) -> None:
        pp = ProviderPriority.for_provider(Provider.UNKNOWN)
        assert pp.provider == "unknown"
        assert pp.priority == 0

    def test_eodhd_bulk_is_authoritative_daily(self) -> None:
        # DAILY-VOLUME CORRECTION (2026-07-16): the EODHD bulk-EOD daily source
        # (correct consolidated volume + adjusted_close) MUST outrank Alpaca's
        # IEX daily bar so the ``provider_priority >=`` upsert guard lets it win.
        eodhd_bulk = ProviderPriority.for_provider(Provider.EODHD_BULK)
        assert eodhd_bulk.provider == "eodhd_bulk"
        assert eodhd_bulk.priority == 120
        # Strictly above Alpaca (110) — the whole point of the fix.
        assert eodhd_bulk.priority > ProviderPriority.for_provider(Provider.ALPACA).priority
        # And still above the per-ticker deep-history EODHD failover (60).
        assert eodhd_bulk.priority > ProviderPriority.for_provider(Provider.EODHD).priority

    def test_eodhd_bulk_resolves_from_string(self) -> None:
        # market-data resolves the event ``provider`` string via ``Provider(...)``;
        # the canonical source "eodhd_bulk" must map to the real member (not UNKNOWN).
        assert Provider("eodhd_bulk") is Provider.EODHD_BULK

    def test_for_provider_all_providers(self) -> None:
        for provider in Provider:
            pp = ProviderPriority.for_provider(provider)
            assert pp.provider == provider.value
            assert isinstance(pp.priority, int)

    def test_equality_structural(self) -> None:
        p1 = ProviderPriority(provider="polygon", priority=100)
        p2 = ProviderPriority(provider="polygon", priority=100)
        assert p1 == p2

    def test_hashable(self) -> None:
        p1 = ProviderPriority(provider="polygon", priority=100)
        p2 = ProviderPriority(provider="polygon", priority=100)
        assert hash(p1) == hash(p2)
