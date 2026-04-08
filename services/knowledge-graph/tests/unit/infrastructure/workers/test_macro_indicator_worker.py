"""Unit tests for MacroIndicatorWorker (Worker 13D-7) — PRD-0018 §6 Worker 13D-7."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_COUNTRY_ENTITY_ID = UUID("01910000-0000-7000-8000-000000000001")

# Patch path — source module path so lazy `from ... import X` picks up the mock
_ENTITY_REPO = "knowledge_graph.infrastructure.intelligence_db.repositories.entity_repository.EntityRepository"

# Default country map used in most tests
_COUNTRY_MAP = {"USA": "US"}

# Minimal EODHD macro indicator response
_GDP_RESPONSE = [{"Value": 25_000_000_000_000.0, "Period": "2023"}]
_INFLATION_RESPONSE = [{"Value": 3.4, "Period": "2023"}]

# All 6 indicators returning data
_ALL_INDICATORS_RESPONSE = {
    "gdp_current_usd": [{"Value": 25e12, "Period": "2023"}],
    "gdp_growth_annual": [{"Value": 2.5, "Period": "2023"}],
    "inflation_consumer_prices_annual": [{"Value": 3.4, "Period": "2023"}],
    "real_interest_rate": [{"Value": 1.5, "Period": "2023"}],
    "unemployment_total_pct": [{"Value": 3.7, "Period": "2023"}],
    "current_account_balance_bop_usd": [{"Value": -1e12, "Period": "2023"}],
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_entity_repo(
    country_entity_id: UUID | None = _COUNTRY_ENTITY_ID,
    old_hash: str | None = None,
) -> Any:
    """Build a mock EntityRepository instance."""
    entity_repo = AsyncMock()
    entity_repo.find_country_entity = AsyncMock(return_value=country_entity_id)
    entity_repo.get_metadata_hash = AsyncMock(return_value=old_hash)
    entity_repo.update_metadata = AsyncMock()
    return entity_repo


def _make_session_factory() -> Any:
    """Build a mock session factory."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    sf = MagicMock()
    sf.return_value = session
    return sf


def _make_eodhd_client(
    responses: dict[str, list[dict[str, Any]]] | None = None,
) -> Any:
    """Build a mock EodhDClient.

    Args:
        responses: Maps indicator_code → list of response dicts.
                   Defaults to returning _ALL_INDICATORS_RESPONSE for all codes.
    """
    client = AsyncMock()
    if responses is None:
        responses = _ALL_INDICATORS_RESPONSE

    async def get_macro_indicator(iso3: str, indicator_code: str) -> list[dict[str, Any]]:
        return responses.get(indicator_code, [])

    client.get_macro_indicator = AsyncMock(side_effect=get_macro_indicator)
    return client


def _make_direct_producer() -> Any:
    return MagicMock()


def _run_worker(
    eodhd_responses: dict[str, list[dict[str, Any]]] | None = None,
    country_entity_id: UUID | None = _COUNTRY_ENTITY_ID,
    old_hash: str | None = None,
    country_map: dict[str, str] | None = None,
    direct_producer: Any | None = None,
) -> tuple[Any, Any]:
    """Build worker + repos, patch EntityRepository class, run worker, return (entity_repo, producer)."""
    from knowledge_graph.infrastructure.workers.macro_indicator_worker import MacroIndicatorWorker

    if country_map is None:
        country_map = _COUNTRY_MAP

    entity_repo = _make_entity_repo(country_entity_id, old_hash)
    sf = _make_session_factory()
    eodhd_client = _make_eodhd_client(eodhd_responses)

    worker = MacroIndicatorWorker(
        session_factory=sf,
        eodhd_client=eodhd_client,
        country_map=country_map,
        direct_producer=direct_producer,
    )

    with patch(_ENTITY_REPO, return_value=entity_repo):
        asyncio.run(worker.run())

    return entity_repo, direct_producer


# ── Test: Metadata update on change ──────────────────────────────────────────


class TestMacroIndicatorWorkerUpdate:
    def test_update_when_hash_differs(self) -> None:
        """New indicators (hash mismatch) → update_metadata called and entity.dirtied produced."""
        producer = _make_direct_producer()
        entity_repo, _ = _run_worker(old_hash=None, direct_producer=producer)

        # update_metadata must be called once for the country
        entity_repo.update_metadata.assert_awaited_once()
        call_kwargs = entity_repo.update_metadata.call_args
        assert call_kwargs[0][0] == _COUNTRY_ENTITY_ID  # entity_id positional arg
        updates = call_kwargs[0][1]
        assert "macro_indicators" in updates
        macro = updates["macro_indicators"]
        assert "gdp_current_usd" in macro
        assert macro["gdp_current_usd"]["value"] == 25e12
        assert macro["gdp_current_usd"]["year"] == "2023"

        # entity.dirtied.v1 must be produced
        producer.produce_bytes.assert_called_once()
        produce_call = producer.produce_bytes.call_args
        assert produce_call.kwargs["topic"] == "entity.dirtied.v1"
        assert produce_call.kwargs["key"] == str(_COUNTRY_ENTITY_ID).encode()
        payload = json.loads(produce_call.kwargs["value"])
        assert payload["entity_id"] == str(_COUNTRY_ENTITY_ID)
        assert payload["dirty_reason"] == "macro_indicators_updated"

    def test_all_six_indicators_fetched(self) -> None:
        """All 6 EODHD indicator codes are requested per country."""
        from knowledge_graph.infrastructure.workers.macro_indicator_worker import MACRO_INDICATORS

        eodhd_client = _make_eodhd_client()
        entity_repo = _make_entity_repo(old_hash=None)
        sf = _make_session_factory()

        from knowledge_graph.infrastructure.workers.macro_indicator_worker import MacroIndicatorWorker

        worker = MacroIndicatorWorker(
            session_factory=sf,
            eodhd_client=eodhd_client,
            country_map={"USA": "US"},
        )
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(worker.run())

        assert eodhd_client.get_macro_indicator.await_count == len(MACRO_INDICATORS)
        called_codes = [c.args[1] for c in eodhd_client.get_macro_indicator.call_args_list]
        assert set(called_codes) == set(MACRO_INDICATORS)

    def test_session_committed_after_update(self) -> None:
        """session.commit() is called when metadata is updated."""
        eodhd_client = _make_eodhd_client()
        entity_repo = _make_entity_repo(old_hash=None)
        sf = _make_session_factory()

        from knowledge_graph.infrastructure.workers.macro_indicator_worker import MacroIndicatorWorker

        worker = MacroIndicatorWorker(
            session_factory=sf,
            eodhd_client=eodhd_client,
            country_map={"USA": "US"},
        )
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(worker.run())

        # The session mock is accessible via the factory's return_value
        sf.return_value.commit.assert_awaited_once()

    def test_multiple_countries_processed(self) -> None:
        """Worker processes multiple countries independently."""
        country_map = {"USA": "US", "GBR": "GB"}
        entity_repo = _make_entity_repo(old_hash=None)
        sf = _make_session_factory()
        eodhd_client = _make_eodhd_client()

        from knowledge_graph.infrastructure.workers.macro_indicator_worker import MACRO_INDICATORS, MacroIndicatorWorker

        worker = MacroIndicatorWorker(
            session_factory=sf,
            eodhd_client=eodhd_client,
            country_map=country_map,
        )
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(worker.run())

        # 6 indicators x 2 countries = 12 EODHD calls
        assert eodhd_client.get_macro_indicator.await_count == len(MACRO_INDICATORS) * 2
        # update_metadata called once per country
        assert entity_repo.update_metadata.await_count == 2


# ── Test: No update on same hash ──────────────────────────────────────────────


class TestMacroIndicatorWorkerNoChange:
    def test_no_update_when_hash_matches(self) -> None:
        """Same indicators as stored hash → update_metadata not called, no entity.dirtied."""
        from knowledge_graph.infrastructure.workers.macro_indicator_worker import _sha256_hex

        # Pre-compute the hash for the data that will be returned by the mock EODHD client
        macro_data = {
            "gdp_current_usd": {"value": 25e12, "year": "2023"},
            "gdp_growth_annual": {"value": 2.5, "year": "2023"},
            "inflation_consumer_prices_annual": {"value": 3.4, "year": "2023"},
            "real_interest_rate": {"value": 1.5, "year": "2023"},
            "unemployment_total_pct": {"value": 3.7, "year": "2023"},
            "current_account_balance_bop_usd": {"value": -1e12, "year": "2023"},
        }
        existing_hash = _sha256_hex(json.dumps(macro_data, sort_keys=True))

        producer = _make_direct_producer()
        entity_repo, _ = _run_worker(old_hash=existing_hash, direct_producer=producer)

        entity_repo.update_metadata.assert_not_awaited()
        producer.produce_bytes.assert_not_called()

    def test_no_commit_when_unchanged(self) -> None:
        """Session is not committed when no indicators changed."""
        from knowledge_graph.infrastructure.workers.macro_indicator_worker import _sha256_hex

        macro_data = {
            "gdp_current_usd": {"value": 25e12, "year": "2023"},
            "gdp_growth_annual": {"value": 2.5, "year": "2023"},
            "inflation_consumer_prices_annual": {"value": 3.4, "year": "2023"},
            "real_interest_rate": {"value": 1.5, "year": "2023"},
            "unemployment_total_pct": {"value": 3.7, "year": "2023"},
            "current_account_balance_bop_usd": {"value": -1e12, "year": "2023"},
        }
        existing_hash = _sha256_hex(json.dumps(macro_data, sort_keys=True))

        entity_repo = _make_entity_repo(old_hash=existing_hash)
        sf = _make_session_factory()
        eodhd_client = _make_eodhd_client()

        from knowledge_graph.infrastructure.workers.macro_indicator_worker import MacroIndicatorWorker

        worker = MacroIndicatorWorker(
            session_factory=sf,
            eodhd_client=eodhd_client,
            country_map={"USA": "US"},
        )
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(worker.run())

        sf.return_value.commit.assert_not_awaited()


# ── Test: Missing country entity ──────────────────────────────────────────────


class TestMacroIndicatorWorkerMissingCountryEntity:
    def test_skip_when_country_entity_not_found(self) -> None:
        """When find_country_entity returns None, update is skipped silently."""
        producer = _make_direct_producer()
        entity_repo, _ = _run_worker(country_entity_id=None, direct_producer=producer)

        entity_repo.update_metadata.assert_not_awaited()
        producer.produce_bytes.assert_not_called()

    def test_hash_not_checked_when_entity_missing(self) -> None:
        """get_metadata_hash is never called if the country entity doesn't exist."""
        entity_repo, _ = _run_worker(country_entity_id=None)

        entity_repo.get_metadata_hash.assert_not_awaited()


# ── Test: Empty EODHD response ────────────────────────────────────────────────


class TestMacroIndicatorWorkerEmptyResponse:
    def test_skip_when_all_indicators_empty(self) -> None:
        """If all indicator endpoints return empty lists, no DB operations are performed."""
        empty_responses: dict[str, list[dict[str, Any]]] = {}  # all return []
        producer = _make_direct_producer()
        entity_repo = _make_entity_repo()
        sf = _make_session_factory()
        eodhd_client = _make_eodhd_client(responses=empty_responses)

        from knowledge_graph.infrastructure.workers.macro_indicator_worker import MacroIndicatorWorker

        worker = MacroIndicatorWorker(
            session_factory=sf,
            eodhd_client=eodhd_client,
            country_map={"USA": "US"},
            direct_producer=producer,
        )
        with patch(_ENTITY_REPO, return_value=entity_repo):
            asyncio.run(worker.run())

        entity_repo.find_country_entity.assert_not_awaited()
        entity_repo.update_metadata.assert_not_awaited()
        producer.produce_bytes.assert_not_called()

    def test_partial_indicators_still_update(self) -> None:
        """If only some indicators return data, partial data is still stored."""
        partial_responses: dict[str, list[dict[str, Any]]] = {
            "gdp_current_usd": [{"Value": 25e12, "Period": "2023"}],
            # All other indicators return empty — not in dict
        }
        entity_repo, _ = _run_worker(eodhd_responses=partial_responses, old_hash=None)

        entity_repo.update_metadata.assert_awaited_once()
        updates = entity_repo.update_metadata.call_args[0][1]
        macro = updates["macro_indicators"]
        assert list(macro.keys()) == ["gdp_current_usd"]


# ── Test: No direct producer (wired without Kafka) ────────────────────────────


class TestMacroIndicatorWorkerNoProducer:
    def test_update_without_producer_does_not_crash(self) -> None:
        """Worker runs successfully without a direct_producer configured."""
        entity_repo, _ = _run_worker(old_hash=None, direct_producer=None)

        # Metadata still updated
        entity_repo.update_metadata.assert_awaited_once()


# ── Test: Prometheus counter ──────────────────────────────────────────────────


class TestMacroIndicatorWorkerPrometheus:
    def test_prometheus_counter_incremented_on_update(self) -> None:
        """s7_macro_indicator_updates_total incremented with country label when updated."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_macro_indicator_updates_total

        before = s7_macro_indicator_updates_total.labels(country="US")._value.get()
        _run_worker(old_hash=None)  # hash=None → update triggered
        after = s7_macro_indicator_updates_total.labels(country="US")._value.get()

        assert after - before == 1.0

    def test_prometheus_counter_not_incremented_on_no_change(self) -> None:
        """Counter not incremented when hash matches (no update)."""
        from knowledge_graph.infrastructure.metrics.prometheus import s7_macro_indicator_updates_total
        from knowledge_graph.infrastructure.workers.macro_indicator_worker import _sha256_hex

        macro_data = {
            "gdp_current_usd": {"value": 25e12, "year": "2023"},
            "gdp_growth_annual": {"value": 2.5, "year": "2023"},
            "inflation_consumer_prices_annual": {"value": 3.4, "year": "2023"},
            "real_interest_rate": {"value": 1.5, "year": "2023"},
            "unemployment_total_pct": {"value": 3.7, "year": "2023"},
            "current_account_balance_bop_usd": {"value": -1e12, "year": "2023"},
        }
        existing_hash = _sha256_hex(json.dumps(macro_data, sort_keys=True))

        before = s7_macro_indicator_updates_total.labels(country="US")._value.get()
        _run_worker(old_hash=existing_hash)
        after = s7_macro_indicator_updates_total.labels(country="US")._value.get()

        assert after == before


# ── Test: _sha256_hex helper ──────────────────────────────────────────────────


class TestSha256HexHelper:
    def test_returns_hex_string(self) -> None:
        from knowledge_graph.infrastructure.workers.macro_indicator_worker import _sha256_hex

        result = _sha256_hex("test")
        assert isinstance(result, str)
        assert len(result) == 64  # SHA-256 = 32 bytes = 64 hex chars
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self) -> None:
        from knowledge_graph.infrastructure.workers.macro_indicator_worker import _sha256_hex

        h1 = _sha256_hex('{"a": 1, "b": 2}')
        h2 = _sha256_hex('{"a": 1, "b": 2}')
        assert h1 == h2

    def test_different_inputs_different_hashes(self) -> None:
        from knowledge_graph.infrastructure.workers.macro_indicator_worker import _sha256_hex

        assert _sha256_hex('{"a": 1}') != _sha256_hex('{"a": 2}')
