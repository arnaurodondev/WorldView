"""Unit tests for the EODHD adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from content_ingestion.domain.entities import Source, SourceType
from content_ingestion.domain.exceptions import AdapterError
from content_ingestion.domain.value_objects import TokenBucket
from content_ingestion.infrastructure.adapters.base import RetryConfig
from content_ingestion.infrastructure.adapters.eodhd import adapter as eodhd_adapter_mod
from content_ingestion.infrastructure.adapters.eodhd.adapter import EODHDAdapter, _parse_published_at
from content_ingestion.infrastructure.adapters.eodhd.client import EODHDClient

import common.time

pytestmark = pytest.mark.unit


def _make_source(**kwargs: Any) -> Source:
    defaults: dict[str, Any] = {
        "name": "test-eodhd",
        "source_type": SourceType.EODHD,
        "enabled": True,
        "config": {"ticker": "AAPL.US", "from_date": "2026-01-01", "to_date": "2026-03-01"},
    }
    defaults.update(kwargs)
    return Source(**defaults)


def _make_bucket() -> TokenBucket:
    return TokenBucket(capacity=100, tokens=100.0, refill_rate=10.0, last_refill=common.time.utc_now())


def _article(link: str, date: str = "2026-03-15T10:00:00") -> dict[str, Any]:
    return {"link": link, "title": f"Article {link}", "date": date}


class TestParsePublishedAt:
    def test_valid_iso_date(self) -> None:
        result = _parse_published_at({"date": "2026-03-15T10:00:00"})
        assert result is not None
        assert result.year == 2026
        assert result.tzinfo is not None

    def test_missing_date(self) -> None:
        assert _parse_published_at({}) is None

    def test_invalid_date(self) -> None:
        assert _parse_published_at({"date": "not-a-date"}) is None


class TestEODHDAdapterFetch:
    async def test_fetches_and_returns_results(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://example.com/a"),
            _article("https://example.com/b"),
        ]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        source = _make_source()
        results = await adapter.fetch(source)
        assert len(results) == 2
        assert results[0].url == "https://example.com/a"
        assert results[1].url == "https://example.com/b"

    async def test_dedup_skips_existing(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://example.com/dup"),
        ]
        exists_fn = AsyncMock(return_value=True)
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            exists_fn=exists_fn,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0
        exists_fn.assert_called_once()

    async def test_published_at_extracted(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [
            _article("https://example.com/dated", date="2026-02-20T14:30:00"),
        ]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1
        assert results[0].published_at is not None
        assert results[0].published_at.month == 2

    async def test_is_backfill_flag_propagated(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [_article("https://example.com/bf")]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source(), is_backfill=True)
        assert len(results) == 1
        assert results[0].is_backfill is True

    async def test_skips_articles_without_link(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [{"title": "No link"}]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 0

    async def test_retry_on_transient_failure(self) -> None:
        mock_client = AsyncMock(spec=EODHDClient)
        call_count = 0

        async def flaky_fetch(**_kwargs: Any) -> list[dict[str, Any]]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "transient"
                raise AdapterError(msg)
            return [_article("https://example.com/retry-ok")]

        mock_client.fetch_all_pages.side_effect = flaky_fetch
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            retry_config=RetryConfig(max_retries=2, backoff_factors=(0.0, 0.0)),
        )
        results = await adapter.fetch(_make_source())
        assert len(results) == 1


def _general_source(**kwargs: Any) -> Source:
    """A filter-less GENERAL EODHD source (no ``ticker`` in config)."""
    defaults: dict[str, Any] = {
        "name": "eodhd-news",
        "source_type": SourceType.EODHD,
        "enabled": True,
        "config": {},
    }
    defaults.update(kwargs)
    return Source(**defaults)


def _firehose_adapter(
    mock_client: AsyncMock,
    *,
    exists_fn: Any,
    shadow_mode: bool = False,
    page_size: int = 100,
    max_pages: int = 3,
) -> EODHDAdapter:
    return EODHDAdapter(
        client=mock_client,
        rate_limiter=_make_bucket(),
        exists_fn=exists_fn,
        retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
        firehose_enabled=True,
        shadow_mode=shadow_mode,
        page_size=page_size,
        max_pages=max_pages,
    )


class TestEODHDFirehoseEarlyExit:
    """SHADOW STAGE: the general early-exit sweep pins high-frequency polls to 1 request."""

    async def test_steady_state_single_request_when_newest_already_seen(self) -> None:
        # Steady state: the newest article on the feed is one we stored last poll.
        # exists_fn returns True on the first article → sweep exits after ONE
        # request with zero new results (the 5-credit/poll case).
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_news.return_value = [_article("https://ex.com/seen"), _article("https://ex.com/older")]
        exists_fn = AsyncMock(return_value=True)

        adapter = _firehose_adapter(mock_client, exists_fn=exists_fn, page_size=100)
        results = await adapter.fetch(_general_source())

        assert results == []
        assert mock_client.fetch_news.await_count == 1  # exactly one page request
        mock_client.fetch_all_pages.assert_not_called()  # firehose path, not legacy bulk

    async def test_collects_new_then_stops_on_first_seen_hash_midpage(self) -> None:
        # A page with two new articles, then an already-stored one, then more:
        # collect the two new ones, stop the whole sweep at the stored boundary
        # (the trailing article is never emitted), all in ONE request.
        new1 = _article("https://ex.com/new1")
        new2 = _article("https://ex.com/new2")
        seen = _article("https://ex.com/seen")
        trailing = _article("https://ex.com/trailing")
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_news.return_value = [new1, new2, seen, trailing]

        async def _exists(h: str) -> bool:
            from content_ingestion.infrastructure.adapters.base import url_hash

            return h == url_hash("https://ex.com/seen")

        adapter = _firehose_adapter(mock_client, exists_fn=AsyncMock(side_effect=_exists), page_size=100)
        results = await adapter.fetch(_general_source())

        assert [r.url for r in results] == ["https://ex.com/new1", "https://ex.com/new2"]
        assert mock_client.fetch_news.await_count == 1

    async def test_cold_start_paginates_until_partial_page(self) -> None:
        # Cold start: nothing is stored yet (exists_fn always False), so the sweep
        # paginates until a partial page signals the feed is drained.
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_news.side_effect = [
            [_article("https://ex.com/a"), _article("https://ex.com/b")],  # full page
            [_article("https://ex.com/c"), _article("https://ex.com/d")],  # full page
            [_article("https://ex.com/e")],  # partial → drained
        ]
        adapter = _firehose_adapter(
            mock_client,
            exists_fn=AsyncMock(return_value=False),
            page_size=2,
            max_pages=10,
        )
        results = await adapter.fetch(_general_source())

        assert len(results) == 5
        assert mock_client.fetch_news.await_count == 3

    async def test_page_cap_backstop_stops_runaway_pagination(self) -> None:
        # If EODHD keeps returning full pages of NEW articles, the max_pages
        # backstop halts the sweep instead of spinning forever.
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_news.side_effect = [
            [_article("https://ex.com/a"), _article("https://ex.com/b")],  # full page
            [_article("https://ex.com/c"), _article("https://ex.com/d")],  # full page → cap hit
            [_article("https://ex.com/e"), _article("https://ex.com/f")],  # never requested
        ]
        adapter = _firehose_adapter(
            mock_client,
            exists_fn=AsyncMock(return_value=False),
            page_size=2,
            max_pages=2,
        )
        results = await adapter.fetch(_general_source())

        assert mock_client.fetch_news.await_count == 2  # capped
        assert len(results) == 4

    async def test_shadow_mode_records_coverage_signal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # In shadow mode the sweep emits the coverage signal: new-article count +
        # symbol-tag count (the general feed's superset advantage).
        captured: dict[str, Any] = {}

        def _fake_record(**kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(eodhd_adapter_mod, "record_general_firehose_sweep", _fake_record)

        tagged = {**_article("https://ex.com/tagged"), "symbols": ["AAPL.US", "MSFT.US"]}
        seen = _article("https://ex.com/seen")
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_news.return_value = [tagged, seen]

        async def _exists(h: str) -> bool:
            from content_ingestion.infrastructure.adapters.base import url_hash

            return h == url_hash("https://ex.com/seen")

        adapter = _firehose_adapter(
            mock_client,
            exists_fn=AsyncMock(side_effect=_exists),
            shadow_mode=True,
            page_size=100,
        )
        results = await adapter.fetch(_general_source())

        assert len(results) == 1
        assert captured["outcome"] == "early_exit"
        assert captured["requests"] == 1
        assert captured["new_articles"] == 1
        assert captured["symbol_tags"] == 2

    async def test_firehose_disabled_uses_legacy_bulk_pull(self) -> None:
        # With the flag OFF the general source keeps the legacy fetch_all_pages
        # behaviour (backward compatible — no early-exit).
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [_article("https://ex.com/a")]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            exists_fn=AsyncMock(return_value=False),
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
            firehose_enabled=False,
        )
        results = await adapter.fetch(_general_source())

        assert len(results) == 1
        mock_client.fetch_all_pages.assert_awaited_once()
        mock_client.fetch_news.assert_not_called()

    async def test_firehose_requires_exists_fn_else_legacy(self) -> None:
        # No dedup oracle → no early-exit boundary → fall back to the legacy path.
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [_article("https://ex.com/a")]
        adapter = EODHDAdapter(
            client=mock_client,
            rate_limiter=_make_bucket(),
            exists_fn=None,
            retry_config=RetryConfig(max_retries=1, backoff_factors=(0.0,)),
            firehose_enabled=True,
        )
        results = await adapter.fetch(_general_source())

        assert len(results) == 1
        mock_client.fetch_all_pages.assert_awaited_once()
        mock_client.fetch_news.assert_not_called()

    async def test_ticker_scoped_source_never_uses_firehose(self) -> None:
        # A ``ticker``-scoped source is the per-symbol legacy path even with the
        # firehose flag on — the firehose is only the filter-less general feed.
        mock_client = AsyncMock(spec=EODHDClient)
        mock_client.fetch_all_pages.return_value = [_article("https://ex.com/a")]
        adapter = _firehose_adapter(mock_client, exists_fn=AsyncMock(return_value=False))
        results = await adapter.fetch(_make_source(config={"ticker": "AAPL.US"}))

        assert len(results) == 1
        mock_client.fetch_all_pages.assert_awaited_once()
        mock_client.fetch_news.assert_not_called()
