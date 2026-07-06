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


class _FakeResolvedEntity:
    """Minimal stand-in for ResolvedEntity — only the field the helper reads."""

    def __init__(self, canonical_name: str) -> None:
        self.canonical_name = canonical_name


def _make_s6(
    chunks: list[Any],
    *,
    ticker_map: dict[str, UUID | None] | None = None,
    name_map: dict[str, str] | None = None,
) -> AsyncMock:
    s6 = AsyncMock()

    async def _resolve(ticker: str) -> UUID | None:
        if ticker_map is None:
            return None
        return ticker_map.get(ticker.upper())

    # BUG-3: the handler resolves ticker → canonical company name for the query
    # text. Default to [] (no name) so query_text stays predictable; per-test
    # ``name_map`` supplies a canonical name when the test needs it.
    async def _resolve_entities(query: str) -> list[Any]:
        if name_map and query.strip().upper() in name_map:
            return [_FakeResolvedEntity(name_map[query.strip().upper()])]
        return []

    s6.resolve_entity_by_ticker.side_effect = _resolve
    s6.resolve_entities.side_effect = _resolve_entities
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
        # BUG-3: NO hard entity_ids filter (sec_edgar chunks aren't entity-linked);
        # the ticker is anchored into the query text instead.
        assert req.entity_ids is None
        assert "AAPL" in req.query_text

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
        # BUG-3: no hard entity_ids filter; the item is still stamped with the id.
        assert req.entity_ids is None
        assert len(items) == 1
        assert items[0].citation_meta.url == _EDGAR_URL_8K
        assert items[0].entity_id == _AAPL_ID

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
        # The query is anchored on the company (ticker) AND biased toward the form.
        req = s6.search_chunks.call_args.args[0]
        assert "AAPL" in req.query_text
        assert "10-K" in req.query_text

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

    # ── BUG-3 (2026-07-01): no hard entity filter; company anchored in query text ─

    @pytest.mark.asyncio
    async def test_resolved_company_name_is_anchored_into_query_text(self) -> None:
        """The resolved canonical company NAME is added to the query text (BUG-3).

        Filings render the full company name ("NVIDIA Corporation"), so the name
        is the strongest retrieval signal now that we no longer hard-filter by
        entity id.
        """
        chunks = [
            _chunk(
                doc_id="nv-1",
                chunk_id="c1",
                text="NVIDIA Corporation ANNUAL REPORT Form 10-K.",
                url=_EDGAR_URL_10K,
            ),
        ]
        _nvda_id = UUID("018f0000-0000-7000-8000-000000aaaa02")
        s6 = _make_s6(
            chunks,
            ticker_map={"NVDA": _nvda_id},
            name_map={"NVDA": "NVIDIA Corporation"},
        )
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="NVDA")

        req = s6.search_chunks.call_args.args[0]
        assert req.entity_ids is None
        assert "NVIDIA Corporation" in req.query_text
        assert "NVDA" in req.query_text
        assert len(items) == 1
        assert items[0].citation_meta.url == _EDGAR_URL_10K

    @pytest.mark.asyncio
    async def test_entity_context_name_used_when_no_ticker(self) -> None:
        """With no explicit ticker, the scoped EntityContext name anchors the query."""
        from rag_chat.application.pipeline.tool_executor import EntityContext

        ctx = EntityContext(entity_id=_AAPL_ID, ticker="AAPL", name="Apple Inc.", pinned=False)
        chunks = [_chunk(doc_id="a-1", chunk_id="c1", text="Apple Inc. Form 10-K", url=_EDGAR_URL_10K)]
        s6 = _make_s6(chunks)
        handler = _make_handler(s6, entity_context=ctx)

        await handler._handle_get_filings()

        req = s6.search_chunks.call_args.args[0]
        assert req.entity_ids is None
        assert "Apple Inc." in req.query_text


class TestGetFilingsFilerIdentity:
    """Fix ③ (2026-07-04): filer/company identity must reach the LLM + citation.

    Before the fix, ``get_filings`` fed the model ANONYMOUS rows (form + date +
    url only — the filer name in ``result.text`` was used for form detection then
    DISCARDED) and force-stamped ``entity_name=<ticker>`` on EVERY row regardless
    of the actual filer. sec_edgar chunks are not entity-linked, so retrieval can
    return the WRONG company's filings — mislabelling them as the queried ticker.
    """

    @pytest.mark.asyncio
    async def test_filer_name_in_item_text_and_citation_title_when_matched(self) -> None:
        """A corroborated filing carries the company NAME in item text + title."""
        chunks = [
            _chunk(
                doc_id="nv-1",
                chunk_id="c1",
                text="NVIDIA Corporation ANNUAL REPORT Form 10-K for fiscal year 2026.",
                url=_EDGAR_URL_10K,
            ),
        ]
        _nvda_id = UUID("018f0000-0000-7000-8000-000000aaaa02")
        s6 = _make_s6(
            chunks,
            ticker_map={"NVDA": _nvda_id},
            name_map={"NVDA": "NVIDIA Corporation"},
        )
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="NVDA")

        assert len(items) == 1
        item = items[0]
        # Company identity is now in BOTH the citation title and the prompt text.
        assert "NVIDIA Corporation" in (item.citation_meta.title or "")
        assert "NVIDIA Corporation" in item.text
        # The queried ticker IS stamped because the filing corroborates it.
        assert item.citation_meta.entity_name == "NVDA"

    @pytest.mark.asyncio
    async def test_body_snippet_injected_so_filer_is_visible(self) -> None:
        """The filing body (where the filer name lives) is injected into item text.

        Even when the queried ticker/company is not resolved to a name, the raw
        chunk body — the only place the filer appears — must reach the prompt so
        the model can attribute the filing.
        """
        chunks = [
            _chunk(
                doc_id="ad-1",
                chunk_id="c1",
                text="CURRENT REPORT Form 8-K AGREEMENT AND PLAN OF MERGER ADIAL PHARMACEUTICALS INC",
                url=_EDGAR_URL_8K,
            ),
        ]
        # ticker resolves to an id but NO canonical name (name_map omitted).
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        assert len(items) == 1
        # The real filer name from the body reaches the prompt (was discarded before).
        assert "ADIAL PHARMACEUTICALS" in items[0].text

    @pytest.mark.asyncio
    async def test_honest_miss_when_only_wrong_filer_and_name_resolved(self) -> None:
        """NEW-1 refinement (2026-07-06): Apple query + ONLY an ADIAL 8-K → empty.

        Previously the wrong-company filing was returned unlabelled (graceful
        fallback), but the model still cited it. With a resolved company NAME to
        corroborate against and NO filing naming Apple as its filer, we now return
        an HONEST MISS — a wrong-company answer is worse than "no filings found".
        R19: this asserts the corrected spec (fails against the old fallback).
        """
        chunks = [
            _chunk(
                doc_id="ad-1",
                chunk_id="c1",
                text="CURRENT REPORT Form 8-K AGREEMENT AND PLAN OF MERGER ADIAL PHARMACEUTICALS INC",
                url=_EDGAR_URL_8K,
            ),
        ]
        s6 = _make_s6(
            chunks,
            ticker_map={"AAPL": _AAPL_ID},
            name_map={"AAPL": "Apple Inc."},  # resolves, but filing is ADIAL
        )
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        # No Apple-filer-corroborated filing exists → honest miss, not ADIAL.
        assert items == []

    @pytest.mark.asyncio
    async def test_entity_name_stamped_when_ticker_token_in_body(self) -> None:
        """Corroboration via the ticker token alone (no resolved name) stamps it."""
        chunks = [
            _chunk(
                doc_id="t-1",
                chunk_id="c1",
                text="TSLA Tesla, Inc. ANNUAL REPORT Form 10-K.",
                url=_EDGAR_URL_10K,
            ),
        ]
        _tsla_id = UUID("018f0000-0000-7000-8000-000000aaaa03")
        s6 = _make_s6(chunks, ticker_map={"TSLA": _tsla_id})  # no name_map
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="TSLA")

        assert len(items) == 1
        assert items[0].citation_meta.entity_name == "TSLA"


class TestGetFilingsRetrievalDepth:
    """R1 depth fix (2026-07-06): the financials-bearing chunk must reach the LLM.

    ROOT CAUSE (docs/audits/2026-07-05-r1-sec-filings-reqa.md §Final): get_filings
    deduped each filing to its ONE best-ranked chunk and injected only a
    <=400-char snippet — the cover / section-listing header. The revenue/segment
    numeric tables live in a DIFFERENT chunk of the same filing, so the model
    identified + attributed the filing but always said "the specific revenue
    figures are not present in the retrieved excerpt". The fix groups chunks per
    filing and injects the top-N, biased toward the numeric-dense chunk.
    """

    # The header chunk of a 10-Q: it NAMES the statements/segments (so the old
    # code's snippet looked plausible) but carries NO numbers — exactly the trap.
    _HEADER = (
        "Apple Inc. FORM 10-Q QUARTERLY REPORT pursuant to Section 13. Index: "
        "Condensed Consolidated Statements of Operations; Products and Services; "
        "iPhone, Mac, iPad, Wearables, Services segment information follows."
    )
    # The financials chunk: the actual income-statement / segment revenue numbers
    # the user asks the chat to quote. Ranks BELOW the header for the generic
    # filings query, so a plain top-N-by-relevance would still drop it.
    _FINANCIALS = (
        "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS. Total net sales $124,300 "
        "million. iPhone revenue $69,138 million. Services revenue $26,340 million. "
        "Mac $8,987 million. Net income $36,330 million. Diluted EPS $2.40."
    )
    _FILLER = "Item 4. Controls and Procedures. There were no changes in internal control."

    @pytest.mark.asyncio
    async def test_financials_chunk_reaches_llm_not_just_header(self) -> None:
        """A single filing's revenue-bearing chunk is injected, not only the header.

        Under the OLD single-best-chunk + 400-char behaviour only ``_HEADER``
        reached the prompt and the numbers were absent. The fix must surface the
        ``_FINANCIALS`` chunk of the SAME filing so the model can quote revenue.
        """
        # All three chunks belong to ONE filing (same doc_id). Header ranks best.
        chunks = [
            _chunk(
                doc_id="aapl-10q",
                chunk_id="h",
                text=TestGetFilingsRetrievalDepth._HEADER,
                url=_EDGAR_URL_10K,
                score=0.95,
            ),
            _chunk(
                doc_id="aapl-10q",
                chunk_id="f",
                text=TestGetFilingsRetrievalDepth._FINANCIALS,
                url=_EDGAR_URL_10K,
                score=0.70,
            ),
            _chunk(
                doc_id="aapl-10q",
                chunk_id="x",
                text=TestGetFilingsRetrievalDepth._FILLER,
                url=_EDGAR_URL_10K,
                score=0.60,
            ),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID}, name_map={"AAPL": "Apple Inc."})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL", form_type="10-Q")

        # Still ONE item per filing (grouping preserved, not one-per-chunk).
        assert len(items) == 1
        item = items[0]
        # The revenue/segment NUMBERS from the financials chunk now reach the LLM.
        assert "$124,300 million" in item.text
        assert "iPhone revenue $69,138 million" in item.text
        assert "Services revenue $26,340 million" in item.text
        # The header context (filer name) is still present — Fix ③ intact.
        assert "Apple Inc." in item.text
        # Citation still points at the canonical EDGAR URL and is attributed.
        assert item.citation_meta.url == _EDGAR_URL_10K
        assert item.citation_meta.entity_name == "AAPL"
        assert "10-Q" in (item.citation_meta.title or "")

    @pytest.mark.asyncio
    async def test_numeric_bias_prefers_financials_over_filler_at_low_depth(self) -> None:
        """With only 2 chunks of budget, the numeric-dense chunk wins over filler.

        Proves the selection is numeric-BIASED, not merely "first two chunks":
        the filler chunk outranks the financials chunk by relevance score, yet the
        financials chunk must be the one injected alongside the primary header.
        """
        chunks = [
            _chunk(
                doc_id="d1", chunk_id="h", text=TestGetFilingsRetrievalDepth._HEADER, url=_EDGAR_URL_10K, score=0.95
            ),
            # Filler ranks ABOVE financials by score, but has no numbers.
            _chunk(
                doc_id="d1", chunk_id="x", text=TestGetFilingsRetrievalDepth._FILLER, url=_EDGAR_URL_10K, score=0.80
            ),
            _chunk(
                doc_id="d1", chunk_id="f", text=TestGetFilingsRetrievalDepth._FINANCIALS, url=_EDGAR_URL_10K, score=0.70
            ),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID}, name_map={"AAPL": "Apple Inc."})
        # Pin depth to 2: primary header + exactly one more chunk.
        handler = _make_handler(s6)
        handler._filing_chunks_per_filing = 2

        items = await handler._handle_get_filings(ticker="AAPL", form_type="10-Q")

        assert len(items) == 1
        item = items[0]
        # The financials chunk is the one selected (numeric bias), not the filler.
        assert "$124,300 million" in item.text
        assert "Controls and Procedures" not in item.text

    @pytest.mark.asyncio
    async def test_per_filing_text_budget_is_bounded(self) -> None:
        """The injected text for one filing never exceeds the configured budget."""
        big = "Revenue $1,000 million. " * 2000  # ~46k chars, well over any cap
        chunks = [
            _chunk(doc_id="d1", chunk_id="a", text=big, url=_EDGAR_URL_10K, score=0.9),
            _chunk(doc_id="d1", chunk_id="b", text=big, url=_EDGAR_URL_10K, score=0.8),
            _chunk(doc_id="d1", chunk_id="c", text=big, url=_EDGAR_URL_10K, score=0.7),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID})
        handler = _make_handler(s6)
        handler._filing_result_max_chars = 5000
        handler._filing_snippet_max_chars = 1500

        items = await handler._handle_get_filings(ticker="AAPL")

        assert len(items) == 1
        # Hard per-filing ceiling holds regardless of chunk sizes.
        assert len(items[0].text) <= 5000


# EDGAR index URL for a DIFFERENT filer (Intel CIK 50863) — used to prove the
# wrong-company filing is NOT the one cited under an Apple query.
_EDGAR_URL_INTEL = "https://www.sec.gov/Archives/edgar/data/50863/000005086326000010/0000050863-26-000010-index.htm"


class TestGetFilingsCompanyPartition:
    """NEW-1 (2026-07-06): filings must be attributed to the QUERIED filer.

    Root cause (docs/audits/2026-07-06-r1-final-exhaustive-qa.md): the corpus
    has ~3,017 distinct CIKs; a NEWER numeric-dense filing from a DIFFERENT
    company (Meta/AMD/Intel) outranked the target's real 10-Q because the final
    sort ordered ALL grouped filings by date regardless of filer. These tests
    assert the company partition — they FAIL against the pre-fix date-only sort.
    """

    @pytest.mark.asyncio
    async def test_target_filing_selected_over_newer_wrong_company(self) -> None:
        """Apple query + a NEWER Intel filing → Apple's filing is the one returned.

        R19: this is the regression assertion for NEW-1. Under the old date-only
        sort the newer Intel row would rank FIRST (and, being non-matching, would
        also be UNLABELLED), producing the wrong-company citation seen in QA.
        """
        chunks = [
            # Apple's real 10-Q — OLDER filed date, names the company.
            _chunk(
                doc_id="018f0000-0000-7000-8000-0000000000a1",
                chunk_id="aapl-c1",
                text="Apple Inc. Form 10-Q. Total net sales $124,300 million for the quarter.",
                url=_EDGAR_URL_10K,
                days_ago=20,
            ),
            # Intel's 10-Q — NEWER filed date, numeric-dense, WRONG company.
            _chunk(
                doc_id="018f0000-0000-7000-8000-0000000000b2",
                chunk_id="intc-c1",
                text="Intel Corporation Form 10-Q. Revenue $12,900 million; operating income $1,700 million.",
                url=_EDGAR_URL_INTEL,
                days_ago=1,
            ),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID}, name_map={"AAPL": "Apple Inc."})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        # Only Apple's filing is returned; the newer Intel filing is dropped.
        assert len(items) == 1
        item = items[0]
        assert item.citation_meta.url == _EDGAR_URL_10K
        assert "Apple" in item.text
        assert "Intel" not in item.citation_meta.title
        # The matched row is LABELLED with the queried ticker (drives grounding).
        assert item.citation_meta.entity_name == "AAPL"

    @pytest.mark.asyncio
    async def test_matched_company_kept_over_newer_wrong_company_multi(self) -> None:
        """When BOTH the target and a newer wrong filer are present, only the
        target survives — and Apple's newest matching filing ranks first."""
        chunks = [
            _chunk(
                doc_id="d-aapl-old",
                chunk_id="a1",
                text="Apple Inc. Form 10-K. Net sales $391,035 million.",
                url=_EDGAR_URL_10K,
                days_ago=25,
            ),
            _chunk(
                doc_id="d-aapl-new",
                chunk_id="a2",
                text="Apple Inc. Form 10-Q. Net sales $124,300 million.",
                url=_EDGAR_URL_8K,
                days_ago=10,
            ),
            _chunk(
                doc_id="d-intc-newest",
                chunk_id="i1",
                text="Intel Corporation Form 10-Q. Revenue $12,900 million.",
                url=_EDGAR_URL_INTEL,
                days_ago=1,
            ),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID}, name_map={"AAPL": "Apple Inc."})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL", max_results=10)

        # Both Apple filings kept, Intel dropped; newest Apple first.
        assert [i.citation_meta.url for i in items] == [_EDGAR_URL_8K, _EDGAR_URL_10K]
        assert all("Intel" not in (i.citation_meta.title or "") for i in items)

    @pytest.mark.asyncio
    async def test_honest_miss_when_no_target_filing(self) -> None:
        """NEW-1 refinement: target has NO filer-corroborated filing → empty.

        Previously we returned the non-matching Intel filing unlabelled; the model
        then cited Intel as if it were Apple's filing (the NVIDIA→AMD class). With
        a resolved company name and no corroborating filer, the honest answer is
        "no filings found for Apple" — so the handler returns []. R19 regression.
        """
        chunks = [
            _chunk(
                doc_id="d-intc",
                chunk_id="i1",
                text="Intel Corporation Form 10-Q. Revenue $12,900 million.",
                url=_EDGAR_URL_INTEL,
                days_ago=1,
            ),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID}, name_map={"AAPL": "Apple Inc."})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        # No wrong-company fallback: the Intel filing is NOT returned under Apple.
        assert items == []

    @pytest.mark.asyncio
    async def test_untargeted_query_keeps_all_filings_by_date(self) -> None:
        """With no company target, behaviour is unchanged: all filings, newest
        first (the generic 'recent filings across the corpus' path)."""
        chunks = [
            _chunk(doc_id="d1", chunk_id="c1", text="Some Corp Form 8-K.", url=_EDGAR_URL_10K, days_ago=5),
            _chunk(doc_id="d2", chunk_id="c2", text="Other Corp Form 8-K.", url=_EDGAR_URL_INTEL, days_ago=1),
        ]
        s6 = _make_s6(chunks)  # no ticker_map / no ticker arg → untargeted
        handler = _make_handler(s6)

        items = await handler._handle_get_filings()

        # Both kept, newest first.
        assert [i.citation_meta.url for i in items] == [_EDGAR_URL_INTEL, _EDGAR_URL_10K]


class TestGetFilingsAuthoritativeFilerMatch:
    """NEW-1 refinement (2026-07-06, docs/audits/2026-07-06-r1-final-exhaustive-qa.md).

    The filer match must be AUTHORITATIVE (title / registrant / cover header),
    NOT a body substring. Concrete live failure: 41 AMD chunks mention "nvidia"
    as a competitor, so an AMD 10-Q passed the "names NVIDIA" partition and — being
    newer + numeric-dense — was cited as NVIDIA's 10-Q. These tests pin the
    corrected discrimination (they FAIL against the body-substring match).
    """

    @pytest.mark.asyncio
    async def test_competitor_body_mention_does_not_corroborate_filer(self) -> None:
        """NVIDIA query + an AMD 10-Q that mentions "NVIDIA" as a competitor deep in
        the body → the AMD filing is NOT selected/cited; the answer is an honest
        miss (NVIDIA has no real filing here). R19 regression for the false positive."""
        # AMD's filing: cover/header names AMD; "NVIDIA" appears ONLY far into the
        # body as a competitor, past the header window and with no cover markers.
        amd_body = (
            "Advanced Micro Devices, Inc. FORM 10-Q. "
            + "Net revenue $5,800 million. Cost of sales $3,000 million. " * 20
            + "Competition: our data-center GPUs compete with NVIDIA Corporation products."
        )
        chunks = [
            _chunk(doc_id="d-amd", chunk_id="a1", text=amd_body, url=_EDGAR_URL_INTEL, days_ago=1),
        ]
        _nvda_id = UUID("018f0000-0000-7000-8000-000000aaaa02")
        s6 = _make_s6(
            chunks,
            ticker_map={"NVDA": _nvda_id},
            name_map={"NVDA": "NVIDIA Corporation"},
        )
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="NVDA")

        # The competitor mention must NOT make AMD's filing count as NVIDIA's.
        assert items == []

    @pytest.mark.asyncio
    async def test_target_wins_over_competitor_mentioning_filing(self) -> None:
        """When BOTH NVIDIA's real 10-Q and a newer AMD filing (that name-drops
        NVIDIA) are retrieved, only NVIDIA's own filing survives + is cited."""
        amd_body = (
            "Advanced Micro Devices, Inc. FORM 10-Q. " + "Revenue $5,800 million. " * 30 + "We compete with NVIDIA."
        )
        chunks = [
            # NVIDIA's real (older) 10-Q — cover names the filer.
            _chunk(
                doc_id="d-nvda",
                chunk_id="n1",
                text="NVIDIA Corporation FORM 10-Q. Revenue $26,000 million; data center $22,000 million.",
                url=_EDGAR_URL_10K,
                days_ago=20,
            ),
            # AMD's newer filing that merely mentions NVIDIA in the body.
            _chunk(doc_id="d-amd", chunk_id="a1", text=amd_body, url=_EDGAR_URL_INTEL, days_ago=1),
        ]
        _nvda_id = UUID("018f0000-0000-7000-8000-000000aaaa02")
        s6 = _make_s6(chunks, ticker_map={"NVDA": _nvda_id}, name_map={"NVDA": "NVIDIA Corporation"})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="NVDA")

        assert len(items) == 1
        assert items[0].citation_meta.url == _EDGAR_URL_10K
        assert items[0].citation_meta.entity_name == "NVDA"

    @pytest.mark.asyncio
    async def test_registrant_charter_declaration_corroborates_filer(self) -> None:
        """The registrant name before "(Exact name of registrant …)" is authoritative
        even when the company name is not near the chunk's very start."""
        text = (
            "UNITED STATES SECURITIES AND EXCHANGE COMMISSION Washington, D.C. 20549 "
            "FORM 10-Q QUARTERLY REPORT. Commission File Number 0-23985. "
            "NVIDIA Corporation (Exact name of registrant as specified in its charter) "
            "Delaware. Revenue $26,000 million."
        )
        chunks = [_chunk(doc_id="d-nvda", chunk_id="n1", text=text, url=_EDGAR_URL_10K)]
        _nvda_id = UUID("018f0000-0000-7000-8000-000000aaaa02")
        s6 = _make_s6(chunks, ticker_map={"NVDA": _nvda_id}, name_map={"NVDA": "NVIDIA Corporation"})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="NVDA")

        assert len(items) == 1
        assert items[0].citation_meta.entity_name == "NVDA"

    @pytest.mark.asyncio
    async def test_edgar_title_corroborates_filer_when_body_lacks_name(self) -> None:
        """An EDGAR-provided title naming the company corroborates the filer even
        when the injected body chunk is a bare numeric table without the name."""
        chunks = [
            _chunk(
                doc_id="d-aapl",
                chunk_id="a1",
                text="CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS. Total net sales $124,300 million.",
                url=_EDGAR_URL_10K,
                title="Apple Inc. 10-Q (Q1 FY25)",
            ),
        ]
        s6 = _make_s6(chunks, ticker_map={"AAPL": _AAPL_ID}, name_map={"AAPL": "Apple Inc."})
        handler = _make_handler(s6)

        items = await handler._handle_get_filings(ticker="AAPL")

        assert len(items) == 1
        assert items[0].citation_meta.entity_name == "AAPL"
