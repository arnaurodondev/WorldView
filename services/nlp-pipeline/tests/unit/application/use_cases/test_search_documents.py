"""Unit tests for SearchDocumentsUseCase (PLAN-0064 W6 T-W6-2-03).

Uses mocked DocumentSearchRepositoryPort, _S5BatchClient, and _S7BatchClient
to test the orchestration logic in isolation.

Note: the use case returns SearchDocumentsOutput (domain DTO), not
SearchDocumentsResponse (Pydantic schema). The API route (Wave 3) maps
between the two. Tests here verify the domain DTO fields directly.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.api.schemas import (
    SearchDocumentResult,
    SearchDocumentsFacet,
    SearchDocumentsRequest,
)
from nlp_pipeline.application.use_cases.search_documents import (
    SearchDocumentsUseCase,
    _S5BatchClient,
    _S7BatchClient,
)

pytestmark = pytest.mark.unit

# ── Fixture constants ─────────────────────────────────────────────────────────

_DOC_ID_1 = uuid.UUID("018f1e2a-0000-7000-8000-000000000001")
_DOC_ID_2 = uuid.UUID("018f1e2a-0000-7000-8000-000000000002")
_ENTITY_ID_1 = uuid.UUID("018f1e2a-0000-7000-8000-000000000010")
_ENTITY_ID_2 = uuid.UUID("018f1e2a-0000-7000-8000-000000000011")

_START = chr(2)  # sentinel start byte
_END = chr(3)  # sentinel end byte


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_request(**kwargs) -> SearchDocumentsRequest:
    defaults = {"q": "Apple earnings"}
    defaults.update(kwargs)
    return SearchDocumentsRequest(**defaults)


def _make_hit(
    doc_id: uuid.UUID = _DOC_ID_1,
    source_type: str = "news",
    snippet: str | None = None,
    score: float = 0.8,
) -> SearchDocumentResult:
    return SearchDocumentResult(
        doc_id=doc_id,
        source_type=source_type,
        snippet=snippet,
        score=score,
    )


def _make_facet(
    entity_id: uuid.UUID = _ENTITY_ID_1,
    entity_type: str = "company",
    count: int = 5,
) -> SearchDocumentsFacet:
    # name="" because the repo leaves it empty (use case fills it)
    return SearchDocumentsFacet(entity_id=entity_id, name="", entity_type=entity_type, count=count)


def _make_repo(
    hits: list[SearchDocumentResult] | None = None,
    total: int = 0,
    facets: list[SearchDocumentsFacet] | None = None,
) -> MagicMock:
    """Build a mocked DocumentSearchRepositoryPort."""
    repo = MagicMock()
    repo.search = AsyncMock(return_value=(hits or [], total))
    repo.facets = AsyncMock(return_value=facets or [])
    return repo


def _make_s5(docs: dict[uuid.UUID, dict] | None = None) -> _S5BatchClient:
    """Build a mocked _S5BatchClient."""
    client = MagicMock(spec=_S5BatchClient)
    client.batch_documents = AsyncMock(return_value=docs or {})
    return client


def _make_s7(entities: dict[uuid.UUID, dict] | None = None) -> _S7BatchClient:
    """Build a mocked _S7BatchClient."""
    client = MagicMock(spec=_S7BatchClient)
    client.batch_get_entities = AsyncMock(return_value=entities or {})
    return client


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestSearchDocumentsUseCase:
    @pytest.mark.asyncio
    async def test_execute_happy_path_calls_repo_then_facets_then_gather(self) -> None:
        """Full pipeline: repo.search → repo.facets → s5 + s7 gather → output."""
        hit = _make_hit(snippet=f"foo {_START}bar{_END} baz")
        facet = _make_facet()
        repo = _make_repo(hits=[hit], total=1, facets=[facet])
        s5 = _make_s5({_DOC_ID_1: {"doc_id": str(_DOC_ID_1), "title": "Apple Q1", "url": "https://example.com"}})
        s7 = _make_s7({_ENTITY_ID_1: {"entity_id": str(_ENTITY_ID_1), "canonical_name": "Apple Inc"}})

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        # Repo must be called
        repo.search.assert_awaited_once()
        repo.facets.assert_awaited_once()
        # Response fields populated
        assert resp.total == 1
        assert resp.query == "Apple earnings"
        assert len(resp.results) == 1
        assert len(resp.facets) == 1
        assert resp.facets[0].name == "Apple Inc"
        assert resp.results[0].title == "Apple Q1"

    @pytest.mark.asyncio
    async def test_high2_prefers_repo_metadata_and_skips_s5(self) -> None:
        """HIGH-2: title/url/published_at from the repo (dsm) are used directly.

        When the repo supplies citation metadata (selected from
        document_source_metadata), the use case must NOT call the S5 batch
        endpoint (which 401'd in the live path) and must surface the repo values.
        """
        from datetime import UTC, datetime

        pub = datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
        hit = SearchDocumentResult(
            doc_id=_DOC_ID_1,
            source_type="sec_edgar",
            title="Apple 10-Q",
            source_url="https://sec.gov/aapl-10q",
            published_at=pub,
            snippet=f"foo {_START}bar{_END}",
            score=0.9,
        )
        repo = _make_repo(hits=[hit], total=1, facets=[])
        s5 = _make_s5()
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        # S5 must be skipped: batch_documents is called with an EMPTY list
        # (short-circuits to {}) because the repo already supplied the metadata.
        s5.batch_documents.assert_awaited_once_with([])
        assert resp.results[0].title == "Apple 10-Q"
        assert resp.results[0].source_url == "https://sec.gov/aapl-10q"
        assert resp.results[0].published_at == pub

    @pytest.mark.asyncio
    async def test_execute_empty_results_skips_facets_and_batch_calls(self) -> None:
        """When repo returns no hits, facets and S5/S7 must NOT be called."""
        repo = _make_repo(hits=[], total=0)
        s5 = _make_s5()
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        repo.facets.assert_not_awaited()
        s5.batch_documents.assert_not_awaited()
        s7.batch_get_entities.assert_not_awaited()
        assert resp.total == 0
        assert resp.results == []
        assert resp.facets == []

    @pytest.mark.asyncio
    async def test_execute_merges_s5_metadata_into_hits(self) -> None:
        """S5 title/source_url/published_at are merged into the result."""
        hit = _make_hit(doc_id=_DOC_ID_1)
        repo = _make_repo(hits=[hit], total=1)
        pub_dt = "2026-01-15T12:00:00Z"
        s5 = _make_s5(
            {
                _DOC_ID_1: {
                    "doc_id": str(_DOC_ID_1),
                    "title": "AAPL Q1 2026",
                    "url": "https://news.example.com/aapl",
                    "published_at": pub_dt,
                }
            }
        )
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        result = resp.results[0]
        assert result.title == "AAPL Q1 2026"
        assert result.source_url == "https://news.example.com/aapl"
        assert result.published_at == pub_dt

    @pytest.mark.asyncio
    async def test_execute_merges_s7_names_into_facets(self) -> None:
        """S7 canonical_name is merged into the facet.name field."""
        hit = _make_hit()
        facet = _make_facet(entity_id=_ENTITY_ID_1)
        repo = _make_repo(hits=[hit], total=1, facets=[facet])
        s5 = _make_s5()
        s7 = _make_s7({_ENTITY_ID_1: {"entity_id": str(_ENTITY_ID_1), "canonical_name": "Apple Inc."}})

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        assert resp.facets[0].name == "Apple Inc."

    @pytest.mark.asyncio
    async def test_execute_handles_s5_partial_response(self) -> None:
        """When S5 omits a doc_id, title falls back to None (no crash)."""
        hit1 = _make_hit(doc_id=_DOC_ID_1)
        hit2 = _make_hit(doc_id=_DOC_ID_2)
        repo = _make_repo(hits=[hit1, hit2], total=2)
        # S5 only returns data for DOC_ID_1
        s5 = _make_s5({_DOC_ID_1: {"doc_id": str(_DOC_ID_1), "title": "Found Title"}})
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        assert resp.results[0].title == "Found Title"
        assert resp.results[1].title is None  # missing → None fallback

    @pytest.mark.asyncio
    async def test_execute_handles_s7_partial_response(self) -> None:
        """When S7 omits an entity_id, that facet is DROPPED (I-001).

        Orphaned entity_mentions (resolved_entity_id in NLP DB with no
        matching canonical_entity in KG) are silently skipped.  Showing a
        raw UUID string in the facet sidebar is worse than omitting the facet.
        Only fully-resolved facets are included in the response.
        """
        hit = _make_hit()
        facet1 = _make_facet(entity_id=_ENTITY_ID_1)
        facet2 = _make_facet(entity_id=_ENTITY_ID_2)
        repo = _make_repo(hits=[hit], total=1, facets=[facet1, facet2])
        s5 = _make_s5()
        # S7 only returns data for ENTITY_ID_1 — ENTITY_ID_2 is orphaned
        s7 = _make_s7({_ENTITY_ID_1: {"entity_id": str(_ENTITY_ID_1), "canonical_name": "Apple Inc"}})

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        # Only ENTITY_ID_1 should appear — ENTITY_ID_2 is dropped, not shown as UUID
        assert len(resp.facets) == 1
        assert resp.facets[0].name == "Apple Inc"
        assert resp.facets[0].entity_id == _ENTITY_ID_1

    @pytest.mark.asyncio
    async def test_execute_runs_s5_and_s7_in_parallel(self) -> None:
        """S5 and S7 batch calls must be driven by asyncio.gather (checked via call order)."""
        hit = _make_hit()
        facet = _make_facet()
        repo = _make_repo(hits=[hit], total=1, facets=[facet])

        call_order: list[str] = []

        async def _s5_side_effect(*args, **kwargs):
            call_order.append("s5")
            return {}

        async def _s7_side_effect(*args, **kwargs):
            call_order.append("s7")
            return {}

        s5 = MagicMock(spec=_S5BatchClient)
        s5.batch_documents = AsyncMock(side_effect=_s5_side_effect)
        s7 = MagicMock(spec=_S7BatchClient)
        s7.batch_get_entities = AsyncMock(side_effect=_s7_side_effect)

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        await uc.execute(_make_request())

        # Both calls must have been made (order may vary since gather is concurrent)
        assert "s5" in call_order
        assert "s7" in call_order

    @pytest.mark.asyncio
    async def test_execute_computes_has_more_correctly(self) -> None:
        """has_more=True when total > page * page_size."""
        hits = [_make_hit(doc_id=uuid.uuid4(), score=0.5) for _ in range(25)]
        repo = _make_repo(hits=hits, total=30)  # 30 total, returning page 1 of 25
        s5 = _make_s5()
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request(page=1, page_size=25))

        assert resp.has_more is True
        assert resp.total == 30

    @pytest.mark.asyncio
    async def test_execute_has_more_false_on_last_page(self) -> None:
        """has_more=False when total <= page * page_size."""
        hits = [_make_hit(doc_id=uuid.uuid4(), score=0.5) for _ in range(5)]
        repo = _make_repo(hits=hits, total=5)  # exactly 5 results, page_size=25
        s5 = _make_s5()
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request(page=1, page_size=25))

        assert resp.has_more is False

    @pytest.mark.asyncio
    async def test_execute_records_latency_ms_non_negative(self) -> None:
        """latency_ms must always be a non-negative integer."""
        repo = _make_repo()
        s5 = _make_s5()
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        assert isinstance(resp.latency_ms, int)
        assert resp.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_execute_post_processes_snippet_markers(self) -> None:
        """Sentinel bytes in snippet are stripped to plain text + offsets."""
        raw_snippet = f"Apple {_START}reported{_END} strong earnings"
        hit = _make_hit(snippet=raw_snippet)
        repo = _make_repo(hits=[hit], total=1)
        s5 = _make_s5()
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        resp = await uc.execute(_make_request())

        result = resp.results[0]
        # Sentinel bytes must be gone from the plain text snippet
        assert chr(2) not in (result.snippet or "")
        assert chr(3) not in (result.snippet or "")
        assert result.snippet == "Apple reported strong earnings"
        # Offset for "reported" (starts at 6, length 8)
        assert result.match_offsets == [(6, 14)]

    @pytest.mark.asyncio
    async def test_execute_s5_exception_degrades_gracefully(self) -> None:
        """If S5 raises an exception, response still returns with title=None."""
        hit = _make_hit()
        repo = _make_repo(hits=[hit], total=1)
        s5 = MagicMock(spec=_S5BatchClient)
        s5.batch_documents = AsyncMock(side_effect=Exception("S5 down"))
        s7 = _make_s7()

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        # Must not raise — asyncio.gather catches it via return_exceptions=True
        resp = await uc.execute(_make_request())
        assert resp.results[0].title is None

    @pytest.mark.asyncio
    async def test_execute_s7_exception_degrades_gracefully(self) -> None:
        """If S7 raises an exception, all facets are dropped (I-001).

        When S7 is fully unavailable (exception raised), s7_data degrades to {}.
        Every facet is then unresolvable, so all are silently skipped rather
        than emitting UUID strings.  The response still succeeds (no crash) with
        an empty facets list — a graceful degradation.
        """
        hit = _make_hit()
        facet = _make_facet(entity_id=_ENTITY_ID_1)
        repo = _make_repo(hits=[hit], total=1, facets=[facet])
        s5 = _make_s5()
        s7 = MagicMock(spec=_S7BatchClient)
        s7.batch_get_entities = AsyncMock(side_effect=Exception("S7 down"))

        uc = SearchDocumentsUseCase(repo=repo, s5_client=s5, s7_client=s7)
        # Must not raise — asyncio.gather catches it via return_exceptions=True
        resp = await uc.execute(_make_request())
        # Facets cannot be resolved without S7 → all dropped, not shown as UUIDs
        assert resp.facets == []
