"""Unit tests for the Polymarket Data-API ``/trades`` client + adapter (PLAN-0056 B1)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket_data_trades.adapter import PolymarketTradesAdapter
from content_ingestion.infrastructure.adapters.polymarket_data_trades.client import PolymarketTradesClient, TradesPage

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)
_UTC_NOW_PATH = "content_ingestion.infrastructure.adapters.polymarket_data_trades.adapter.common.time.utc_now"


def _client_settings(base_url: str = "https://data-api.polymarket.com/trades") -> object:
    cfg = MagicMock()
    cfg.base_url = base_url
    return cfg


def _adapter_settings(page_size: int = 500, max_pages: int = 20) -> object:
    cfg = MagicMock()
    cfg.page_size = page_size
    cfg.max_pages_per_cycle = max_pages
    return cfg


def _response(body: object, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def _source(condition_ids: list[str] | None = None) -> Source:
    return Source(
        name="pm-trades",
        source_type=SourceType.POLYMARKET_DATA_TRADES,
        enabled=True,
        config={"condition_ids": condition_ids if condition_ids is not None else ["cond_1"]},
    )


def _trade(trade_id: str = "0xabc") -> dict:
    return {
        "transactionHash": trade_id,
        "asset": "tok_yes",
        "price": 0.62,
        "size": 125.5,
        "side": "BUY",
        "timestamp": 1_700_000_000,
    }


def _make_adapter(client: object, storage: object = None, settings: object = None) -> PolymarketTradesAdapter:
    if storage is None:
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
    return PolymarketTradesAdapter(
        client=client,  # type: ignore[arg-type]
        fetch_log_exists_fn=AsyncMock(return_value=False),  # type: ignore[arg-type]
        settings=settings or _adapter_settings(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )


class TestPolymarketTradesClient:
    async def test_parses_trades_page_list(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response([_trade("a"), _trade("b")]))
        client = PolymarketTradesClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        page = await client.fetch_trades_page(market="cond_1", limit=500)

        assert isinstance(page, TradesPage)
        assert len(page.trades) == 2
        assert page.has_more is False

    async def test_wrapped_data_and_has_more(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response({"data": [_trade("a"), _trade("b")]}))
        client = PolymarketTradesClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        page = await client.fetch_trades_page(market="cond_1", limit=2)

        assert len(page.trades) == 2
        assert page.has_more is True

    async def test_http_429_raises(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response([], status_code=429))
        client = PolymarketTradesClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        with pytest.raises(AdapterError, match="429") as exc:
            await client.fetch_trades_page(market="cond_1")
        assert exc.value.status_code == 429


class TestPolymarketTradesAdapter:
    async def test_happy_path_parses_trades(self) -> None:
        client = MagicMock()
        client.fetch_trades_page = AsyncMock(
            return_value=TradesPage(trades=[_trade("0xt1"), _trade("0xt2")], has_more=False)
        )
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["cond_a"]))

        assert len(results) == 2
        r = results[0]
        assert r.trade_id == "0xt1"
        assert r.token_id == "tok_yes"  # noqa: S105 — token id, not a secret
        assert r.price == 0.62
        assert r.size_usd == 125.5
        assert r.side == "BUY"
        assert r.source_type == SourceType.POLYMARKET_DATA_TRADES

    async def test_offset_pagination_stops_at_max_pages(self) -> None:
        client = MagicMock()
        # Always full page → has_more True → would loop forever without cap.
        client.fetch_trades_page = AsyncMock(return_value=TradesPage(trades=[_trade("0xp")], has_more=True))
        adapter = _make_adapter(client, settings=_adapter_settings(page_size=1, max_pages=3))

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["cond_pg"]))

        assert client.fetch_trades_page.await_count == 3
        # Same trade id → deduped by fetch_log within this call? No — fetch_log is a
        # stub returning False, so each of 3 pages yields the trade (dedup is DB-level).
        assert len(results) == 3

    async def test_dedup_skips_existing_trade(self) -> None:
        client = MagicMock()
        client.fetch_trades_page = AsyncMock(return_value=TradesPage(trades=[_trade("0xdup")], has_more=False))
        adapter = PolymarketTradesAdapter(
            client=client,  # type: ignore[arg-type]
            fetch_log_exists_fn=AsyncMock(return_value=True),  # type: ignore[arg-type]
            settings=_adapter_settings(),  # type: ignore[arg-type]
            storage=AsyncMock(),  # type: ignore[arg-type]
        )

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["cond_d"]))

        assert results == []

    async def test_minio_failure_non_fatal(self) -> None:
        client = MagicMock()
        client.fetch_trades_page = AsyncMock(return_value=TradesPage(trades=[_trade("0xm")], has_more=False))
        storage = AsyncMock()
        storage.put_bytes = AsyncMock(side_effect=RuntimeError("minio down"))
        adapter = _make_adapter(client, storage=storage)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["cond_m"]))

        assert len(results) == 1
        assert results[0].minio_bronze_key is None

    async def test_no_condition_ids_returns_empty(self) -> None:
        client = MagicMock()
        client.fetch_trades_page = AsyncMock()
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(condition_ids=[]))

        assert results == []
        client.fetch_trades_page.assert_not_awaited()
