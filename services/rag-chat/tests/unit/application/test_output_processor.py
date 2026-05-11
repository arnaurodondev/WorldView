"""Unit tests for OutputProcessor (T-F-4-01)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rag_chat.application.pipeline.output_processor import OutputProcessor
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


def _item(item_id: str = "chunk-1", score: float = 0.85) -> RetrievedItem:
    return RetrievedItem.create(
        item_id=item_id,
        item_type=ItemType.chunk,
        text="Apple reported record revenue of $120B.",
        score=score,
        trust_weight=0.90,
        citation_meta=CitationMeta(
            title="Apple 10-K 2024",
            url="https://sec.gov/apple",
            source_name="SEC",
            published_at=datetime(2024, 1, 15, tzinfo=UTC),
            entity_name="Apple Inc",
        ),
    )


@pytest.fixture
def processor() -> OutputProcessor:
    return OutputProcessor()


@pytest.mark.unit
def test_output_strips_think_tags(processor: OutputProcessor) -> None:
    """<think>...</think> block is removed from output."""
    raw = "<think>Internal reasoning here</think>The answer is [1]."
    items = [_item()]

    answer, _ = processor.process(raw, items)
    assert "<think>" not in answer
    assert "Internal reasoning" not in answer
    assert "The answer is" in answer


@pytest.mark.unit
def test_output_strips_reasoning_tags(processor: OutputProcessor) -> None:
    """<reasoning> block is removed from output."""
    raw = "<reasoning>Some reasoning</reasoning>Clean answer [1]."
    items = [_item()]

    answer, _ = processor.process(raw, items)
    assert "<reasoning>" not in answer
    assert "Clean answer" in answer


@pytest.mark.unit
def test_output_parses_citation_markers(processor: OutputProcessor) -> None:
    """[1] in answer -> citations[0] populated."""
    raw = "Apple revenue grew [1]."
    items = [_item("chunk-1")]

    _answer, citations = processor.process(raw, items)
    assert len(citations) == 1
    assert citations[0].ref == 1
    assert citations[0].title == "Apple 10-K 2024"
    assert citations[0].id == "chunk-1"


@pytest.mark.unit
def test_output_citation_out_of_range_ignored(processor: OutputProcessor) -> None:
    """[99] when only 5 items -> citation 99 not in list."""
    raw = "Some answer with [99] invalid reference."
    items = [_item(f"item-{i}") for i in range(5)]

    _, citations = processor.process(raw, items)
    refs = [c.ref for c in citations]
    assert 99 not in refs


@pytest.mark.unit
def test_output_multiple_citations(processor: OutputProcessor) -> None:
    """Multiple [N] references in answer -> multiple citations."""
    raw = "Apple [1] compared to Google [2]."
    items = [_item("apple-chunk"), _item("google-chunk")]

    _, citations = processor.process(raw, items)
    assert len(citations) == 2
    refs = sorted(c.ref for c in citations)
    assert refs == [1, 2]


@pytest.mark.unit
def test_output_no_citations_in_text(processor: OutputProcessor) -> None:
    """Answer with no [N] markers -> empty citations list."""
    raw = "The stock market is volatile."
    items = [_item()]

    answer, citations = processor.process(raw, items)
    assert citations == []
    assert "volatile" in answer


@pytest.mark.unit
def test_output_empty_input(processor: OutputProcessor) -> None:
    """Empty raw output -> empty answer and no citations."""
    answer, citations = processor.process("", [])
    assert answer == ""
    assert citations == []
