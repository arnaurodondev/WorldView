"""Unit tests for the Polymarket Data-API open-interest client + adapter (PLAN-0056 B1)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket_data_oi.adapter import PolymarketOIAdapter
from content_ingestion.infrastructure.adapters.polymarket_data_oi.client import PolymarketOIClient

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)
_UTC_NOW_PATH = "content_ingestion.infrastructure.adapters.polymarket_data_oi.adapter.common.time.utc_now"


def _client_settings(base_url: str = "https://data-api.polymarket.com/oi") -> object:
    cfg = MagicMock()
    cfg.base_url = base_url
    return cfg


def _response(body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def _source(condition_ids: list[str] | None = None) -> Source:
    return Source(
        name="pm-oi",
        source_type=SourceType.POLYMARKET_DATA_OI,
        enabled=True,
        config={"condition_ids": condition_ids if condition_ids is not None else ["cond_1"]},
    )


def _oi_body() -> dict:
    return {"openInterest": 543210.75, "volume24hr": 98765.4}


def _make_adapter(client: object, storage: object = None) -> PolymarketOIAdapter:
    if storage is None:
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
    return PolymarketOIAdapter(
        client=client,  # type: ignore[arg-type]
        fetch_log_exists_fn=AsyncMock(return_value=False),  # type: ignore[arg-type]
        settings=MagicMock(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )


class TestPolymarketOIClient:
    async def test_parses_oi(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response(_oi_body()))
        client = PolymarketOIClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        raw = await client.fetch_open_interest(market="cond_1")

        assert raw["openInterest"] == 543210.75

    async def test_unwraps_data_envelope(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response({"data": _oi_body()}))
        client = PolymarketOIClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        raw = await client.fetch_open_interest(market="cond_1")

        assert raw["openInterest"] == 543210.75

    async def test_http_429_raises(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response({}, status_code=429))
        client = PolymarketOIClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        with pytest.raises(AdapterError, match="429") as exc:
            await client.fetch_open_interest(market="cond_1")
        assert exc.value.status_code == 429


class TestPolymarketOIAdapter:
    async def test_happy_path_parses_snapshot(self) -> None:
        client = MagicMock()
        client.fetch_open_interest = AsyncMock(return_value=_oi_body())
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["cond_ok"]))

        assert len(results) == 1
        r = results[0]
        assert r.market_id == "cond_ok"
        assert r.open_interest_usd == 543210.75
        assert r.volume_24h_usd == 98765.4
        assert r.snapshot_date == _FETCHED_AT
        assert r.source_type == SourceType.POLYMARKET_DATA_OI

    async def test_dedup_skips_existing(self) -> None:
        client = MagicMock()
        client.fetch_open_interest = AsyncMock(return_value=_oi_body())
        adapter = PolymarketOIAdapter(
            client=client,  # type: ignore[arg-type]
            fetch_log_exists_fn=AsyncMock(return_value=True),  # type: ignore[arg-type]
            settings=MagicMock(),  # type: ignore[arg-type]
            storage=AsyncMock(),  # type: ignore[arg-type]
        )

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["cond_d"]))

        assert results == []
        client.fetch_open_interest.assert_not_awaited()

    async def test_minio_failure_non_fatal(self) -> None:
        client = MagicMock()
        client.fetch_open_interest = AsyncMock(return_value=_oi_body())
        storage = AsyncMock()
        storage.put_bytes = AsyncMock(side_effect=RuntimeError("minio down"))
        adapter = _make_adapter(client, storage=storage)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["cond_m"]))

        assert len(results) == 1
        assert results[0].minio_bronze_key is None

    async def test_no_condition_ids_returns_empty(self) -> None:
        client = MagicMock()
        client.fetch_open_interest = AsyncMock()
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(condition_ids=[]))

        assert results == []
        client.fetch_open_interest.assert_not_awaited()
