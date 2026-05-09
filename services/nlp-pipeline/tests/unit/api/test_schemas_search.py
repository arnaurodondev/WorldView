"""Unit tests for SearchDocuments* Pydantic schemas (PLAN-0064 W6 T-W6-1-01).

No fixtures needed — pure model validation tests.
All validation is enforced at instantiation time by Pydantic v2, so we assert
that ValidationError is raised on bad inputs and that valid inputs parse cleanly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from nlp_pipeline.api.schemas import (
    SearchDocumentResult,
    SearchDocumentsFacet,
    SearchDocumentsRequest,
    SearchDocumentsResponse,
)
from pydantic import ValidationError

pytestmark = pytest.mark.unit

# ── Helpers ───────────────────────────────────────────────────────────────────

_UUID_A = "018f1e2a-0000-7000-8000-000000000001"
_UUID_B = "018f1e2a-0000-7000-8000-000000000002"


def _utc(year: int, month: int, day: int) -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime(year, month, day, tzinfo=UTC)


# ── SearchDocumentsRequest validation ─────────────────────────────────────────


@pytest.mark.unit
def test_request_q_required_min_length_1() -> None:
    """Empty q should raise ValidationError (min_length=1)."""
    with pytest.raises(ValidationError):
        SearchDocumentsRequest(q="")


@pytest.mark.unit
def test_request_q_max_length_500() -> None:
    """q longer than 500 characters should raise ValidationError."""
    with pytest.raises(ValidationError):
        SearchDocumentsRequest(q="a" * 501)


@pytest.mark.unit
def test_request_q_at_max_length_accepted() -> None:
    """q of exactly 500 characters should be accepted."""
    req = SearchDocumentsRequest(q="a" * 500)
    assert len(req.q) == 500


@pytest.mark.unit
def test_request_page_size_max_100() -> None:
    """page_size > 100 should raise ValidationError (NOT 51 — corrected limit is 100)."""
    with pytest.raises(ValidationError):
        SearchDocumentsRequest(q="test", page_size=101)


@pytest.mark.unit
def test_request_page_size_100_accepted() -> None:
    """page_size=100 is the maximum and should be accepted."""
    req = SearchDocumentsRequest(q="test", page_size=100)
    assert req.page_size == 100


@pytest.mark.unit
def test_request_page_max_40() -> None:
    """page > 40 should raise ValidationError."""
    with pytest.raises(ValidationError):
        SearchDocumentsRequest(q="test", page=41)


@pytest.mark.unit
def test_request_page_40_accepted() -> None:
    """page=40 is the maximum and should be accepted."""
    req = SearchDocumentsRequest(q="test", page=40)
    assert req.page == 40


@pytest.mark.unit
def test_request_date_range_inverted_rejected() -> None:
    """date_from > date_to should raise ValidationError."""
    with pytest.raises(ValidationError, match="date_from must be <= date_to"):
        SearchDocumentsRequest(
            q="test",
            date_from=_utc(2026, 5, 10),
            date_to=_utc(2026, 5, 1),
        )


@pytest.mark.unit
def test_request_naive_datetime_rejected() -> None:
    """Timezone-naive datetimes should raise ValidationError."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        SearchDocumentsRequest(
            q="test",
            date_from=datetime(2026, 5, 1),  # naive — no tzinfo  # noqa: DTZ001
        )


@pytest.mark.unit
def test_request_source_type_transcript_rejected() -> None:
    """source_type='transcript' should raise ValidationError — not yet ingested."""
    with pytest.raises(ValidationError):
        SearchDocumentsRequest(q="test", source_type="transcript")  # type: ignore[arg-type]


@pytest.mark.unit
def test_request_valid_defaults() -> None:
    """Minimal valid request uses correct defaults."""
    req = SearchDocumentsRequest(q="apple earnings")
    assert req.scope == "all"
    assert req.source_type == "all"
    assert req.page == 1
    assert req.page_size == 25
    assert req.entity_ids == []
    assert req.date_from is None
    assert req.date_to is None
    assert req.date_preset is None


@pytest.mark.unit
def test_request_equal_dates_accepted() -> None:
    """date_from == date_to (same point in time) should be accepted."""
    dt = _utc(2026, 5, 1)
    req = SearchDocumentsRequest(q="test", date_from=dt, date_to=dt)
    assert req.date_from == req.date_to


# ── SearchDocumentResult validation ──────────────────────────────────────────


@pytest.mark.unit
def test_result_snippet_accepts_angle_brackets() -> None:
    """snippet with '<' or '>' is accepted — financial text like 'P/E <15x' is legitimate.

    The _no_html_in_snippet validator was removed (PLAN-0064 bug-fix) because
    SEC filing and financial article chunks legitimately contain angle bracket
    comparisons (price <$50, yield >3%).  The repo constructs SearchDocumentResult
    with raw ts_headline output (sentinels not yet stripped), and these chars are
    not security-sensitive since the frontend renders highlights via match_offsets,
    not dangerouslySetInnerHTML.
    """
    r = SearchDocumentResult(
        doc_id=_UUID_A,
        source_type="news",
        score=0.9,
        snippet="P/E ratio <15x and dividend yield >3%",
    )
    assert "<" in (r.snippet or "") and ">" in (r.snippet or "")


@pytest.mark.unit
def test_result_snippet_none_accepted() -> None:
    """snippet=None should be accepted (no text available)."""
    r = SearchDocumentResult(doc_id=_UUID_A, source_type="news", score=0.9, snippet=None)
    assert r.snippet is None


@pytest.mark.unit
def test_result_match_offsets_invalid_start_gte_end() -> None:
    """match_offsets with start >= end should raise ValidationError."""
    with pytest.raises(ValidationError, match="start must be < end"):
        SearchDocumentResult(
            doc_id=_UUID_A,
            source_type="news",
            score=0.9,
            match_offsets=[(5, 3)],
        )


@pytest.mark.unit
def test_result_match_offsets_equal_start_end_rejected() -> None:
    """match_offsets with start == end is a zero-length range — must be rejected."""
    with pytest.raises(ValidationError, match="start must be < end"):
        SearchDocumentResult(
            doc_id=_UUID_A,
            source_type="news",
            score=0.9,
            match_offsets=[(5, 5)],
        )


@pytest.mark.unit
def test_result_valid_match_offsets() -> None:
    """Valid match_offsets should be accepted."""
    r = SearchDocumentResult(
        doc_id=_UUID_A,
        source_type="news",
        score=0.9,
        match_offsets=[(0, 5), (10, 20)],
    )
    assert r.match_offsets == [(0, 5), (10, 20)]


# ── SearchDocumentsResponse validation ───────────────────────────────────────


@pytest.mark.unit
def test_response_has_more_true_when_total_exceeds_page() -> None:
    """has_more=True when there are more pages beyond the current one."""
    # total=100, page=1, page_size=25 → pages 2..4 remain → has_more=True
    resp = SearchDocumentsResponse(
        query="apple",
        total=100,
        page=1,
        page_size=25,
        has_more=True,
        results=[],
        latency_ms=42,
    )
    assert resp.has_more is True


@pytest.mark.unit
def test_response_has_more_false_on_last_page() -> None:
    """has_more=False when we're on the last page."""
    resp = SearchDocumentsResponse(
        query="apple",
        total=25,
        page=1,
        page_size=25,
        has_more=False,
        results=[],
        latency_ms=10,
    )
    assert resp.has_more is False


@pytest.mark.unit
def test_response_facets_accepted() -> None:
    """A list of SearchDocumentsFacet should be accepted in the response."""
    facet = SearchDocumentsFacet(
        entity_id=_UUID_A,
        name="Apple Inc.",
        entity_type="company",
        count=12,
    )
    resp = SearchDocumentsResponse(
        query="apple",
        total=12,
        page=1,
        page_size=25,
        has_more=False,
        results=[],
        facets=[facet],
        latency_ms=88,
    )
    assert len(resp.facets) == 1
    assert resp.facets[0].name == "Apple Inc."
