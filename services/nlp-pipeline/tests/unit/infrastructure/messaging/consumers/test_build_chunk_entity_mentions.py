"""Unit tests for _build_chunk_entity_mentions (PLAN-0078 Wave B).

Covers the char-offset overlap + confidence floor logic that builds the
entity_mentions JSONB payload stored on each chunk.
"""

from __future__ import annotations

import uuid

import pytest
from nlp_pipeline.domain.enums import MentionClass
from nlp_pipeline.domain.models import Chunk, EntityMention
from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
    _build_chunk_entity_mentions,
)

pytestmark = pytest.mark.unit

# ── Helpers ────────────────────────────────────────────────────────────────────


def _chunk(chunk_id: uuid.UUID, section_id: uuid.UUID, char_start: int, char_end: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=uuid.uuid4(),
        section_id=section_id,
        chunk_index=0,
        char_start=char_start,
        char_end=char_end,
        token_count=50,
        text="placeholder text",
    )


def _mention(
    mention_id: uuid.UUID,
    section_id: uuid.UUID,
    char_start: int,
    char_end: int,
    confidence: float = 0.8,
    resolved_entity_id: uuid.UUID | None = None,
    mention_class: MentionClass = MentionClass.ORGANIZATION,
    text: str = "Apple Inc",
) -> EntityMention:
    return EntityMention(
        mention_id=mention_id,
        doc_id=uuid.uuid4(),
        section_id=section_id,
        mention_text=text,
        mention_class=mention_class,
        confidence=confidence,
        char_start=char_start,
        char_end=char_end,
        resolved_entity_id=resolved_entity_id,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestBuildChunkEntityMentions:
    @pytest.mark.unit
    def test_mention_overlapping_chunk_is_included(self) -> None:
        """A mention whose char range overlaps the chunk is stored."""
        section_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        entity_id = uuid.uuid4()

        chunk = _chunk(chunk_id, section_id, 0, 100)
        mention = _mention(uuid.uuid4(), section_id, 10, 20, confidence=0.8, resolved_entity_id=entity_id)

        result = _build_chunk_entity_mentions([chunk], [mention], mention_floor=0.6)

        assert chunk_id in result
        assert len(result[chunk_id]) == 1
        entry = result[chunk_id][0]
        assert entry["entity_id"] == str(entity_id)
        assert entry["entity_type"] == MentionClass.ORGANIZATION.value
        assert entry["char_start"] == 10
        assert entry["char_end"] == 20
        assert entry["gliner_score"] == 0.8
        assert entry["raw_text"] == "Apple Inc"

    @pytest.mark.unit
    def test_mention_below_floor_is_excluded(self) -> None:
        """Mentions with confidence < mention_floor are dropped."""
        section_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        chunk = _chunk(chunk_id, section_id, 0, 100)
        mention = _mention(uuid.uuid4(), section_id, 10, 20, confidence=0.5)

        result = _build_chunk_entity_mentions([chunk], [mention], mention_floor=0.6)

        assert result[chunk_id] == []

    @pytest.mark.unit
    def test_mention_exactly_at_floor_is_included(self) -> None:
        """Confidence exactly equal to the floor passes (>= comparison)."""
        section_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        chunk = _chunk(chunk_id, section_id, 0, 100)
        mention = _mention(uuid.uuid4(), section_id, 5, 15, confidence=0.6)

        result = _build_chunk_entity_mentions([chunk], [mention], mention_floor=0.6)

        assert len(result[chunk_id]) == 1

    @pytest.mark.unit
    def test_mention_in_different_section_is_excluded(self) -> None:
        """A mention from a different section is not matched to the chunk."""
        chunk_section = uuid.uuid4()
        mention_section = uuid.uuid4()
        chunk_id = uuid.uuid4()

        chunk = _chunk(chunk_id, chunk_section, 0, 100)
        mention = _mention(uuid.uuid4(), mention_section, 10, 20, confidence=0.9)

        result = _build_chunk_entity_mentions([chunk], [mention], mention_floor=0.6)

        assert result[chunk_id] == []

    @pytest.mark.unit
    def test_non_overlapping_mention_excluded(self) -> None:
        """Mention entirely before the chunk char range is excluded."""
        section_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        chunk = _chunk(chunk_id, section_id, 100, 200)
        # mention ends at char 50, chunk starts at 100 — no overlap
        mention = _mention(uuid.uuid4(), section_id, 30, 50, confidence=0.9)

        result = _build_chunk_entity_mentions([chunk], [mention], mention_floor=0.6)

        assert result[chunk_id] == []

    @pytest.mark.unit
    def test_unresolved_mention_has_null_entity_id(self) -> None:
        """Mentions without a resolved_entity_id emit null entity_id in the dict."""
        section_id = uuid.uuid4()
        chunk_id = uuid.uuid4()

        chunk = _chunk(chunk_id, section_id, 0, 100)
        mention = _mention(uuid.uuid4(), section_id, 10, 20, confidence=0.8, resolved_entity_id=None)

        result = _build_chunk_entity_mentions([chunk], [mention], mention_floor=0.6)

        assert result[chunk_id][0]["entity_id"] is None

    @pytest.mark.unit
    def test_multiple_chunks_and_mentions(self) -> None:
        """Each mention is routed to the correct chunk by section + offset."""
        section_id = uuid.uuid4()
        chunk_a_id = uuid.uuid4()
        chunk_b_id = uuid.uuid4()
        eid_a = uuid.uuid4()
        eid_b = uuid.uuid4()

        chunk_a = _chunk(chunk_a_id, section_id, 0, 100)
        chunk_b = _chunk(chunk_b_id, section_id, 100, 200)
        # mention_a overlaps only chunk_a
        mention_a = _mention(uuid.uuid4(), section_id, 10, 30, confidence=0.9, resolved_entity_id=eid_a)
        # mention_b overlaps only chunk_b
        mention_b = _mention(uuid.uuid4(), section_id, 110, 150, confidence=0.85, resolved_entity_id=eid_b)

        result = _build_chunk_entity_mentions([chunk_a, chunk_b], [mention_a, mention_b], mention_floor=0.6)

        assert len(result[chunk_a_id]) == 1
        assert result[chunk_a_id][0]["entity_id"] == str(eid_a)
        assert len(result[chunk_b_id]) == 1
        assert result[chunk_b_id][0]["entity_id"] == str(eid_b)

    @pytest.mark.unit
    def test_mention_straddling_boundary_assigned_to_both_chunks(self) -> None:
        """A mention whose char range spans a chunk boundary is assigned to both adjacent chunks."""
        section_id = uuid.uuid4()
        chunk_a_id = uuid.uuid4()
        chunk_b_id = uuid.uuid4()
        eid = uuid.uuid4()

        chunk_a = _chunk(chunk_a_id, section_id, 0, 100)
        chunk_b = _chunk(chunk_b_id, section_id, 100, 200)
        # mention spans the boundary at 90-110 -> overlaps both chunks
        mention = _mention(uuid.uuid4(), section_id, 90, 110, confidence=0.9, resolved_entity_id=eid)

        result = _build_chunk_entity_mentions([chunk_a, chunk_b], [mention], mention_floor=0.6)

        assert len(result[chunk_a_id]) == 1, "mention should be assigned to chunk_a (overlap)"
        assert len(result[chunk_b_id]) == 1, "mention should be assigned to chunk_b (overlap)"
        assert result[chunk_a_id][0]["entity_id"] == str(eid)
        assert result[chunk_b_id][0]["entity_id"] == str(eid)

    @pytest.mark.unit
    def test_empty_inputs_return_empty_maps(self) -> None:
        """Empty chunk and mention lists produce an empty result."""
        result = _build_chunk_entity_mentions([], [], mention_floor=0.6)
        assert result == {}
