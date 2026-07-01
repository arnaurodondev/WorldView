"""Unit tests for InstrumentPolicySyncWorker (PLAN-0106 Wave D-1).

Covers:
- Disabled flag → ``run()`` returns immediately without touching infra.
- Config default is enabled (True).
- ``enabled`` property reads the correct settings attribute.
- ``_fetch_instruments`` returns [] for INDX/FOREX exchanges.
- ``_fetch_instruments`` returns [] on HTTP failure without crashing.
- ``_sign_internal_jwt`` falls back to HS256 dev token when no RS256 key.
- ``stop()`` sets the stop event.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from market_ingestion.infrastructure.workers.instrument_policy_sync_worker import (
    _SKIP_EXCHANGES,
    InstrumentPolicySyncWorker,
    _ulid_from_seed,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Settings stub helper
# ---------------------------------------------------------------------------


def _settings(**overrides: Any) -> SimpleNamespace:
    """Build a minimal settings stub for the sync worker."""
    base = {
        "instrument_policy_sync_enabled": True,
        "instrument_policy_sync_interval_hours": 6.0,
        "market_data_url": "http://market-data-test:8003",
        "internal_jwt_private_key": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# enabled / disabled flag
# ---------------------------------------------------------------------------


class TestEnabledFlag:
    def test_enabled_returns_true_by_default(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings())
        assert worker.enabled is True

    def test_enabled_returns_false_when_disabled(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings(instrument_policy_sync_enabled=False))
        assert worker.enabled is False

    def test_real_settings_default_is_true(self) -> None:
        """The production Settings class must default instrument_policy_sync_enabled to True."""
        from market_ingestion.config import Settings

        assert Settings.model_fields["instrument_policy_sync_enabled"].default is True

    @pytest.mark.asyncio
    async def test_disabled_run_returns_immediately_without_building_infra(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings(instrument_policy_sync_enabled=False))
        with patch(
            "market_ingestion.infrastructure.workers.instrument_policy_sync_worker._build_factories",
            side_effect=AssertionError("must not build infra when disabled"),
        ):
            await worker.run()  # Should return immediately without raising.
        assert worker.enabled is False


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_sets_stop_event(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings())
        assert not worker._stop_event.is_set()
        worker.stop()
        assert worker._stop_event.is_set()


# ---------------------------------------------------------------------------
# _ulid_from_seed — shared helper
# ---------------------------------------------------------------------------


class TestUlidFromSeed:
    def test_deterministic(self) -> None:
        seed = "alpaca:ohlcv:AAPL:US:1m:"
        assert _ulid_from_seed(seed) == _ulid_from_seed(seed)

    def test_length_is_26(self) -> None:
        assert len(_ulid_from_seed("alpaca:ohlcv:TSLA:US:1m:")) == 26

    def test_starts_with_01HX(self) -> None:
        assert _ulid_from_seed("alpaca:ohlcv:NVDA:US:1m:").startswith("01HX")

    def test_different_seeds_produce_different_ids(self) -> None:
        a = _ulid_from_seed("alpaca:ohlcv:AAPL:US:1m:")
        b = _ulid_from_seed("alpaca:ohlcv:TSLA:US:1m:")
        assert a != b

    def test_us_and_cc_same_symbol_differ(self) -> None:
        us = _ulid_from_seed("alpaca:ohlcv:BTC-USD:US:1m:")
        cc = _ulid_from_seed("alpaca:ohlcv:BTC-USD:CC:1m:")
        assert us != cc


# ---------------------------------------------------------------------------
# _SKIP_EXCHANGES
# ---------------------------------------------------------------------------


class TestSkipExchanges:
    def test_indx_is_skipped(self) -> None:
        assert "INDX" in _SKIP_EXCHANGES

    def test_forex_is_skipped(self) -> None:
        assert "FOREX" in _SKIP_EXCHANGES

    def test_us_is_not_skipped(self) -> None:
        assert "US" not in _SKIP_EXCHANGES

    def test_cc_is_not_skipped(self) -> None:
        assert "CC" not in _SKIP_EXCHANGES


# ---------------------------------------------------------------------------
# _fetch_instruments — skip exchanges + HTTP error path
# ---------------------------------------------------------------------------


class TestFetchInstruments:
    @pytest.mark.asyncio
    async def test_returns_empty_for_skip_exchanges(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings())
        for exch in ("INDX", "FOREX"):
            result = await worker._fetch_instruments(exch)
            assert result == [], f"Expected [] for {exch}"

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_2xx(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings())

        mock_resp = MagicMock()
        mock_resp.status_code = 503

        with patch(
            "market_ingestion.infrastructure.workers.instrument_policy_sync_worker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await worker._fetch_instruments("US")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_http_error(self) -> None:
        import httpx

        worker = InstrumentPolicySyncWorker(settings=_settings())

        with patch(
            "market_ingestion.infrastructure.workers.instrument_policy_sync_worker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
            mock_client_cls.return_value = mock_client

            result = await worker._fetch_instruments("US")

        assert result == []

    @pytest.mark.asyncio
    async def test_parses_results_envelope(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings())

        payload = {"results": [{"symbol": "AAPL", "exchange": "US"}, {"symbol": "MSFT", "exchange": "US"}]}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=payload)

        with patch(
            "market_ingestion.infrastructure.workers.instrument_policy_sync_worker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await worker._fetch_instruments("US")

        assert len(result) == 2
        assert result[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_parses_bare_list_response(self) -> None:
        worker = InstrumentPolicySyncWorker(settings=_settings())

        payload = [{"symbol": "BTC-USD", "exchange": "CC"}]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=payload)

        with patch(
            "market_ingestion.infrastructure.workers.instrument_policy_sync_worker.httpx.AsyncClient"
        ) as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value = mock_client

            result = await worker._fetch_instruments("CC")

        assert result == [{"symbol": "BTC-USD", "exchange": "CC"}]


# ---------------------------------------------------------------------------
# _sign_internal_jwt — HS256 dev path
# ---------------------------------------------------------------------------


class TestSignInternalJwt:
    def test_returns_hs256_token_when_no_private_key(self) -> None:
        import jwt as pyjwt

        worker = InstrumentPolicySyncWorker(settings=_settings(internal_jwt_private_key=""))
        token = worker._sign_internal_jwt()
        # HS256 dev key — decode without verification to check claims.
        decoded = pyjwt.decode(token, options={"verify_signature": False})
        assert decoded["sub"] == "system:instrument-policy-sync-worker"
        assert decoded["iss"] == "worldview-gateway"
        assert decoded["role"] == "system"
        # DEF-002: token MUST carry aud + a unique jti so it survives real
        # InternalJWTMiddleware verification once skip_verification is disabled.
        assert decoded["aud"] == "worldview-internal"
        assert decoded["jti"]

    def test_token_exp_is_in_the_future(self) -> None:
        import time

        import jwt as pyjwt

        worker = InstrumentPolicySyncWorker(settings=_settings())
        token = worker._sign_internal_jwt()
        decoded = pyjwt.decode(token, options={"verify_signature": False})
        assert decoded["exp"] > int(time.time())
