"""Unit tests for _fetch_brief_seed and implicit/explicit brief seeding
in ParallelRetrievalOrchestrator (PLAN-0066 Wave D T-W10-D-02).

Tests verify:
  - Explicit seed_brief_id → get_by_id called, citations injected as RetrievedItem
  - Implicit same-day brief → citations injected via get_latest
  - Yesterday's brief → NOT injected (implicit seed skipped)
  - Citations capped at _MAX_BRIEF_SEED_ITEMS (8) even when brief has 20 citations

WHY test _fetch_brief_seed directly (not via retrieve()): the function is a
module-level helper with clear inputs/outputs. Direct testing avoids the overhead
of mocking all S6/S7/S3/S1 clients just to check brief seeding logic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_USER_ID = UUID("00000000-0000-0000-0000-000000000099")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000088")
_BRIEF_ID = UUID("00000000-0000-0000-0000-000000000001")


def _make_brief(generated_at: datetime, num_citations: int = 3) -> object:
    """Build a UserBriefRecord with the given generated_at and citation count."""
    from rag_chat.application.ports.brief_archive import UserBriefRecord

    citations = [
        {"title": f"Article {i}", "url": f"https://example.com/{i}", "snippet": f"Snippet {i}."}
        for i in range(num_citations)
    ]
    return UserBriefRecord(
        id=_BRIEF_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        entity_id=None,
        generated_at=generated_at,
        headline="Markets Rally.",
        lead="Tech stocks lead.",
        sections_json=[],
        citations_json=citations,
        confidence=0.88,
        source_version="v2",
    )


def _make_mock_archive(
    brief_for_get_by_id: object | None = None,
    briefs_for_get_latest: list | None = None,
) -> MagicMock:
    """Build a mock BriefArchivePort with configurable return values."""
    mock = MagicMock()
    mock.get_by_id = AsyncMock(return_value=brief_for_get_by_id)
    mock.get_latest = AsyncMock(return_value=briefs_for_get_latest or [])
    mock.get_history = AsyncMock(return_value=([], 0))
    mock.save = AsyncMock()
    return mock


# ── T-W10-D-02: explicit seed ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_seed_injects_brief_citations() -> None:
    """seed_brief_id provided → get_by_id called, citations returned as RetrievedItem list.

    WHY: when a thread was created via POST /v1/briefings/chat/discuss, the
    thread carries a seed_brief_id. retrieve() passes it to _fetch_brief_seed
    which must use get_by_id (not get_latest) to look up the exact brief.
    """
    from rag_chat.application.pipeline.retrieval_orchestrator import _fetch_brief_seed
    from rag_chat.domain.enums import ItemType

    today = datetime.now(tz=UTC)
    brief = _make_brief(generated_at=today, num_citations=3)
    mock_archive = _make_mock_archive(brief_for_get_by_id=brief)

    items = await _fetch_brief_seed(mock_archive, _USER_ID, _TENANT_ID, seed_brief_id=_BRIEF_ID)

    # get_by_id must be called with the explicit seed_brief_id
    mock_archive.get_by_id.assert_called_once_with(_BRIEF_ID)
    # get_latest must NOT be called — we have an explicit seed
    mock_archive.get_latest.assert_not_called()

    # 3 citations → 3 RetrievedItems
    assert len(items) == 3
    for item in items:
        assert item.item_type == ItemType.chunk
        assert item.score == 0.95
        assert item.trust_weight == 0.95
        assert item.citation_meta.source_name == "Morning Brief"
        # item_id must include the brief_id for deduplication
        assert str(_BRIEF_ID) in item.item_id


# ── T-W10-D-02: implicit same-day seed ────────────────────────────────────────


@pytest.mark.asyncio
async def test_implicit_seed_injects_same_day_brief() -> None:
    """seed_brief_id=None + same-day brief → citations injected via get_latest.

    WHY: the implicit seed lets any chat session on the same day as a brief
    generation benefit from the brief context without the user having clicked
    "Discuss in chat".
    """
    from rag_chat.application.pipeline.retrieval_orchestrator import _fetch_brief_seed

    today = datetime.now(tz=UTC)
    brief = _make_brief(generated_at=today, num_citations=2)
    mock_archive = _make_mock_archive(briefs_for_get_latest=[brief])

    items = await _fetch_brief_seed(mock_archive, _USER_ID, _TENANT_ID, seed_brief_id=None)

    # get_latest called (implicit path)
    mock_archive.get_latest.assert_called_once()
    # get_by_id must NOT be called
    mock_archive.get_by_id.assert_not_called()

    assert len(items) == 2


# ── T-W10-D-02: implicit seed skipped for yesterday's brief ───────────────────


@pytest.mark.asyncio
async def test_no_seed_when_brief_is_from_yesterday() -> None:
    """seed_brief_id=None + yesterday's brief → NOT injected (stale brief filter).

    WHY: implicit seeding is only useful for the current day's brief. Yesterday's
    brief contains stale context that may mislead the LLM for today's questions.
    The _is_same_day() check enforces this boundary using UTC dates (R11).
    """
    from rag_chat.application.pipeline.retrieval_orchestrator import _fetch_brief_seed

    yesterday = datetime.now(tz=UTC) - timedelta(days=1)
    brief = _make_brief(generated_at=yesterday, num_citations=3)
    mock_archive = _make_mock_archive(briefs_for_get_latest=[brief])

    items = await _fetch_brief_seed(mock_archive, _USER_ID, _TENANT_ID, seed_brief_id=None)

    # Yesterday's brief → empty result (stale, not injected)
    assert items == []
    mock_archive.get_latest.assert_called_once()


# ── T-W10-D-02: cap at 8 items ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_capped_at_8_items() -> None:
    """Brief with 20 citations → only 8 RetrievedItems returned.

    WHY: injecting all citations from a large brief would crowd out other
    retrieval results. _MAX_BRIEF_SEED_ITEMS caps the injection at 8 items
    (≈2-3 KB of context budget).
    """
    from rag_chat.application.pipeline.retrieval_orchestrator import (
        _MAX_BRIEF_SEED_ITEMS,
        _fetch_brief_seed,
    )

    today = datetime.now(tz=UTC)
    brief = _make_brief(generated_at=today, num_citations=20)
    mock_archive = _make_mock_archive(brief_for_get_by_id=brief)

    items = await _fetch_brief_seed(mock_archive, _USER_ID, _TENANT_ID, seed_brief_id=_BRIEF_ID)

    # Never more than _MAX_BRIEF_SEED_ITEMS regardless of citation count
    assert len(items) == _MAX_BRIEF_SEED_ITEMS
    assert _MAX_BRIEF_SEED_ITEMS == 8


# ── T-W10-D-02: no archive → empty result ─────────────────────────────────────


@pytest.mark.asyncio
async def test_no_seed_when_archive_raises() -> None:
    """Archive raises → empty list (error swallowed, retrieval continues).

    WHY: brief seeding is a non-critical enrichment. If the archive is
    unavailable (e.g. DB timeout), the retrieval pipeline must continue
    and return results from other sources (S6 chunks, S7 relations, etc.).
    """
    from rag_chat.application.pipeline.retrieval_orchestrator import _fetch_brief_seed

    mock_archive = MagicMock()
    mock_archive.get_by_id = AsyncMock(side_effect=RuntimeError("DB timeout"))
    mock_archive.get_latest = AsyncMock(side_effect=RuntimeError("DB timeout"))

    items = await _fetch_brief_seed(mock_archive, _USER_ID, _TENANT_ID, seed_brief_id=_BRIEF_ID)
    assert items == []


# ── T-W10-D-02: empty citations → empty result ────────────────────────────────


@pytest.mark.asyncio
async def test_no_seed_when_citations_empty() -> None:
    """Brief with empty citations_json → empty list (no items to inject).

    WHY: citations_json=[] happens when a brief was generated but no source
    articles were retrieved (e.g. early dev environment with empty S6 index).
    The brief exists but has nothing to inject.
    """
    from rag_chat.application.pipeline.retrieval_orchestrator import _fetch_brief_seed
    from rag_chat.application.ports.brief_archive import UserBriefRecord

    today = datetime.now(tz=UTC)
    brief = UserBriefRecord(
        id=_BRIEF_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        entity_id=None,
        generated_at=today,
        headline="Empty Brief.",
        lead=None,
        sections_json=[],
        citations_json=[],  # No citations
        confidence=0.5,
        source_version="v2",
    )
    mock_archive = _make_mock_archive(brief_for_get_by_id=brief)

    items = await _fetch_brief_seed(mock_archive, _USER_ID, _TENANT_ID, seed_brief_id=_BRIEF_ID)
    assert items == []
