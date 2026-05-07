"""Tests for EntityMentionRepository ON CONFLICT DO NOTHING idempotency — F-012.

PLAN-0084 B-3: EntityMentionRepository.add() uses pg_insert + ON CONFLICT DO NOTHING
so duplicate mention_ids (from deterministic uuid5 on Kafka replay) are silently skipped.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit

_DOC_ID = UUID("00000000-0000-0000-0000-000000000002")
_MENTION_ID = UUID("00000000-0000-0000-0000-000000000001")


def _make_session() -> tuple[MagicMock, list[Any]]:
    executed: list[Any] = []

    async def _fake_execute(stmt: Any, *args: Any, **kwargs: Any) -> MagicMock:
        executed.append(stmt)
        return MagicMock(rowcount=1)

    session = MagicMock()
    session.execute = _fake_execute
    return session, executed


def _make_mention() -> object:
    """Build a minimal EntityMention-like object."""
    from nlp_pipeline.domain.models import EntityMention

    m = EntityMention.__new__(EntityMention)
    m.mention_id = _MENTION_ID
    m.doc_id = _DOC_ID
    m.section_id = UUID("00000000-0000-0000-0000-000000000003")
    m.mention_text = "Apple Inc"
    m.mention_class = None
    m.confidence = 0.9
    m.char_start = 0
    m.char_end = 9
    m.resolved_entity_id = None
    m.tenant_id = None
    m.resolution_confidence = None
    m.resolution_stage = None
    m.ner_model_id = None
    m.resolution_outcome = None
    m.resolution_noise_reason = None
    m.resolution_processed_at = None
    return m


@pytest.mark.asyncio
async def test_entity_mention_add_uses_on_conflict_do_nothing() -> None:
    """add() must use pg_insert with on_conflict_do_nothing (F-012)."""
    from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import EntityMentionRepository
    from sqlalchemy.dialects.postgresql import Insert as PgInsert

    session, executed = _make_session()
    repo = EntityMentionRepository(session)
    mention = _make_mention()

    await repo.add(mention)  # type: ignore[arg-type]

    assert len(executed) == 1
    stmt = executed[0]
    assert isinstance(stmt, PgInsert), "add() must use pg_insert (dialect-level ON CONFLICT DO NOTHING)"
    assert stmt._post_values_clause is not None, "ON CONFLICT DO NOTHING clause must be present"


@pytest.mark.asyncio
async def test_entity_mention_add_passes_mention_id() -> None:
    """The mention_id from the EntityMention must appear in the INSERT values."""
    from nlp_pipeline.infrastructure.nlp_db.repositories.entity_mention import EntityMentionRepository

    session, executed = _make_session()
    repo = EntityMentionRepository(session)
    mention = _make_mention()

    await repo.add(mention)  # type: ignore[arg-type]

    vals = {col.key: bp.value for col, bp in executed[0]._values.items()}
    assert vals["mention_id"] == _MENTION_ID
