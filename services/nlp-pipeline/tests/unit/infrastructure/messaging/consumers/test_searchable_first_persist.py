"""BP-719 Mode B — searchable-artefact-first persistence regression tests.

The article consumer used to write the SEARCHABLE artefacts (sections, chunks /
``chunk_text``, chunk + section embeddings) only in the trailing transaction, AFTER
the ML enrichment phase (Blocks 8-10). A deep-extraction timeout / 900s Kafka
watchdog cancellation therefore rolled the whole transaction back and the doc was
never indexed (~500+ DLQ rows, incl. NVIDIA/MSFT 10-Qs).

These tests pin the fix at the block / repository level:
  * ``persist_searchable_artifacts`` writes sections + chunks + embeddings and does
    NOT commit (the caller owns the transaction boundary).
  * The searchable chunk INSERT is idempotent (``ON CONFLICT DO NOTHING``) so a
    reprocessed message never duplicates a chunk.
  * ``persist_artifacts`` (post-ML) refreshes the chunk ``entity_mentions`` JSONB
    with the resolved mentions instead of re-inserting the chunk row.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.domain.models import Chunk, Section
from nlp_pipeline.infrastructure.messaging.consumers.blocks.persist import (
    persist_artifacts,
    persist_searchable_artifacts,
)
from nlp_pipeline.infrastructure.nlp_db.repositories.chunk import ChunkRepository

# Reuse the hand-built settings / ML-result helpers from the persist-floor suite.
from .test_persist_floor import _make_settings, _mention, _ml_result, _stub_async_repo

pytestmark = pytest.mark.unit


def _section() -> Section:
    return Section(
        section_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_index=0,
        char_start=0,
        char_end=20,
        text="Some section body.",
        section_type="body",
        title="T",
    )


def _chunk(doc_id: uuid.UUID, section_id: uuid.UUID) -> Chunk:
    return Chunk(
        chunk_id=uuid.uuid4(),
        doc_id=doc_id,
        section_id=section_id,
        chunk_index=0,
        char_start=0,
        char_end=20,
        token_count=4,
        text="Some section body.",
    )


@pytest.mark.asyncio
async def test_persist_searchable_artifacts_writes_and_does_not_commit() -> None:
    """Phase 1 writes sections + chunks + embeddings but never commits.

    The caller (``_run_pipeline``) owns the commit so the searchable write lands
    in its OWN transaction, independent of the later ML/enrichment transaction.
    """
    settings = _make_settings()
    doc_id = uuid.uuid4()
    section = _section()
    chunk = _chunk(doc_id, section.section_id)

    section_repo = _stub_async_repo()
    chunk_repo = _stub_async_repo()
    nlp_session = AsyncMock()
    nlp_session.execute = AsyncMock()

    returned = await persist_searchable_artifacts(
        nlp_session=nlp_session,
        section_repo=section_repo,
        chunk_repo=chunk_repo,
        doc_id=doc_id,
        sections=[section],
        chunks=[chunk],
        chunk_embs=[(chunk.chunk_id, [0.1, 0.2])],
        section_embs=[(section.section_id, [0.3, 0.4])],
        pending=None,
        gliner_mention_floor=settings.gliner_mention_floor,
        settings=settings,
        ner_mentions=[],
    )

    # Sections + chunks (the searchable rows) were written.
    section_repo.add_batch.assert_awaited_once()
    chunk_repo.add_batch.assert_awaited_once()
    # Embeddings written via session.execute (2 rows: 1 chunk + 1 section).
    assert nlp_session.execute.await_count == 2
    # Phase 1 must NOT commit — the caller owns the transaction boundary.
    nlp_session.commit.assert_not_called()
    # Returns the (augmented) chunks so the caller can carry them into the ML phase.
    assert [c.chunk_id for c in returned] == [chunk.chunk_id]


@pytest.mark.asyncio
async def test_searchable_chunk_insert_is_idempotent() -> None:
    """The chunk INSERT uses ON CONFLICT DO NOTHING → reprocessing never dupes.

    We compile the statement handed to ``session.execute`` and assert the
    conflict clause is present, which is what makes a Kafka redelivery of the
    same message safe after an enrichment retry.
    """
    from sqlalchemy.dialects import postgresql

    session = AsyncMock()
    session.execute = AsyncMock()
    chunk = _chunk(uuid.uuid4(), uuid.uuid4())

    await ChunkRepository(session).add(chunk)

    stmt = session.execute.await_args.args[0]
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in compiled.upper()
    assert "DO NOTHING" in compiled.upper()


@pytest.mark.asyncio
async def test_update_entity_mentions_batch_updates_only_jsonb() -> None:
    """``update_entity_mentions_batch`` issues an UPDATE of only entity_mentions.

    It must NOT re-insert the chunk (which would be a DO-NOTHING no-op and would
    never refresh the JSONB) and must NOT touch chunk_text.
    """
    from sqlalchemy.dialects import postgresql

    session = AsyncMock()
    session.execute = AsyncMock()
    chunk = _chunk(uuid.uuid4(), uuid.uuid4())

    await ChunkRepository(session).update_entity_mentions_batch([chunk])

    session.execute.assert_awaited_once()
    compiled = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect())).upper()
    assert compiled.startswith("UPDATE")
    assert "ENTITY_MENTIONS" in compiled
    assert "CHUNK_TEXT" not in compiled


@pytest.mark.asyncio
async def test_persist_artifacts_refreshes_chunk_jsonb_not_reinserts() -> None:
    """Post-ML persist_artifacts refreshes the chunk JSONB (no chunk re-insert).

    Regression guard: sections/chunks/embeddings moved to phase 1, so
    persist_artifacts must NOT call ``chunk_repo.add_batch`` again — it only
    updates the already-inserted chunks' resolved-mention JSONB.
    """
    settings = _make_settings(min_persist_floor=0.6)
    doc_id = uuid.uuid4()
    section_id = uuid.uuid4()
    chunk = _chunk(doc_id, section_id)
    mention = _mention(0.9)

    chunk_repo = _stub_async_repo()
    nlp_session = AsyncMock()
    nlp_session.execute = AsyncMock()

    await persist_artifacts(
        nlp_session=nlp_session,
        section_repo=_stub_async_repo(),
        chunk_repo=chunk_repo,
        outbox_repo=_stub_async_repo(),
        routing_decision_repo=_stub_async_repo(),
        entity_mention_repo=_stub_async_repo(),
        doc_entity_stats_repo=_stub_async_repo(),
        chunk_entity_mention_repo=_stub_async_repo(),
        mention_resolution_repo=_stub_async_repo(),
        doc_id=doc_id,
        sections=[_section()],
        stats=MagicMock(),
        chunks=[chunk],
        chunk_embs=[(chunk.chunk_id, [0.1])],
        section_embs=[(section_id, [0.2])],
        pending=None,
        gliner_mention_floor=settings.gliner_mention_floor,
        settings=settings,
        ml=_ml_result([mention]),
    )

    # Phase 1 owns the chunk INSERT — persist_artifacts must NOT re-add chunks.
    chunk_repo.add_batch.assert_not_awaited()
    # But it MUST refresh the resolved-mention JSONB in place.
    chunk_repo.update_entity_mentions_batch.assert_awaited_once()
