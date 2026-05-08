"""Unit tests for Block 4 — GLiNER NER (T-C-2-05).

Critical invariant: zero NER mentions NEVER suppresses the document.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nlp_pipeline.application.blocks.ner import (
    NER_CLASS_LABELS,
    _compute_stats,
    _iou,
    _nms,
    run_ner_block,
)
from nlp_pipeline.domain.enums import MentionClass
from nlp_pipeline.domain.models import EntityMention, Section

pytestmark = pytest.mark.unit


def _make_section(text: str, char_start: int = 0) -> Section:
    return Section(
        section_id=uuid.uuid4(),
        doc_id=uuid.uuid4(),
        section_index=0,
        char_start=char_start,
        char_end=char_start + len(text),
        text=text,
        section_type="body",
    )


def _make_mention(
    mention_text: str,
    label: str,
    score: float,
    char_start: int,
    char_end: int,
    doc_id: uuid.UUID | None = None,
) -> EntityMention:
    return EntityMention(
        mention_id=uuid.uuid4(),
        doc_id=doc_id or uuid.uuid4(),
        section_id=uuid.uuid4(),
        mention_text=mention_text,
        mention_class=MentionClass(label),
        confidence=score,
        char_start=char_start,
        char_end=char_end,
    )


def _make_ner_client(mentions: list[dict[str, Any]]) -> Any:
    """Build a mock NERClient that returns the given mentions for every section.

    run_ner_block now calls batch_extract_entities (one call per batch of sections).
    The mock returns the same mention list for every section in the batch.
    """
    from ml_clients.dataclasses import EntityMention as MLMention  # type: ignore[import-not-found]
    from ml_clients.dataclasses import NEROutput

    ml_mentions = [
        MLMention(
            text=m["text"],
            label=m["label"],
            start=m["start"],
            end=m["end"],
            score=m["score"],
        )
        for m in mentions
    ]
    per_section_output = NEROutput(mentions=ml_mentions)

    async def _batch(inputs: list[Any]) -> list[NEROutput]:
        return [per_section_output] * len(inputs)

    client = MagicMock()
    client.batch_extract_entities = AsyncMock(side_effect=_batch)
    # extract_entities kept for completeness (not called by run_ner_block anymore)
    client.extract_entities = AsyncMock(return_value=per_section_output)
    return client


@pytest.mark.unit
class TestNERClassOntology:
    def test_exactly_11_classes(self) -> None:
        assert len(NER_CLASS_LABELS) == 11

    def test_macroeconomic_indicator_present(self) -> None:
        assert "macroeconomic_indicator" in NER_CLASS_LABELS

    def test_all_classes_valid_mention_class(self) -> None:
        for label in NER_CLASS_LABELS:
            assert MentionClass(label) is not None


@pytest.mark.unit
class TestIoU:
    def test_full_overlap(self) -> None:
        assert _iou(0, 10, 0, 10) == 1.0

    def test_no_overlap(self) -> None:
        assert _iou(0, 5, 10, 15) == 0.0

    def test_partial_overlap(self) -> None:
        result = _iou(0, 10, 5, 15)
        # intersection=5, union=15
        assert abs(result - 5 / 15) < 1e-9

    def test_adjacent_no_overlap(self) -> None:
        assert _iou(0, 5, 5, 10) == 0.0


@pytest.mark.unit
class TestNMS:
    def test_keeps_higher_confidence_when_overlapping(self) -> None:
        doc_id = uuid.uuid4()
        # IoU(0,10 vs 1,9): intersection=8, union=10 → 0.8 > 0.5 → NMS suppresses the lower
        high = _make_mention("Apple Inc.", "organization", 0.95, 0, 10, doc_id)
        low = _make_mention("Apple Inc", "organization", 0.60, 1, 9, doc_id)
        result = _nms([high, low])
        assert len(result) == 1
        assert result[0].confidence == 0.95

    def test_keeps_both_when_no_overlap(self) -> None:
        doc_id = uuid.uuid4()
        m1 = _make_mention("Apple", "organization", 0.90, 0, 5, doc_id)
        m2 = _make_mention("Tesla", "organization", 0.85, 50, 55, doc_id)
        result = _nms([m1, m2])
        assert len(result) == 2

    def test_empty_input_returns_empty(self) -> None:
        assert _nms([]) == []


@pytest.mark.unit
class TestRunNERBlock:
    @pytest.mark.asyncio
    async def test_zero_mentions_returns_empty_list(self) -> None:
        """CRITICAL invariant: zero NER mentions NEVER suppresses the document."""
        client = _make_ner_client([])
        doc_id = uuid.uuid4()
        section = _make_section("No financial entities here whatsoever.")

        mentions, stats = await run_ner_block(doc_id, [section], client)

        # Zero mentions — must return empty list, NOT raise, NOT suppress
        assert mentions == []
        assert stats.distinct_mention_count == 0
        assert stats.high_conf_mention_count == 0

    @pytest.mark.asyncio
    async def test_mentions_returned_correctly(self) -> None:
        client = _make_ner_client(
            [
                {"text": "Apple", "label": "organization", "score": 0.92, "start": 0, "end": 5},
                {"text": "AAPL", "label": "financial_instrument", "score": 0.88, "start": 10, "end": 14},
            ]
        )
        doc_id = uuid.uuid4()
        section = Section(
            section_id=uuid.uuid4(),
            doc_id=doc_id,
            section_index=0,
            char_start=0,
            char_end=50,
            text="Apple AAPL earnings today",
        )
        mentions, stats = await run_ner_block(doc_id, [section], client)

        assert len(mentions) == 2
        assert stats.distinct_mention_count == 2

    @pytest.mark.asyncio
    async def test_short_spans_filtered(self) -> None:
        """Spans < 2 chars must be dropped."""
        client = _make_ner_client(
            [
                {"text": "X", "label": "organization", "score": 0.95, "start": 0, "end": 1},  # 1 char
                {"text": "Apple Inc.", "label": "organization", "score": 0.90, "start": 5, "end": 15},
            ]
        )
        doc_id = uuid.uuid4()
        section = _make_section("X Apple Inc. reported earnings yesterday afternoon.")

        mentions, _ = await run_ner_block(doc_id, [section], client)

        texts = [m.mention_text for m in mentions]
        assert "X" not in texts
        assert "Apple Inc." in texts

    @pytest.mark.asyncio
    async def test_unknown_label_skipped(self) -> None:
        """Unknown NER label must be silently skipped."""
        client = _make_ner_client(
            [
                {"text": "Apple", "label": "unknown_class_xyz", "score": 0.90, "start": 0, "end": 5},
                {"text": "AAPL", "label": "financial_instrument", "score": 0.88, "start": 10, "end": 14},
            ]
        )
        doc_id = uuid.uuid4()
        section = _make_section("Apple AAPL quarterly results today")

        mentions, _ = await run_ner_block(doc_id, [section], client)
        texts = [m.mention_text for m in mentions]
        assert "Apple" not in texts
        assert "AAPL" in texts

    @pytest.mark.asyncio
    async def test_nms_applied_per_section(self) -> None:
        """Overlapping spans within a section must be deduplicated by NMS (IoU > 0.5)."""
        # IoU(0,10 vs 1,9) = 8/10 = 0.8 > 0.5 → lower confidence is suppressed
        client = _make_ner_client(
            [
                {"text": "Apple Inc.", "label": "organization", "score": 0.95, "start": 0, "end": 10},
                {"text": "Apple Inc", "label": "organization", "score": 0.60, "start": 1, "end": 9},
            ]
        )
        doc_id = uuid.uuid4()
        section = _make_section("Apple Inc. beats earnings expectations this quarter.")

        mentions, _ = await run_ner_block(doc_id, [section], client)
        # NMS should keep only the higher-confidence span
        assert len(mentions) == 1
        assert mentions[0].mention_text == "Apple Inc."

    @pytest.mark.asyncio
    async def test_ner_block_sets_model_id(self) -> None:
        """When ner_model_id is passed, all EntityMention objects carry that value (PLAN-0031 B-1)."""
        client = _make_ner_client(
            [
                {"text": "Apple", "label": "organization", "score": 0.92, "start": 0, "end": 5},
                {"text": "AAPL", "label": "financial_instrument", "score": 0.88, "start": 10, "end": 14},
            ]
        )
        doc_id = uuid.uuid4()
        section = _make_section("Apple AAPL earnings today")

        mentions, _ = await run_ner_block(doc_id, [section], client, ner_model_id="test-ner-v1")

        assert len(mentions) == 2
        for m in mentions:
            assert m.ner_model_id == "test-ner-v1"

    @pytest.mark.asyncio
    async def test_ner_block_none_model_id_fallback(self) -> None:
        """When ner_model_id is not passed (defaults to None), mentions have ner_model_id=None."""
        client = _make_ner_client(
            [
                {"text": "Tesla", "label": "organization", "score": 0.90, "start": 0, "end": 5},
            ]
        )
        doc_id = uuid.uuid4()
        section = _make_section("Tesla reported quarterly earnings")

        mentions, _ = await run_ner_block(doc_id, [section], client)

        assert len(mentions) == 1
        assert mentions[0].ner_model_id is None


@pytest.mark.unit
class TestComputeStats:
    def test_empty_mentions(self) -> None:
        doc_id = uuid.uuid4()
        stats = _compute_stats(doc_id, [])
        assert stats.distinct_mention_count == 0
        assert stats.high_conf_mention_count == 0
        assert stats.type_distribution == {}

    def test_counts_correctly(self) -> None:
        doc_id = uuid.uuid4()
        mentions = [
            _make_mention("Apple", "organization", 0.92, 0, 5, doc_id),
            _make_mention("TSMC", "organization", 0.45, 10, 14, doc_id),  # below 0.70 threshold
            _make_mention("Fed", "government_body", 0.80, 20, 23, doc_id),
        ]
        stats = _compute_stats(doc_id, mentions)
        assert stats.distinct_mention_count == 3
        assert stats.high_conf_mention_count == 2  # Apple + Fed (>= 0.70)
        assert stats.type_distribution["organization"] == 2
        assert stats.type_distribution["government_body"] == 1
