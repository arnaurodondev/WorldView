"""Unit tests for the Polymarket Gamma ``/events`` client + adapter (PLAN-0056 B1)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket_gamma_events.adapter import (
    PolymarketEventsAdapter,
    _build_bronze_key,
)
from content_ingestion.infrastructure.adapters.polymarket_gamma_events.client import (
    GammaEventsPage,
    PolymarketEventsClient,
)

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)
_UTC_NOW_PATH = "content_ingestion.infrastructure.adapters.polymarket_gamma_events.adapter.common.time.utc_now"


def _client_settings(base_url: str = "https://gamma-api.polymarket.com/events") -> object:
    cfg = MagicMock()
    cfg.base_url = base_url
    return cfg


def _adapter_settings(page_size: int = 500, max_pages: int = 20) -> object:
    cfg = MagicMock()
    cfg.page_size = page_size
    cfg.max_pages_per_cycle = max_pages
    return cfg


def _response(body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def _source() -> Source:
    return Source(name="pm-events", source_type=SourceType.POLYMARKET_GAMMA_EVENTS, enabled=True, config={})


def _event(event_id: str = "evt_1") -> dict:
    return {
        "id": event_id,
        "title": "2028 US Presidential Election",
        "category": "Politics",
        "startDate": "2027-01-01T00:00:00Z",
        "endDate": "2028-11-07T00:00:00Z",
        "markets": [{"conditionId": "m1"}, {"conditionId": "m2"}, {"conditionId": "m3"}],
    }


def _make_adapter(client: object, storage: object = None, settings: object = None) -> PolymarketEventsAdapter:
    if storage is None:
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
    return PolymarketEventsAdapter(
        client=client,  # type: ignore[arg-type]
        fetch_log_exists_fn=AsyncMock(return_value=False),  # type: ignore[arg-type]
        settings=settings or _adapter_settings(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )


class TestPolymarketEventsClient:
    async def test_parses_events_page(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response({"events": [_event()], "next_cursor": "c1"}))
        client = PolymarketEventsClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        page = await client.fetch_events_page(limit=10)

        assert page.next_cursor == "c1"
        assert page.events[0]["id"] == "evt_1"

    async def test_next_cursor_absent(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response({"events": []}))
        client = PolymarketEventsClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        page = await client.fetch_events_page()

        assert isinstance(page, GammaEventsPage)
        assert page.next_cursor is None

    async def test_http_429_raises_adapter_error(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response({}, status_code=429))
        client = PolymarketEventsClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        with pytest.raises(AdapterError, match="429") as exc:
            await client.fetch_events_page()
        assert exc.value.status_code == 429


class TestPolymarketEventsAdapter:
    async def test_happy_path_parses_event(self) -> None:
        client = MagicMock()
        client.fetch_events_page = AsyncMock(return_value=GammaEventsPage(events=[_event("evt_ok")], next_cursor=None))
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source())

        assert len(results) == 1
        r = results[0]
        assert r.event_id == "evt_ok"
        assert r.title == "2028 US Presidential Election"
        assert r.category == "Politics"
        assert r.market_count == 3
        assert r.source_type == SourceType.POLYMARKET_GAMMA_EVENTS
        assert r.minio_bronze_key == _build_bronze_key("evt_ok", _FETCHED_AT)

    async def test_pagination_stops_at_max_pages(self) -> None:
        client = MagicMock()
        client.fetch_events_page = AsyncMock(
            return_value=GammaEventsPage(events=[_event("evt_pg")], next_cursor="more")
        )
        adapter = _make_adapter(client, settings=_adapter_settings(page_size=1, max_pages=3))

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source())

        assert client.fetch_events_page.await_count == 3
        assert len(results) == 3

    async def test_dedup_skips_existing(self) -> None:
        client = MagicMock()
        client.fetch_events_page = AsyncMock(return_value=GammaEventsPage(events=[_event("evt_dup")], next_cursor=None))
        adapter = PolymarketEventsAdapter(
            client=client,  # type: ignore[arg-type]
            fetch_log_exists_fn=AsyncMock(return_value=True),  # type: ignore[arg-type]
            settings=_adapter_settings(),  # type: ignore[arg-type]
            storage=AsyncMock(),  # type: ignore[arg-type]
        )

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source())

        assert results == []

    async def test_minio_failure_non_fatal(self) -> None:
        client = MagicMock()
        client.fetch_events_page = AsyncMock(return_value=GammaEventsPage(events=[_event("evt_m")], next_cursor=None))
        storage = AsyncMock()
        storage.put_bytes = AsyncMock(side_effect=RuntimeError("minio down"))
        adapter = _make_adapter(client, storage=storage)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source())

        assert len(results) == 1
        assert results[0].minio_bronze_key is None
