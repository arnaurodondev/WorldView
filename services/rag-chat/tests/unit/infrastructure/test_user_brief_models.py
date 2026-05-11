"""Unit tests for UserBriefModel, BriefFeedbackModel, UserBriefRecord, NullBriefArchive (PLAN-0066 Wave A).

WHY these tests: the four test cases below verify the ORM model defaults, the
frozen-dataclass invariant on the port DTO, and the no-op behaviour of the
NullBriefArchive — all without touching the database.  The SQLAlchemy models
are exercised through direct Python construction (not a live Session) so the
tests run in milliseconds with zero external deps.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest
from rag_chat.application.ports.brief_archive import NullBriefArchive, UserBriefRecord
from rag_chat.infrastructure.db.models.user_brief import BriefFeedbackModel, UserBriefModel

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
_TENANT_ID = UUID("00000000-0000-0000-0000-000000000002")
_BRIEF_ID = UUID("00000000-0000-0000-0000-000000000003")
_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# T-W10-A-02 — ORM model construction
# ---------------------------------------------------------------------------


def test_user_brief_model_defaults() -> None:
    """UserBriefModel with only required fields: optional columns are None, list defaults are empty."""
    # WHY: verifies that the ORM model correctly defaults JSONB columns to an
    # empty list (Python-side default=list) and that nullable optional fields
    # resolve to None when not supplied.
    model = UserBriefModel(
        id=_BRIEF_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        generated_at=_NOW,
        headline="Markets wrap: AI chips surge",
    )

    # Required fields stored as-is
    assert model.id == _BRIEF_ID
    assert model.user_id == _USER_ID
    assert model.tenant_id == _TENANT_ID
    assert model.brief_type == "morning"
    assert model.headline == "Markets wrap: AI chips surge"
    assert model.generated_at == _NOW

    # Optional fields default to None
    assert model.entity_id is None
    assert model.lead is None

    # WHY check Column.default: SQLAlchemy ORM instances constructed without a
    # Session do NOT auto-apply Python-side defaults — the default is only
    # applied when the ORM flushes the INSERT to the DB. Outside a Session the
    # attribute resolves to None. We verify the *Column* carries the correct
    # default callable/value so the INSERT will produce the right row.
    col_defaults = {
        c.name: c.default
        for c in UserBriefModel.__table__.columns  # type: ignore[attr-defined]
    }
    # sections_json and citations_json: Python-side CallableColumnDefault(list)
    sections_default = col_defaults["sections_json"]
    assert sections_default is not None and callable(sections_default.arg)
    citations_default = col_defaults["citations_json"]
    assert citations_default is not None and callable(citations_default.arg)
    # confidence: scalar default 1.0
    assert col_defaults["confidence"].arg == 1.0
    # source_version: scalar default "v2"
    assert col_defaults["source_version"].arg == "v2"


def test_brief_feedback_model_fields() -> None:
    """BriefFeedbackModel stores all required fields correctly."""
    # WHY: verifies that the FK column (brief_id), scope string, and nullable
    # index columns (section_idx, bullet_idx) are stored without coercion.
    model = BriefFeedbackModel(
        id=_USER_ID,  # reuse a UUID for simplicity
        brief_id=_BRIEF_ID,
        user_id=_USER_ID,
        scope="bullet",
        section_idx=0,
        bullet_idx=2,
        reaction="thumbs_up",
        created_at=_NOW,
    )

    assert model.brief_id == _BRIEF_ID
    assert model.user_id == _USER_ID
    assert model.scope == "bullet"
    assert model.section_idx == 0
    assert model.bullet_idx == 2
    assert model.reaction == "thumbs_up"
    assert model.created_at == _NOW


def test_brief_feedback_model_nullable_indices() -> None:
    """BriefFeedbackModel accepts None for section_idx and bullet_idx (brief-level feedback)."""
    model = BriefFeedbackModel(
        id=_USER_ID,
        brief_id=_BRIEF_ID,
        user_id=_USER_ID,
        scope="brief",
        reaction="thumbs_down",
        created_at=_NOW,
    )

    assert model.section_idx is None
    assert model.bullet_idx is None


# ---------------------------------------------------------------------------
# T-W10-A-03 — UserBriefRecord frozen dataclass
# ---------------------------------------------------------------------------


def test_user_brief_record_is_frozen() -> None:
    """UserBriefRecord raises FrozenInstanceError when a field is mutated after construction."""
    # WHY frozen: the port DTO must be immutable so callers cannot accidentally
    # mutate a record retrieved from the archive and persist the stale view.
    record = UserBriefRecord(
        id=_BRIEF_ID,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        entity_id=None,
        generated_at=_NOW,
        headline="Test headline",
        lead=None,
        sections_json=[],
        citations_json=[],
        confidence=0.9,
        source_version="v2",
    )

    with pytest.raises(FrozenInstanceError):
        record.headline = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# T-W10-A-03 — NullBriefArchive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_null_brief_archive_returns_empty() -> None:
    """NullBriefArchive.get_latest returns [] and get_by_id returns None."""
    # WHY: NullBriefArchive is the default DI registration; its no-op behaviour
    # must be stable so tests and local dev that skip brief persistence work.
    # WHY @pytest.mark.asyncio: NullBriefArchive methods are async coroutines;
    # using pytest-asyncio avoids the DeprecationWarning from get_event_loop().

    archive = NullBriefArchive()

    latest = await archive.get_latest(user_id=_USER_ID, tenant_id=_TENANT_ID, brief_type="morning")
    assert latest == []

    by_id = await archive.get_by_id(brief_id=_BRIEF_ID)
    assert by_id is None

    rows, total = await archive.get_history(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        brief_type="morning",
        page=1,
        page_size=10,
    )
    assert rows == []
    assert total == 0
