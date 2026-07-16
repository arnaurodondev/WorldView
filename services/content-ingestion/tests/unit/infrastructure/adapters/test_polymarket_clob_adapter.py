"""Unit tests for the Polymarket CLOB ``/prices-history`` client + adapter (PLAN-0056 B1)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.infrastructure.adapters.polymarket_clob.adapter import PolymarketClobHistoryAdapter
from content_ingestion.infrastructure.adapters.polymarket_clob.client import PolymarketClobHistoryClient

pytestmark = pytest.mark.unit

_FETCHED_AT = datetime(2026, 4, 9, 14, 0, 0, tzinfo=UTC)
_UTC_NOW_PATH = "content_ingestion.infrastructure.adapters.polymarket_clob.adapter.common.time.utc_now"


def _client_settings(base_url: str = "https://clob.polymarket.com/prices-history") -> object:
    cfg = MagicMock()
    cfg.base_url = base_url
    return cfg


def _adapter_settings(interval: str = "1h", fallback: str = "1d") -> object:
    cfg = MagicMock()
    cfg.interval = interval
    cfg.fallback_interval = fallback
    cfg.fidelity = 60
    cfg.backfill_days = 14
    cfg.ongoing_window_hours = 6
    return cfg


def _response(body: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    return resp


def _source(token_ids: list[str] | None = None) -> Source:
    # Legacy flat ``token_ids`` config (pre-B4) — still honoured via fallback.
    return Source(
        name="pm-clob",
        source_type=SourceType.POLYMARKET_CLOB,
        enabled=True,
        config={"token_ids": token_ids if token_ids is not None else ["tok_1"]},
    )


def _source_markets(markets: list[dict]) -> Source:
    # PLAN-0056 Wave B4: unified ``markets`` work-list config
    # ({condition_id, token_ids}) that carries the parent conditionId.
    return Source(
        name="pm-clob",
        source_type=SourceType.POLYMARKET_CLOB,
        enabled=True,
        config={"markets": markets},
    )


def _history(points: int = 3) -> dict:
    base = 1_700_000_000
    return {"history": [{"t": base + i * 3600, "p": 0.5 + i * 0.01} for i in range(points)]}


def _make_adapter(client: object, storage: object = None, settings: object = None) -> PolymarketClobHistoryAdapter:
    if storage is None:
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
    return PolymarketClobHistoryAdapter(
        client=client,  # type: ignore[arg-type]
        fetch_log_exists_fn=AsyncMock(return_value=False),  # type: ignore[arg-type]
        settings=settings or _adapter_settings(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
    )


class TestPolymarketClobHistoryClient:
    async def test_parses_history(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response(_history(2)))
        client = PolymarketClobHistoryClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        raw = await client.fetch_price_history(token_id="tok_1", interval="1h", start_ts=100)

        assert len(raw["history"]) == 2

    async def test_http_400_raises_with_status(self) -> None:
        http = AsyncMock()
        http.get = AsyncMock(return_value=_response({}, status_code=400))
        client = PolymarketClobHistoryClient(http_client=http, settings=_client_settings())  # type: ignore[arg-type]

        with pytest.raises(AdapterError) as exc:
            await client.fetch_price_history(token_id="tok_1", interval="1h")
        assert exc.value.status_code == 400


class TestPolymarketClobHistoryAdapter:
    async def test_happy_path_parses_points(self) -> None:
        client = MagicMock()
        client.fetch_price_history = AsyncMock(return_value=_history(3))
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["tok_a"]))

        assert len(results) == 1
        assert results[0].token_id == "tok_a"  # noqa: S105 — token id, not a secret
        assert results[0].interval == "1h"
        assert len(results[0].points) == 3
        # Legacy flat config → no parent conditionId known.
        assert results[0].market_id is None

    async def test_markets_worklist_stamps_parent_condition_id(self) -> None:
        """PLAN-0056 Wave B4: the ``markets`` work-list stamps market_id=conditionId."""
        client = MagicMock()
        client.fetch_price_history = AsyncMock(return_value=_history(3))
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source_markets([{"condition_id": "cond_xyz", "token_ids": ["tok_a"]}]))

        assert len(results) == 1
        assert results[0].token_id == "tok_a"  # noqa: S105 — token id, not a secret
        assert results[0].market_id == "cond_xyz"

    async def test_two_token_ids_share_parent_condition_id(self) -> None:
        """A market with 2 outcome tokens → 2 results, all under the same parent."""
        client = MagicMock()
        client.fetch_price_history = AsyncMock(return_value=_history(2))
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(
                _source_markets([{"condition_id": "cond_multi", "token_ids": ["tok_yes", "tok_no"]}])
            )

        assert {r.token_id for r in results} == {"tok_yes", "tok_no"}
        assert {r.market_id for r in results} == {"cond_multi"}
        assert client.fetch_price_history.await_count == 2

    async def test_no_token_ids_returns_empty(self) -> None:
        client = MagicMock()
        client.fetch_price_history = AsyncMock(return_value=_history(3))
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(token_ids=[]))

        assert results == []
        client.fetch_price_history.assert_not_awaited()

    async def test_fallback_to_1d_on_400(self) -> None:
        """1h → HTTP 400 → retry at 1d (resolved-market fallback)."""
        client = MagicMock()
        client.fetch_price_history = AsyncMock(
            side_effect=[AdapterError("CLOB HTTP 400", status_code=400), _history(2)]
        )
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["tok_resolved"]))

        assert client.fetch_price_history.await_count == 2
        # Second call used the fallback interval.
        assert client.fetch_price_history.await_args_list[1].kwargs["interval"] == "1d"
        assert results[0].interval == "1d"

    async def test_fallback_to_1d_on_empty_series(self) -> None:
        """1h → empty series → retry at 1d."""
        client = MagicMock()
        client.fetch_price_history = AsyncMock(side_effect=[{"history": []}, _history(2)])
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["tok_empty"]))

        assert client.fetch_price_history.await_count == 2
        assert results[0].interval == "1d"
        assert len(results[0].points) == 2

    async def test_empty_after_fallback_skips_token(self) -> None:
        client = MagicMock()
        client.fetch_price_history = AsyncMock(side_effect=[{"history": []}, {"history": []}])
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["tok_dead"]))

        assert results == []

    async def test_non_400_error_reraises(self) -> None:
        client = MagicMock()
        client.fetch_price_history = AsyncMock(side_effect=AdapterError("CLOB HTTP 429", status_code=429))
        adapter = _make_adapter(client)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT), pytest.raises(AdapterError, match="429"):
            await adapter.fetch(_source(["tok_x"]))

    async def test_minio_failure_non_fatal(self) -> None:
        client = MagicMock()
        client.fetch_price_history = AsyncMock(return_value=_history(2))
        storage = AsyncMock()
        storage.put_bytes = AsyncMock(side_effect=RuntimeError("minio down"))
        adapter = _make_adapter(client, storage=storage)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["tok_m"]))

        assert len(results) == 1
        assert results[0].minio_bronze_key is None

    async def test_bronze_archive_disabled_skips_put(self) -> None:
        """Inode-exhaustion P0 (2026-07-16): when ``bronze_archive_enabled`` is
        False (the production default) NO bronze object is written — the CLOB
        firehose stops burning inodes — yet the fetch-results (the live Kafka
        path) are still returned with ``minio_bronze_key`` left None."""
        client = MagicMock()
        client.fetch_price_history = AsyncMock(return_value=_history(3))
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
        settings = _adapter_settings()
        settings.bronze_archive_enabled = False
        adapter = _make_adapter(client, storage=storage, settings=settings)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["tok_off"]))

        # Data still flows (results returned), but zero bronze objects written.
        assert len(results) == 1
        assert len(results[0].points) == 3
        assert results[0].minio_bronze_key is None
        storage.put_bytes.assert_not_awaited()

    async def test_bronze_archive_enabled_writes_put(self) -> None:
        """With the archive explicitly enabled the bronze object IS written and
        the key is stamped onto the result (opt-in replay/audit path)."""
        client = MagicMock()
        client.fetch_price_history = AsyncMock(return_value=_history(2))
        storage = AsyncMock()
        storage.put_bytes = AsyncMock()
        settings = _adapter_settings()
        settings.bronze_archive_enabled = True
        adapter = _make_adapter(client, storage=storage, settings=settings)

        with patch(_UTC_NOW_PATH, return_value=_FETCHED_AT):
            results = await adapter.fetch(_source(["tok_on"]))

        assert len(results) == 1
        assert results[0].minio_bronze_key is not None
        storage.put_bytes.assert_awaited_once()
