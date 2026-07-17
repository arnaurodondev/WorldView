"""Unit tests for PolymarketAdapter."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.config import PolymarketProviderSettings
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.infrastructure.adapters.polymarket.adapter import PolymarketAdapter, _build_bronze_key
from content_ingestion.infrastructure.adapters.polymarket.client import GammaMarketsPage, PolymarketClient

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)


def _make_settings(page_size: int = 500, max_pages: int = 20) -> object:
    cfg = MagicMock()
    cfg.page_size = page_size
    cfg.max_pages_per_cycle = max_pages
    return cfg


def _make_source() -> Source:
    return Source(name="polymarket-test", source_type=SourceType.POLYMARKET, enabled=True, config={})


def _market(condition_id: str = "cond_abc") -> dict:
    return {
        "conditionId": condition_id,
        "question": "Will X happen?",
        "tokens": [
            {"outcome": "Yes", "token_id": "tok_yes", "price": 0.6},
            {"outcome": "No", "token_id": "tok_no", "price": 0.4},
        ],
    }


def _make_adapter(
    client: object = None,
    fetch_log_exists_fn: object = None,
    storage: object = None,
    settings: object = None,
) -> PolymarketAdapter:
    if client is None:
        client = MagicMock()
        client.fetch_markets_page = AsyncMock(return_value=GammaMarketsPage(markets=[], next_cursor=None))
    if fetch_log_exists_fn is None:
        fetch_log_exists_fn = AsyncMock(return_value=False)
    if storage is None:
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
    if settings is None:
        settings = _make_settings()
    return PolymarketAdapter(
        client=client,  # type: ignore[arg-type]
        fetch_log_exists_fn=fetch_log_exists_fn,  # type: ignore[arg-type]
        settings=settings,  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )


class TestPolymarketAdapter:
    async def test_adapter_dedup_skips_existing(self) -> None:
        """fetch_log_exists_fn returns True → result excluded from output."""
        client = MagicMock()
        client.fetch_markets_page = AsyncMock(
            return_value=GammaMarketsPage(markets=[_market("cond_dup")], next_cursor=None)
        )
        fetch_log_exists_fn = AsyncMock(return_value=True)

        adapter = _make_adapter(client=client, fetch_log_exists_fn=fetch_log_exists_fn)
        _utc_now_path = "content_ingestion.infrastructure.adapters.polymarket.adapter.common.time.utc_now"
        with patch(_utc_now_path, return_value=_FETCHED_AT):
            results = await adapter.fetch(_make_source())

        assert results == []
        fetch_log_exists_fn.assert_awaited_once()

    async def test_adapter_pagination_stops_at_max_pages(self) -> None:
        """Stops after max_pages_per_cycle even if next_cursor is present."""
        client = MagicMock()
        # Always returns 1 market + a cursor → would loop forever without cap
        client.fetch_markets_page = AsyncMock(
            return_value=GammaMarketsPage(markets=[_market("cond_pg")], next_cursor="keep-going")
        )
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
        settings = _make_settings(page_size=1, max_pages=3)

        adapter = _make_adapter(client=client, storage=storage, settings=settings)
        _utc_now_path = "content_ingestion.infrastructure.adapters.polymarket.adapter.common.time.utc_now"
        with patch(_utc_now_path, return_value=_FETCHED_AT):
            results = await adapter.fetch(_make_source())

        assert client.fetch_markets_page.await_count == 3
        assert len(results) == 3

    async def test_adapter_walks_offsets_across_pages_until_empty_page(self) -> None:
        """End-to-end: adapter + real client page through increasing offsets and
        stop only on an EMPTY page. Proves the offset-pagination fix is robust to
        the Gamma server-side page cap: a page shorter than ``limit`` is the norm
        (the API caps the page size below the requested limit), so the walk must
        advance past it by the actual returned count and terminate only when a page
        comes back empty. page 1 (offset 0, full=2) → page 2 (offset 2, short=1,
        advances by 1) → page 3 (offset 3, empty) → stop. Regression both for the
        page-1-only bug AND for stopping prematurely on a capped short page.
        """

        def _resp(body: list) -> MagicMock:
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = body
            return r

        full_page = [_market("cond_a"), _market("cond_b")]  # full page → advance
        short_page = [_market("cond_c")]  # server-capped short page → still advance
        empty_page: list = []  # empty page → terminate
        http = AsyncMock()
        http.get = AsyncMock(side_effect=[_resp(full_page), _resp(short_page), _resp(empty_page)])
        client = PolymarketClient(
            http_client=http,  # type: ignore[arg-type]
            settings=PolymarketProviderSettings(page_size=2, order=""),
        )
        settings = PolymarketProviderSettings(page_size=2, max_pages_per_cycle=20, order="")

        adapter = _make_adapter(client=client, settings=settings)
        _utc_now_path = "content_ingestion.infrastructure.adapters.polymarket.adapter.common.time.utc_now"
        with patch(_utc_now_path, return_value=_FETCHED_AT):
            results = await adapter.fetch(_make_source())

        # Three HTTP calls with offsets 0, 2 (advanced by the 2 full rows), 3
        # (advanced by the 1 short-page row); three markets total.
        assert http.get.await_count == 3
        offsets = [call.kwargs["params"]["offset"] for call in http.get.await_args_list]
        assert offsets == [0, 2, 3]
        assert len(results) == 3

    async def test_adapter_parse_failure_continues(self) -> None:
        """One bad market dict → warning logged, remaining markets processed."""
        bad_market = {"conditionId": "bad", "question": "Q?", "tokens": []}  # 0 outcomes → ValueError
        good_market = _market("cond_good")
        client = MagicMock()
        client.fetch_markets_page = AsyncMock(
            return_value=GammaMarketsPage(markets=[bad_market, good_market], next_cursor=None)
        )
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()

        adapter = _make_adapter(client=client, storage=storage)
        _utc_now_path = "content_ingestion.infrastructure.adapters.polymarket.adapter.common.time.utc_now"
        with patch(_utc_now_path, return_value=_FETCHED_AT):
            results = await adapter.fetch(_make_source())

        # bad_market has 0 outcomes → pre-check skips it; good_market succeeds
        assert len(results) == 1
        assert results[0].market_id == "cond_good"

    async def test_adapter_skips_single_outcome_market(self) -> None:
        """Markets with exactly 1 token are also skipped (domain invariant requires ≥2)."""
        single_token_market = {
            "conditionId": "cond_single",
            "question": "Will Harvey be sentenced?",
            "tokens": [{"outcome": "Yes", "token_id": "tok_yes", "price": 1.0}],
        }
        good_market = _market("cond_two")
        client = MagicMock()
        client.fetch_markets_page = AsyncMock(
            return_value=GammaMarketsPage(markets=[single_token_market, good_market], next_cursor=None)
        )
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()

        adapter = _make_adapter(client=client, storage=storage)
        _utc_now_path = "content_ingestion.infrastructure.adapters.polymarket.adapter.common.time.utc_now"
        with patch(_utc_now_path, return_value=_FETCHED_AT):
            results = await adapter.fetch(_make_source())

        # 1-token market → pre-check skips before parse; 2-token market passes
        assert len(results) == 1
        assert results[0].market_id == "cond_two"

    async def test_adapter_stores_raw_bytes_to_minio(self) -> None:
        """MinIO put_bytes called once per successfully parsed result."""
        client = MagicMock()
        client.fetch_markets_page = AsyncMock(
            return_value=GammaMarketsPage(markets=[_market("cond_store")], next_cursor=None)
        )
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()

        adapter = _make_adapter(client=client, storage=storage)
        _utc_now_path = "content_ingestion.infrastructure.adapters.polymarket.adapter.common.time.utc_now"
        with patch(_utc_now_path, return_value=_FETCHED_AT):
            results = await adapter.fetch(_make_source())

        assert len(results) == 1
        storage.put_bytes.assert_awaited_once()
        expected_key = _build_bronze_key("cond_store", _FETCHED_AT)
        assert results[0].minio_bronze_key == expected_key
