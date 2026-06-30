"""Tests for the ``get_filings`` tool handler (feat/chat-sec-filings-tool).

The chat catalogue previously had NO way to surface a company's SEC filings
with a clickable link to the primary source: fundamentals come from EODHD
aggregates (``url=None``) and ``search_documents`` advertised a ``sec_filing``
source taxonomy that never matched the stored ``sec_edgar`` literal, so
filing-only retrieval was unreachable.

``get_filings`` calls ``S6Port.search_chunks`` with the CORRECT stored
``source_types=['sec_edgar']`` filter, dedupes chunk hits down to one row per
filing, recovers the form label (10-K / 8-K / …) best-effort from the text, and
stamps ``citation_meta.url`` with the canonical EDGAR filing-index URL.

Test scenarios:
  1. ticker path — UUID resolved + source_types=['sec_edgar'] + EDGAR url citation.
  2. entity_id path — UUID provided directly (no ticker resolution).
  3. dedup — multiple chunks of the same filing collapse to one item.
  4. newest-first ordering by filed date.
  5. form_type filter — exact-form filings preferred; graceful fallback otherwise.
  6. missing S6 port → [] (R9 safe degradation).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_AAPL_ID = UUID("018f0000-0000-7000-8000-000000aaaa01")
_FAKE_USER_ID = UUID("018f0000-0000-7000-8000-0000000000d1")
_FAKE_TENANT_ID = UUID("018f0000-0000-7000-8000-0000000000d2")

_EDGAR_URL_10K = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/0000320193-26-000001-index.htm"
_EDGAR_URL_8K = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000002/0000320193-26-000002-index.htm"


def _make_handler(s6: AsyncMock, entity_context: Any = None) -> Any:
    from rag_chat.application.pipeline.handlers.news import NewsHandler

    return NewsHandler(
        s6=s6,
        brief_archive=None,
        entity_context=entity_context,
        user_id=_FAKE_USER_ID,
        tenant_id=_FAKE_TENANT_ID,
        timeout=5.0,
    )


def _chunk(
    *,
    doc_id: str,
    chunk_id: str,
    text: str,
    url: str,
    days_ago: int = 1,
    title: str | None = None,
    score: float = 0.8,
) -> Any:
    """Build an EnrichedChunkResult as returned by S6 chunk search."""
    from rag_chat.application.ports.upstream_clients import EnrichedChunkResult

    published = datetime(2026, 1, 31, tzinfo=UTC).replace(day=max(1, 31 - days_ago))
    return EnrichedChunkResult(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        score=score,
        source_type="sec_edgar",
        title=title,
        url=url,
        published_at=published,
        source_name="sec_edgar",
    )


def _make_s6(chunks: list[Any], *, ticker_map: dict[str, UUID | None] | None = None) -> AsyncMock:
    s6 = AsyncMock()

    async def _resolve(ticker: str) -> UUID | None:
        if ticker_map is None:
            return None
        return ticker_map.get(ticker.upper())

    s6.resolve_entity_by_ticker.side_effect = _resolve
    s6.search_chunks.return_value = chunks
    return s6


class TestGetFilingsHandler:
    @pytest.mark.asyncio
    async def test_ticker_resolves_and_filters_sec_edgar_with_edgar_citation(self) -> None:
        """ticker → entity_id; source_types pinned to ['sec_edgar']; EDGAR url on citation."""
        chunks = [
            _chunk(
                doc_id="018f0000-0000-7000-8000-00000000d001",
                chunk_id="c1",
                text="Apple Inc. ANNUAL REPORT pursuant to Section 13. Form 10-K for fiscal year.",
                url=_EDGAR_URL_10K,
            ),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        # Resolved + chunk search received the right filters.
        assert s6.resolve_entity_by_ticker.await_count == 1
        req = s6.search_chunks.call_args.args[0]
        assert req.source_types == ["sec_edgar"]
        assert req.entity_ids == [_AAPL_ID]

        # One filing returned, citation points at the canonical EDGAR index URL.
        assert len(items) == 1
        item = items[0]
        assert item.citation_meta.url == _EDGAR_URL_10K
        assert item.citation_meta.source_name == "sec_edgar"
        # Form label recovered from the body text.
        assert "10-K" in (item.citation_meta.title or "")
        # Trust weight reflects primary-source authority.
        assert item.trust_weight == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_entity_id_path_skips_ticker_resolution(self) -> None:
        chunks = [
            _chunk(
                doc_id="018f0000-0000-7000-8000-00000000d010",
                chunk_id="c1",
                text="Form 8-K current report.",
                url=_EDGAR_URL_8K,
            ),
        ]
        s6 = _make_s6(chunks)
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(entity_id=str(_AAPL_ID))

        s6.resolve_entity_by_ticker.assert_not_awaited()
        req = s6.search_chunks.call_args.args[0]
        assert req.entity_ids == [_AAPL_ID]
        assert len(items) == 1
        assert items[0].citation_meta.url == _EDGAR_URL_8K

    @pytest.mark.asyncio
    async def test_dedupes_multiple_chunks_of_same_filing(self) -> None:
        """Chunk search returns many chunks per filing → one result per doc_id."""
        chunks = [
            _chunk(doc_id="doc-1", chunk_id="c1", text="Form 10-K part 1", url=_EDGAR_URL_10K),
            _chunk(doc_id="doc-1", chunk_id="c2", text="Form 10-K part 2", url=_EDGAR_URL_10K),
            _chunk(doc_id="doc-1", chunk_id="c3", text="Form 10-K part 3", url=_EDGAR_URL_10K),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_results_sorted_newest_first(self) -> None:
        chunks = [
            _chunk(doc_id="old", chunk_id="c1", text="Form 8-K", url=_EDGAR_URL_8K, days_ago=20),
            _chunk(doc_id="new", chunk_id="c2", text="Form 10-K", url=_EDGAR_URL_10K, days_ago=1),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        assert [i.item_id for i in items] == ["tool:filing:new", "tool:filing:old"]

    @pytest.mark.asyncio
    async def test_form_type_filter_prefers_matching_form(self) -> None:
        chunks = [
            _chunk(doc_id="k", chunk_id="c1", text="ANNUAL REPORT Form 10-K", url=_EDGAR_URL_10K, days_ago=5),
            _chunk(doc_id="kk", chunk_id="c2", text="CURRENT REPORT Form 8-K", url=_EDGAR_URL_8K, days_ago=1),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL", form_type="10-K")

        # Only the 10-K is returned when a matching filing exists.
        assert len(items) == 1
        assert "10-K" in (items[0].citation_meta.title or "")
        # The query was biased toward the requested form.
        req = s6.search_chunks.call_args.args[0]
        assert req.query_text == "10-K"

    @pytest.mark.asyncio
    async def test_form_type_filter_falls_back_when_no_match(self) -> None:
        """No filing matches the requested form → still return filings (not empty)."""
        chunks = [
            _chunk(doc_id="kk", chunk_id="c1", text="CURRENT REPORT Form 8-K", url=_EDGAR_URL_8K),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL", form_type="10-K")

        assert len(items) == 1
        assert items[0].citation_meta.url == _EDGAR_URL_8K

    @pytest.mark.asyncio
    async def test_missing_s6_returns_empty(self) -> None:
        from rag_chat.application.pipeline.handlers.news import NewsHandler

        handler = NewsHandler(s6=None, brief_archive=None, entity_context=None)
        items = await handler._handle_get_filings(ticker="AAPL")
        assert items == []

    @pytest.mark.asyncio
    async def test_unresolved_ticker_with_no_results_returns_empty(self) -> None:
        s6 = _make_s6([], ticker_map={})  # ticker unresolvable, no chunks
        handler = _make_handler(s6)
        items = await handler._handle_get_filings(ticker="ZZZZZ")
        assert items == []

    @pytest.mark.asyncio
    async def test_dispatch_via_execute_normalises_date_aliases(self) -> None:
        """The public execute() entrypoint maps from_date/to_date aliases."""
        chunks = [_chunk(doc_id="d", chunk_id="c1", text="Form 10-K", url=_EDGAR_URL_10K)]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)

        items = await handler.execute(
            "get_filings",
            {"ticker": "AAPL", "from_date": "2026-01-01", "to_date": "2026-12-31"},
        )

        assert len(items) == 1
        req = s6.search_chunks.call_args.args[0]
        assert req.date_from is not None
        assert req.date_to is not None
