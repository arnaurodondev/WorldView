"""Unit tests for ContextAssembler, ContradictionAssembler, and PromptBuilder (T-F-2-02)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from rag_chat.application.pipeline.context_assembler import (
    ContextAssembler,
    ContradictionAssembler,
)
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.entities.conversation import ContradictionRef
from rag_chat.domain.enums import ItemType

pytestmark = pytest.mark.unit


def _item(
    item_id: str = "id-1",
    text: str = "Some evidence text.",
    score: float = 0.80,
    trust: float = 0.90,
    published_at: datetime | None = None,
    source_name: str | None = "SEC",
) -> RetrievedItem:
    return RetrievedItem.create(
        item_id=item_id,
        item_type=ItemType.chunk,
        text=text,
        score=score,
        trust_weight=trust,
        citation_meta=CitationMeta(
            title=None,
            url=None,
            source_name=source_name,
            published_at=published_at,
            entity_name=None,
        ),
        published_at=published_at,
    )


@pytest.fixture
def assembler() -> ContextAssembler:
    return ContextAssembler()


@pytest.fixture
def contradiction_assembler() -> ContradictionAssembler:
    return ContradictionAssembler()


@pytest.mark.unit
def test_context_assembler_numbers_items(assembler: ContextAssembler) -> None:
    """First item gets [1] marker in the output."""
    items = [_item("a"), _item("b")]
    result = assembler.assemble(items)
    assert "[1]" in result
    assert "[2]" in result


@pytest.mark.unit
def test_context_assembler_respects_token_budget(assembler: ContextAssembler) -> None:
    """Very many large items -> output stays within token budget."""
    large_items = [_item(f"item-{i}", text="x" * 2000) for i in range(50)]
    result = assembler.assemble(large_items)
    # Should be well under 32k chars
    assert len(result) < 35_000


@pytest.mark.unit
def test_context_assembler_empty_returns_empty(assembler: ContextAssembler) -> None:
    """No items -> empty string."""
    assert assembler.assemble([]) == ""


@pytest.mark.unit
def test_context_assembler_includes_date(assembler: ContextAssembler) -> None:
    """Published date is included in the context block."""
    item = _item(published_at=datetime(2024, 3, 15, tzinfo=UTC))
    result = assembler.assemble([item])
    assert "2024-03-15" in result


@pytest.mark.unit
def test_context_assembler_unknown_date_on_none(assembler: ContextAssembler) -> None:
    """Items without published_at show 'unknown date'."""
    item = _item(published_at=None)
    result = assembler.assemble([item])
    assert "unknown date" in result


@pytest.mark.unit
def test_contradiction_assembler_empty_returns_empty(
    contradiction_assembler: ContradictionAssembler,
) -> None:
    """No contradictions -> empty text block."""
    block = contradiction_assembler.build([])
    assert not block.has_contradictions
    assert block.text == ""


@pytest.mark.unit
def test_contradiction_assembler_builds_block(
    contradiction_assembler: ContradictionAssembler,
) -> None:
    """Contradictions present -> warning block with claim_type included."""
    ref = ContradictionRef(
        claim_type="revenue_growth",
        strength=0.75,
        sides=({"text": "Revenue grew"}, {"text": "Revenue fell"}),
    )
    block = contradiction_assembler.build([ref])
    assert block.has_contradictions
    assert "revenue_growth" in block.text
    assert len(block.refs) == 1
