"""BUG-2 (2026-06-30) regression tests — KG citations emptied before the user.

Two independent mechanisms emptied the ``citations`` array on grounded answers:

  1. ``[tool_name row N]`` provenance tags (the shape the models actually emit)
     were never recognised by the citation assembler — only plain ``[N]``.
  2. the numeric-grounding rewrite fired on QUALITATIVE answers (whose only
     "unsupported" numbers are dates / counts / years), replacing the answer
     with ``[row N]`` text and dropping citations.

These tests pin the deterministic helpers that fix both, plus an end-to-end
normalize→OutputProcessor assembly check proving a ``[tool_name row N]`` answer
now yields real citations. The numeric-grounding GUARANTEE (material figures
still fail) is regression-tested too.
"""

from __future__ import annotations

import pytest
from rag_chat.application.pipeline.output_processor import OutputProcessor
from rag_chat.application.services.numeric_grounding import (
    GroundingResult,
    NumericGroundingValidator,
    UnsupportedNumber,
    material_unsupported_numbers,
    normalize_tool_row_citations,
    numeric_grounding_effectively_passed,
)
from rag_chat.domain.entities.chat import CitationMeta, RetrievedItem
from rag_chat.domain.enums import ItemType

from contracts.numeric_grounding import FieldKind

pytestmark = pytest.mark.unit


def _item(item_id: str, text: str, *, title: str, url: str) -> RetrievedItem:
    return RetrievedItem.create(
        item_id=item_id,
        item_type=ItemType.event,
        text=text,
        score=0.9,
        trust_weight=0.7,
        citation_meta=CitationMeta(
            title=title,
            url=url,
            source_name="knowledge_graph",
            published_at=None,
            entity_name="nvda",
        ),
    )


def _grounding_result(unsupported: tuple[UnsupportedNumber, ...]) -> GroundingResult:
    return GroundingResult(
        passed=not unsupported,
        total_numbers=len(unsupported),
        unsupported=unsupported,
    )


# ── Mechanism 1: [tool_name row N] → real citations ──────────────────────────


def test_normalize_maps_tool_row_to_prompt_position() -> None:
    """``[search_events row N]`` rewrites to the item's 1-based prompt position."""
    # prompt_items order → positions [1], [2], [3]
    items = [
        _item("ev0", "Blackwell ramp", title="Blackwell", url="https://a"),
        _item("ev1", "Data-center demand", title="DC demand", url="https://b"),
        _item("ev2", "China export curbs", title="China", url="https://c"),
    ]
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}
    # tool row map: search_events rows 0,1,2 → items 0,1,2
    row_items = {("search_events", i): it for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    text = "NVIDIA is ramping Blackwell [search_events row 0] amid demand [search_events row 1]."
    out = normalize_tool_row_citations(text, resolver)
    assert "[1]" in out and "[2]" in out
    assert "row 0" not in out and "row 1" not in out


def test_normalize_leaves_out_of_range_tag_untouched() -> None:
    """A row past what the tool returned resolves to None → tag left verbatim."""

    def resolver(tool: str, row: int) -> int | None:
        return None  # nothing maps

    text = "Claim [search_entity_relations row 9]."
    assert normalize_tool_row_citations(text, resolver) == text


def test_tool_row_answer_produces_real_citations_end_to_end() -> None:
    """normalize + OutputProcessor turns a [tool_name row N] answer into citations.

    This is the core BUG-2 mechanism-1 assertion: before the fix such an answer
    shipped ``citations:[]``; now every mapped tag becomes a Citation carrying
    the source-article URL.
    """
    items = [
        _item("ev0", "Blackwell ramp", title="Blackwell ramp", url="https://x/1"),
        _item("ev1", "DC demand", title="DC demand", url="https://x/2"),
    ]
    row_items = {("search_events", 0): items[0], ("search_events", 1): items[1]}
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    answer = (
        "Recent events: Blackwell is ramping [search_events row 0] and "
        "data-center demand is strong [search_events row 1]."
    )
    normalized = normalize_tool_row_citations(answer, resolver)
    _clean, citations = OutputProcessor().process(normalized, items)

    assert len(citations) == 2, f"expected 2 citations, got {citations}"
    urls = {c.url for c in citations}
    assert urls == {"https://x/1", "https://x/2"}


# ── Mechanism 2: qualitative answers do NOT count as material failures ───────


def test_incidental_numbers_are_not_material() -> None:
    """Dates / counts / years → effectively passed (no rewrite)."""
    unsupported = (
        UnsupportedNumber(
            value=2026.0, field_kind=FieldKind.YEAR, tolerance_used=0.0, closest_tool_value=None, snippet="2026"
        ),
        UnsupportedNumber(
            value=3.0,
            field_kind=FieldKind.UNKNOWN,
            tolerance_used=0.005,
            closest_tool_value=None,
            snippet="3 partnerships",
        ),
        UnsupportedNumber(
            value=9.0, field_kind=FieldKind.UNKNOWN, tolerance_used=0.005, closest_tool_value=None, snippet="Jun 9"
        ),
    )
    result = _grounding_result(unsupported)
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_material_financial_figure_still_fails() -> None:
    """A genuinely-unsupported revenue figure remains material (rewrite required)."""
    unsupported = (
        UnsupportedNumber(
            value=3.46e10,
            field_kind=FieldKind.REVENUE,
            tolerance_used=0.005,
            closest_tool_value=1.025e10,
            snippet="$34.6B",
        ),
    )
    result = _grounding_result(unsupported)
    assert len(material_unsupported_numbers(result)) == 1
    assert numeric_grounding_effectively_passed(result) is False


def test_large_unknown_magnitude_treated_as_material() -> None:
    """A big UNKNOWN-classified number (classifier miss) is still material."""
    unsupported = (
        UnsupportedNumber(
            value=5.0e9,
            field_kind=FieldKind.UNKNOWN,
            tolerance_used=0.005,
            closest_tool_value=None,
            snippet="5,000,000,000",
        ),
    )
    result = _grounding_result(unsupported)
    assert numeric_grounding_effectively_passed(result) is False


def test_validator_qualitative_answer_effectively_passes() -> None:
    """End-to-end: a qualitative events answer with a bare date is not material.

    The validator DOES surface the date as unsupported, but the material gate
    treats the whole answer as effectively grounded so no rewrite fires.
    """
    validator = NumericGroundingValidator()
    answer = "NVIDIA announced a partnership on June 9 with a major cloud provider."
    result = validator.validate(answer, tool_results=[], called_tool_names=[])
    # Whatever the validator flags, none of it is a material financial claim.
    assert numeric_grounding_effectively_passed(result) is True
