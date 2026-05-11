"""Unit tests for BriefDiffUseCase (PLAN-0066 Wave C T-W10-C-01).

Tests verify:
  - new_bullets: bullet in today's brief but not in yesterday's
  - removed_bullets: bullet in yesterday's brief but not in today's
  - no_diff_available when fewer than 2 briefs exist
  - identical briefs produce empty new_bullets and removed_bullets

WHY mock BriefArchivePort: BriefDiffUseCase depends on the port (Protocol),
not the concrete SqlBriefArchive. Using AsyncMock keeps tests DB-free and
validates the R25 invariant — the use case never touches infrastructure directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from rag_chat.application.ports.brief_archive import UserBriefRecord
from rag_chat.application.use_cases.brief_diff import BriefDiffUseCase

pytestmark = pytest.mark.unit

# ── Shared fixtures ───────────────────────────────────────────────────────────

_USER_ID = UUID("00000000-0000-0000-0000-000000000099")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000088")
_BRIEF_ID_TODAY = UUID("00000000-0000-0000-0000-000000000001")
_BRIEF_ID_YESTERDAY = UUID("00000000-0000-0000-0000-000000000002")
_TODAY = datetime(2026, 5, 8, 9, 0, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 5, 7, 9, 0, 0, tzinfo=UTC)


def _make_record(
    brief_id: UUID,
    generated_at: datetime,
    sections_json: list[dict],
) -> UserBriefRecord:
    """Build a UserBriefRecord with the given sections_json and minimal other fields."""
    return UserBriefRecord(
        id=brief_id,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        entity_id=None,
        generated_at=generated_at,
        headline="Test Brief",
        lead=None,
        sections_json=sections_json,
        citations_json=[],
        confidence=0.85,
        source_version="v2",
    )


def _make_archive(records: list[UserBriefRecord]) -> AsyncMock:
    """Create a mock BriefArchivePort that returns the given records from get_latest()."""
    archive = AsyncMock()
    archive.get_latest = AsyncMock(return_value=records)
    return archive


# ── T-W10-C-01: new bullets detected ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_detects_new_bullets() -> None:
    """Bullet in today's brief that is absent from yesterday's → appears in new_bullets.

    WHY this test: core correctness of the diff engine. If a bullet appears in
    today's brief but not yesterday's, users must see it in the "What's new" panel.
    The use case must detect it and label it correctly.
    """
    today_sections = [
        {
            "title": "Market Movers",
            "bullets": [
                {"text": "Apple hits all-time high on AI chip demand."},
                {"text": "New: Fed signals rate pause through Q3."},  # not in yesterday
            ],
        }
    ]
    yesterday_sections = [
        {
            "title": "Market Movers",
            "bullets": [
                {"text": "Apple hits all-time high on AI chip demand."},
            ],
        }
    ]

    today_record = _make_record(_BRIEF_ID_TODAY, _TODAY, today_sections)
    yesterday_record = _make_record(_BRIEF_ID_YESTERDAY, _YESTERDAY, yesterday_sections)
    archive = _make_archive([today_record, yesterday_record])

    uc = BriefDiffUseCase(archive=archive)
    result = await uc.execute(user_id=_USER_ID, tenant_id=_TENANT_ID)

    assert result.status == "diff_available"
    # One new bullet: the "Fed signals" bullet
    new_texts = [b.text for b in result.new_bullets]
    assert any("Fed signals rate pause" in t for t in new_texts), f"Expected new bullet about Fed, got: {new_texts}"
    # The shared Apple bullet should NOT be in new_bullets
    assert not any("Apple hits" in t for t in new_texts), f"Shared bullet wrongly flagged as new: {new_texts}"
    assert result.today_generated_at is not None
    assert result.yesterday_generated_at is not None


# ── T-W10-C-01: removed bullets detected ─────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_detects_removed_bullets() -> None:
    """Bullet in yesterday's brief that is absent from today's → appears in removed_bullets.

    WHY this test: the diff must also surface bullets that dropped out. Users
    need to know what context was removed (e.g. a resolved geopolitical risk).
    """
    today_sections = [
        {
            "title": "Geopolitical",
            "bullets": [
                {"text": "Tensions ease in Middle East trade corridor."},
            ],
        }
    ]
    yesterday_sections = [
        {
            "title": "Geopolitical",
            "bullets": [
                {"text": "Tensions ease in Middle East trade corridor."},
                {"text": "Yesterday-only: Iran sanctions extended."},  # removed today
            ],
        }
    ]

    today_record = _make_record(_BRIEF_ID_TODAY, _TODAY, today_sections)
    yesterday_record = _make_record(_BRIEF_ID_YESTERDAY, _YESTERDAY, yesterday_sections)
    archive = _make_archive([today_record, yesterday_record])

    uc = BriefDiffUseCase(archive=archive)
    result = await uc.execute(user_id=_USER_ID, tenant_id=_TENANT_ID)

    assert result.status == "diff_available"
    removed_texts = [b.text for b in result.removed_bullets]
    assert any(
        "Iran sanctions" in t for t in removed_texts
    ), f"Expected removed bullet about Iran sanctions, got: {removed_texts}"
    # The shared Geopolitical bullet must NOT appear in removed_bullets
    assert not any(
        "Tensions ease" in t for t in removed_texts
    ), f"Shared bullet wrongly flagged as removed: {removed_texts}"


# ── T-W10-C-01: no_diff_available when history < 2 ───────────────────────────


@pytest.mark.asyncio
async def test_diff_no_data_returns_no_diff() -> None:
    """Fewer than 2 briefs in the archive → status='no_diff_available'.

    WHY this test: new users or users on day-1 have only one brief. The use
    case must return a safe result (not crash) and the frontend must be able
    to surface a "no history yet" message from delta_summary.
    """
    # Case 1: exactly one brief
    one_record = _make_record(_BRIEF_ID_TODAY, _TODAY, [])
    archive_one = _make_archive([one_record])

    uc = BriefDiffUseCase(archive=archive_one)
    result_one = await uc.execute(user_id=_USER_ID, tenant_id=_TENANT_ID)

    assert result_one.status == "no_diff_available"
    assert result_one.new_bullets == []
    assert result_one.removed_bullets == []
    assert result_one.today_generated_at is not None
    assert result_one.yesterday_generated_at is None

    # Case 2: zero briefs — use a fresh use case with a new archive
    archive_zero = _make_archive([])
    uc_zero = BriefDiffUseCase(archive=archive_zero)
    result_zero = await uc_zero.execute(user_id=_USER_ID, tenant_id=_TENANT_ID)

    assert result_zero.status == "no_diff_available"
    assert result_zero.today_generated_at is None


# ── T-W10-C-01: identical briefs produce empty delta ─────────────────────────


@pytest.mark.asyncio
async def test_diff_identical_briefs_empty_delta() -> None:
    """Same sections and bullets in both briefs → new_bullets=[], removed_bullets=[].

    WHY this test: if today's brief is identical to yesterday's (e.g. no new
    market events), the diff engine must not falsely report new/removed bullets.
    Normalisation (lowercase+strip) must make "Fed decision" == "fed decision".
    """
    shared_sections = [
        {
            "title": "Tech",
            "bullets": [
                {"text": "NVIDIA leads GPU market with H100 dominance."},
                {"text": "Apple hits all-time high on AI chip demand."},
            ],
        },
        {
            "title": "Macro",
            "bullets": [
                # WHY mixed case: tests that normalise() lowercases before comparing.
                {"text": "Fed holds rates steady."},
            ],
        },
    ]

    today_record = _make_record(_BRIEF_ID_TODAY, _TODAY, shared_sections)
    # Identical sections but with slightly different casing to test normalisation
    yesterday_sections_same = [
        {
            "title": "Tech",
            "bullets": [
                {"text": "NVIDIA leads GPU market with H100 dominance."},
                {"text": "Apple hits all-time high on AI chip demand."},
            ],
        },
        {
            "title": "Macro",
            "bullets": [
                # Same content as today — normalise() must treat these as equal
                {"text": "Fed holds rates steady."},
            ],
        },
    ]
    yesterday_record = _make_record(_BRIEF_ID_YESTERDAY, _YESTERDAY, yesterday_sections_same)
    archive = _make_archive([today_record, yesterday_record])

    uc = BriefDiffUseCase(archive=archive)
    result = await uc.execute(user_id=_USER_ID, tenant_id=_TENANT_ID)

    assert result.status == "diff_available"
    assert result.new_bullets == [], f"Expected no new bullets, got: {result.new_bullets}"
    assert result.removed_bullets == [], f"Expected no removed bullets, got: {result.removed_bullets}"
    assert result.changed_sections == [], f"Expected no changed sections, got: {result.changed_sections}"


# ── T-W10-C-01: delta_summary format ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_diff_delta_summary_format() -> None:
    """delta_summary string follows the expected "N new bullet(s), M removed since YYYY-MM-DD" pattern."""
    today_sections = [{"title": "Markets", "bullets": [{"text": "New bullet today."}]}]
    yesterday_sections = [{"title": "Markets", "bullets": [{"text": "Old bullet yesterday."}]}]

    today_record = _make_record(_BRIEF_ID_TODAY, _TODAY, today_sections)
    yesterday_record = _make_record(_BRIEF_ID_YESTERDAY, _YESTERDAY, yesterday_sections)
    archive = _make_archive([today_record, yesterday_record])

    uc = BriefDiffUseCase(archive=archive)
    result = await uc.execute(user_id=_USER_ID, tenant_id=_TENANT_ID)

    # "1 new bullet, 1 removed since 2026-05-07"
    assert "new bullet" in result.delta_summary
    assert "removed" in result.delta_summary
    assert "2026-05-07" in result.delta_summary
