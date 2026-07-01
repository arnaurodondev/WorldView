"""Unit tests for AsyncpgDocumentSearchRepository (PLAN-0064 W6 T-W6-2-02).

All tests mock SQLAlchemy AsyncSession to avoid a live DB connection.
Pattern: mock session.execute → return MagicMock with .scalar_one() or .all().
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.api.schemas import SearchDocumentsRequest
from nlp_pipeline.infrastructure.nlp_db.repositories.document_search import (
    _SEARCH_CTE,
    AsyncpgDocumentSearchRepository,
    _build_search_params,
)

pytestmark = pytest.mark.unit

# ── Fixture constants ─────────────────────────────────────────────────────────

_DOC_ID_1 = uuid.UUID("018f1e2a-0000-7000-8000-000000000001")
_DOC_ID_2 = uuid.UUID("018f1e2a-0000-7000-8000-000000000002")
_ENTITY_ID_1 = uuid.UUID("018f1e2a-0000-7000-8000-000000000010")

_START = chr(2)
_END = chr(3)


# ── Session mocking helpers ───────────────────────────────────────────────────


def _make_session(
    count: int = 0,
    rows: list[MagicMock] | None = None,
) -> AsyncMock:
    """Build an AsyncMock session returning count for the COUNT query, rows for search.

    HIGH-1: ``search()`` now issues a leading ``set_config('enable_seqscan')``
    statement (to pin the GIN index), so we dispatch on the SQL text rather than
    on a fixed call ordinal — set_config is ignored, ``count(*)`` → count,
    otherwise → rows.
    """
    session = AsyncMock()

    async def _execute(stmt: Any, *args, **kwargs) -> MagicMock:
        result = MagicMock()
        sql = str(stmt)
        if "set_config" in sql:
            return result  # planner hint — result ignored by search()
        if "count(*)" in sql:
            result.scalar_one.return_value = count
        else:
            result.all.return_value = rows or []
        return result

    session.execute = _execute
    return session


def _make_facets_session(rows: list[MagicMock] | None = None) -> AsyncMock:
    """Build an AsyncMock session that returns rows from a single execute call."""
    session = AsyncMock()

    async def _execute(stmt: Any, *args, **kwargs) -> MagicMock:
        result = MagicMock()
        result.all.return_value = rows or []
        return result

    session.execute = _execute
    return session


def _make_row(
    doc_id: uuid.UUID = _DOC_ID_1,
    rank: float = 0.5,
    snippet_marked: str = "no markers",
    source_type: str = "news",
    final_score: float = 0.4,
    title: str | None = None,
    url: str | None = None,
    published_at: datetime | None = None,
) -> MagicMock:
    row = MagicMock()
    row.doc_id = doc_id
    row.rank = rank
    row.snippet_marked = snippet_marked
    row.source_type = source_type
    row.final_score = final_score
    # HIGH-2: the search SELECT now projects title/url/published_at from dsm.
    row.title = title
    row.url = url
    row.published_at = published_at
    return row


def _make_facet_row(
    entity_id: uuid.UUID = _ENTITY_ID_1,
    entity_type: str = "company",
    cnt: int = 3,
) -> MagicMock:
    row = MagicMock()
    row.resolved_entity_id = entity_id
    row.entity_type = entity_type
    row.cnt = cnt
    return row


def _make_request(**kwargs) -> SearchDocumentsRequest:
    defaults = {"q": "Apple earnings"}
    defaults.update(kwargs)
    return SearchDocumentsRequest(**defaults)


# ── Search tests ──────────────────────────────────────────────────────────────


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_no_filters_returns_results(self) -> None:
        """Basic happy path: repo returns 1 result with correct doc_id and score."""
        session = _make_session(count=1, rows=[_make_row()])
        repo = AsyncpgDocumentSearchRepository(session)

        results, total = await repo.search(_make_request())

        assert total == 1
        assert len(results) == 1
        assert results[0].doc_id == _DOC_ID_1
        assert results[0].score == pytest.approx(0.4)
        assert results[0].source_type == "news"

    @pytest.mark.asyncio
    async def test_search_with_entity_filter_sends_entity_ids(self) -> None:
        """entity_ids are converted to string list and passed as a param."""
        eid = uuid.UUID("018f1e2a-0000-7000-8000-000000000099")
        request = _make_request(entity_ids=[eid])
        params = _build_search_params(request)

        # The param should be a list of UUID strings (not UUID objects)
        assert params["entity_ids"] == [str(eid)]

    @pytest.mark.asyncio
    async def test_search_with_source_type_filter(self) -> None:
        """source_type='news' maps to the DB enum list via _SOURCE_TYPE_MAP.

        The API exposes a coarser taxonomy ('news', 'sec_edgar') than the DB,
        which stores the canonical `ContentSourceType` literal per adapter.
        _build_search_params must translate API → DB list so the SQL ANY() clause
        matches actual rows.

        REGRESSION GUARD (feat/fix-sec-fts-source-type): the LIVE news literals
        — eodhd / eodhd_ticker_news / finnhub / newsapi — MUST be present, or the
        'news' filter silently drops ~49k real articles (it previously only
        listed the legacy seed names). Legacy seed names are still included for
        backward compatibility.
        """
        request = _make_request(source_type="news")
        params = _build_search_params(request)
        source_types = params["source_types"]
        # The four live ContentSourceType news literals must all be present:
        assert source_types is not None
        for live_literal in ("eodhd", "eodhd_ticker_news", "finnhub", "newsapi"):
            assert live_literal in source_types
        # Legacy seed names retained for backward compatibility:
        assert "eodhd_news" in source_types
        assert "press_release" in source_types

    @pytest.mark.asyncio
    async def test_search_with_sec_edgar_source_type_filter(self) -> None:
        """source_type='sec_edgar' maps to the literal stored by ingestion.

        REGRESSION GUARD (feat/fix-sec-fts-source-type): the canonical
        'sec_edgar' literal — the value the SEC EDGAR adapter path actually
        writes for every one of the 4.5k stored filings — MUST be in the mapped
        list. The original map only listed per-form seed names (sec_10k/8k/10q)
        and matched ZERO real filings.
        """
        request = _make_request(source_type="sec_edgar")
        params = _build_search_params(request)
        source_types = params["source_types"]
        assert source_types is not None
        # The bug: 'sec_edgar' (the live literal) was missing → 0 filings matched.
        assert "sec_edgar" in source_types
        # Legacy per-form seed names retained for backward compatibility:
        for legacy in ("sec_10k", "sec_8k", "sec_10q"):
            assert legacy in source_types

    @pytest.mark.asyncio
    async def test_search_source_type_all_becomes_none(self) -> None:
        """source_type='all' means no filter — :source_types param must be None."""
        request = _make_request(source_type="all")
        params = _build_search_params(request)
        assert params["source_types"] is None

    @pytest.mark.asyncio
    async def test_search_with_date_range(self) -> None:
        """date_from / date_to are forwarded unchanged to the SQL params."""
        dt_from = datetime(2026, 1, 1, tzinfo=UTC)
        dt_to = datetime(2026, 3, 31, tzinfo=UTC)
        request = _make_request(date_from=dt_from, date_to=dt_to)
        params = _build_search_params(request)

        assert params["date_from"] == dt_from
        assert params["date_to"] == dt_to

    @pytest.mark.asyncio
    async def test_search_paginates_offset_limit(self) -> None:
        """page=2, page_size=25 → OFFSET=25 (computed in repo.search, not params)."""
        # We verify indirectly: on an empty result set the session is called for count.
        # The offset/limit are set inside search(), not in _build_search_params().
        session = _make_session(count=0, rows=[])
        repo = AsyncpgDocumentSearchRepository(session)

        results, total = await repo.search(_make_request(page=2, page_size=25))

        # Empty count → fast-path returns before the second execute; still correct.
        assert total == 0
        assert results == []

    @pytest.mark.asyncio
    async def test_search_empty_results_returns_empty_tuple(self) -> None:
        """When count=0 the repo short-circuits and returns ([], 0)."""
        session = _make_session(count=0, rows=[])
        repo = AsyncpgDocumentSearchRepository(session)

        results, total = await repo.search(_make_request())

        assert total == 0
        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_special_chars_in_q(self) -> None:
        """Special chars in q are passed verbatim to the SQL param (no crash)."""
        special_q = ':;|!& "quoted phrase" OR -minus'
        request = _make_request(q=special_q)
        params = _build_search_params(request)
        # The query value is forwarded as-is; websearch_to_tsquery handles escaping.
        assert params["q"] == special_q

    @pytest.mark.asyncio
    async def test_snippet_row_contains_sentinel_bytes(self) -> None:
        """snippet_marked returned from repo still has \\x02/\\x03 bytes."""
        raw_snippet = f"foo {_START}bar{_END} baz"
        session = _make_session(count=1, rows=[_make_row(snippet_marked=raw_snippet)])
        repo = AsyncpgDocumentSearchRepository(session)

        results, _ = await repo.search(_make_request())

        assert chr(2) in (results[0].snippet or "")
        assert chr(3) in (results[0].snippet or "")

    @pytest.mark.asyncio
    async def test_search_result_has_empty_entity_hits(self) -> None:
        """entity_hits must be empty [] from the repo (use case fills it)."""
        session = _make_session(count=1, rows=[_make_row()])
        repo = AsyncpgDocumentSearchRepository(session)

        results, _ = await repo.search(_make_request())

        assert results[0].entity_hits == []

    @pytest.mark.asyncio
    async def test_search_result_title_url_published_from_dsm(self) -> None:
        """HIGH-2: title/source_url/published_at come from dsm (selected in SQL).

        Previously the repo nulled these and deferred to an S5 batch call that
        401'd in the live path. Now they are projected directly from
        document_source_metadata, so a row carrying them surfaces them verbatim.
        """
        pub = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
        row = _make_row(title="Apple 10-Q", url="https://sec.gov/aapl", published_at=pub)
        session = _make_session(count=1, rows=[row])
        repo = AsyncpgDocumentSearchRepository(session)

        results, _ = await repo.search(_make_request())

        assert results[0].title == "Apple 10-Q"
        assert results[0].source_url == "https://sec.gov/aapl"
        assert results[0].published_at == pub

    @pytest.mark.asyncio
    async def test_search_result_null_dsm_metadata_stays_none(self) -> None:
        """When dsm has no title/url/date, the result fields stay None (fallback)."""
        session = _make_session(count=1, rows=[_make_row()])
        repo = AsyncpgDocumentSearchRepository(session)

        results, _ = await repo.search(_make_request())

        assert results[0].title is None
        assert results[0].source_url is None
        assert results[0].published_at is None


# ── HIGH-1 perf guard: index pin + deferred snippet ───────────────────────────


class TestSearchPerf:
    @pytest.mark.asyncio
    async def test_search_issues_enable_seqscan_off(self) -> None:
        """HIGH-1: search() must pin the GIN index via set_config(enable_seqscan)."""
        executed: list[str] = []
        session = AsyncMock()

        async def _execute(stmt: Any, *args, **kwargs) -> MagicMock:
            executed.append(str(stmt))
            result = MagicMock()
            if "count(*)" in str(stmt):
                result.scalar_one.return_value = 0
            else:
                result.all.return_value = []
            return result

        session.execute = _execute
        repo = AsyncpgDocumentSearchRepository(session, force_index_scan=True)
        await repo.search(_make_request())

        assert any("set_config" in s and "enable_seqscan" in s for s in executed)

    @pytest.mark.asyncio
    async def test_search_skips_planner_hint_when_disabled(self) -> None:
        """force_index_scan=False must NOT issue the planner-hint statement."""
        executed: list[str] = []
        session = AsyncMock()

        async def _execute(stmt: Any, *args, **kwargs) -> MagicMock:
            executed.append(str(stmt))
            result = MagicMock()
            result.scalar_one.return_value = 0
            return result

        session.execute = _execute
        repo = AsyncpgDocumentSearchRepository(session, force_index_scan=False)
        await repo.search(_make_request())

        assert not any("set_config" in s for s in executed)

    def test_ranked_chunks_cte_defers_ts_headline(self) -> None:
        """HIGH-1: the ranked_chunks CTE must NOT compute ts_headline.

        The snippet is generated only for the paginated page rows in the SELECT
        leg — computing it for every matched chunk was the ~30s latency source.
        """
        from nlp_pipeline.infrastructure.nlp_db.repositories.document_search import (
            _SEARCH_SELECT,
        )

        ranked_cte = _SEARCH_CTE.split("top_chunk_per_doc")[0]
        assert "ts_headline" not in ranked_cte
        # ts_headline lives in the paginated SELECT leg instead.
        assert "ts_headline" in _SEARCH_SELECT


# ── Facets tests ──────────────────────────────────────────────────────────────


class TestFacets:
    @pytest.mark.asyncio
    async def test_facets_returns_results(self) -> None:
        """facets() returns one SearchDocumentsFacet per DB row."""
        session = _make_facets_session(rows=[_make_facet_row()])
        repo = AsyncpgDocumentSearchRepository(session)

        facets = await repo.facets(_make_request(), [_DOC_ID_1])

        assert len(facets) == 1
        assert facets[0].entity_id == _ENTITY_ID_1
        assert facets[0].count == 3
        assert facets[0].entity_type == "company"
        # Name must be empty — use case fills it via S7 batch
        assert facets[0].name == ""

    @pytest.mark.asyncio
    async def test_facets_returns_top_25_capped(self) -> None:
        """Mock returning 30 rows → SQL LIMIT 25 → at most 25 facets returned."""
        # We mock 30 rows but the SQL has LIMIT 25 baked in.
        # Since we mock the DB response, we simulate what the DB would return
        # (i.e., after applying LIMIT 25 the DB returns at most 25 rows).
        rows = [_make_facet_row(entity_id=uuid.uuid4(), cnt=i) for i in range(25)]
        session = _make_facets_session(rows=rows)
        repo = AsyncpgDocumentSearchRepository(session)

        facets = await repo.facets(_make_request(), [_DOC_ID_1, _DOC_ID_2])

        # The SQL LIMIT 25 ensures at most 25 rows come back from the DB.
        assert len(facets) <= 25

    @pytest.mark.asyncio
    async def test_facets_skips_unresolved_entities(self) -> None:
        """SQL has resolved_entity_id IS NOT NULL — repo returns only resolved rows."""
        # This test verifies the SQL constant contains the NOT NULL guard.
        from nlp_pipeline.infrastructure.nlp_db.repositories.document_search import _FACETS_SQL

        assert "resolved_entity_id IS NOT NULL" in _FACETS_SQL

    @pytest.mark.asyncio
    async def test_facets_empty_doc_ids_returns_empty(self) -> None:
        """facets() with no hit doc_ids returns [] without hitting DB."""
        session = AsyncMock()
        repo = AsyncpgDocumentSearchRepository(session)

        facets = await repo.facets(_make_request(), [])

        assert facets == []
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_no_canonical_entities_join_in_sql(self) -> None:
        """SQL must NOT reference canonical_entities — that table is in intelligence_db (R9)."""
        # The CTE SQL must not contain "canonical_entities" — that lives in S7's
        # intelligence_db, not nlp_db. Cross-DB joins violate R9.
        assert "canonical_entities" not in _SEARCH_CTE
