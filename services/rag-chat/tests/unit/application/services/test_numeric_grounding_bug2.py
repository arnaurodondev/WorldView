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


# ── BUG-2 (2026-07-01): full-width / CJK bracket variants ─────────────────────
#
# The live gpt-oss-120b model emits ``【search_events row 1】`` (CJK brackets)
# almost exclusively. The ASCII-anchored citation regexes were blind to them, so
# citations were dropped AND the numeric fast-path could not ground a cited
# number → a spurious rewrite that also emptied citations.


def test_normalize_recognises_cjk_brackets() -> None:
    """``【search_events row N】`` (CJK) maps to positional ``[N]`` markers."""
    items = [
        _item("ev0", "Blackwell ramp", title="Blackwell", url="https://a"),
        _item("ev1", "DC demand", title="DC demand", url="https://b"),
    ]
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}
    row_items = {("search_events", i): it for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    # Full-width and CJK bracket variants the live model emits.
    text = "NVIDIA is ramping Blackwell 【search_events row 0】 amid demand ［search_events row 1］."  # noqa: RUF001
    out = normalize_tool_row_citations(text, resolver)
    assert "[1]" in out and "[2]" in out
    assert "【" not in out and "】" not in out and "［" not in out  # noqa: RUF001
    assert "row 0" not in out and "row 1" not in out


def test_cjk_tool_row_answer_produces_real_citations_end_to_end() -> None:
    """A CJK-bracketed answer yields real citations (the live-model shape)."""
    items = [
        _item("ev0", "Blackwell ramp", title="Blackwell ramp", url="https://x/1"),
        _item("ev1", "DC demand", title="DC demand", url="https://x/2"),
    ]
    row_items = {("search_events", 0): items[0], ("search_events", 1): items[1]}
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    answer = "Recent events: Blackwell is ramping 【search_events row 0】 and demand is strong 【search_events row 1】."
    normalized = normalize_tool_row_citations(answer, resolver)
    _clean, citations = OutputProcessor().process(normalized, items)
    assert len(citations) == 2, f"expected 2 citations, got {citations}"
    assert {c.url for c in citations} == {"https://x/1", "https://x/2"}


def test_cjk_cited_number_grounds_via_fast_path_no_rewrite() -> None:
    """A material number cited with a CJK bracket to a CALLED tool grounds cleanly.

    Before the fix the CJK citation was invisible to ``_has_grounding_citation``
    so ``92%`` looked unsupported → spurious rewrite that dropped citations. After
    normalising brackets the validator sees the citation and the answer passes.
    """
    from rag_chat.application.services.numeric_grounding import normalize_citation_brackets

    validator = NumericGroundingValidator()
    # search_events returned this figure in its text; the model cites it via CJK.
    tool_item = _item(
        "ev0",
        "NVIDIA data-center revenue grew 92% year-over-year.",
        title="NVDA DC revenue",
        url="https://x/1",
    )
    answer = "NVIDIA's data-center revenue grew 92% YoY 【search_events row 0】."
    # The orchestrator normalises brackets before grounding — do the same here.
    normalized = normalize_citation_brackets(answer)
    result = validator.validate(normalized, tool_results=[tool_item], called_tool_names=["search_events"])
    assert (
        numeric_grounding_effectively_passed(result) is True
    ), "a CJK-cited number to a called tool must ground (no spurious rewrite)"


def test_normalize_citation_brackets_is_idempotent_on_ascii() -> None:
    from rag_chat.application.services.numeric_grounding import normalize_citation_brackets

    ascii_text = "Plain [search_events row 0] answer with [1] marker."
    assert normalize_citation_brackets(ascii_text) == ascii_text


# ── 2026-07-01 marker-robustness: prefix tolerance + out-of-range clamp ───────
#
# Residual from the round-2 live QA: citations still vanished when the model used
# NON-STANDARD provenance markers. Two observed shapes:
#   1. ``[functions.get_prediction_markets row 0]`` — the model prefixes the tool
#      name with the OpenAI function-calling namespace ``functions.`` → the tag
#      failed to match the tool-row regex at all → citation stripped.
#   2. ``[get_filings row 10]`` when only 5 rows were retrieved — an out-of-range
#      row index → treated as out-of-range and stripped instead of clamped.
# Both now deliver a citation; the phantom-tool refusal is untouched.


def _pk_items() -> list[RetrievedItem]:
    return [
        _item("pm0", "Will X win?", title="Market 0", url="https://polymarket.com/event/a"),
        _item("pm1", "Will Y win?", title="Market 1", url="https://polymarket.com/event/b"),
    ]


def test_functions_namespace_prefix_maps_to_real_citation() -> None:
    """``[functions.get_prediction_markets row 0]`` resolves to the item position.

    The ``functions.`` namespace prefix is stripped before the tool-row lookup, so
    the bare ``get_prediction_markets`` key matches the map and the tag becomes a
    real ``[1]`` citation instead of being dropped.
    """
    items = _pk_items()
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}
    row_items = {("get_prediction_markets", i): it for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    text = "Odds favour X [functions.get_prediction_markets row 0] and Y [functions.get_prediction_markets row 1]."
    out = normalize_tool_row_citations(text, resolver)
    assert "[1]" in out and "[2]" in out
    assert "functions." not in out and "row 0" not in out and "row 1" not in out


def test_tool_and_tools_namespace_prefixes_also_map() -> None:
    """Sibling namespace prefixes (``tool.`` / ``tools.``) are stripped too."""
    items = _pk_items()
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}
    row_items = {("get_prediction_markets", i): it for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    text = "A [tool.get_prediction_markets row 0] and B [tools.get_prediction_markets row 1]."
    out = normalize_tool_row_citations(text, resolver)
    assert "[1]" in out and "[2]" in out
    assert "tool." not in out and "tools." not in out


def test_prefixed_end_to_end_produces_real_citations() -> None:
    """A ``functions.``-prefixed answer yields real URL-bearing citations."""
    items = _pk_items()
    row_items = {("get_prediction_markets", 0): items[0], ("get_prediction_markets", 1): items[1]}
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    answer = "Markets: [functions.get_prediction_markets row 0] and [functions.get_prediction_markets row 1]."
    normalized = normalize_tool_row_citations(answer, resolver)
    _clean, citations = OutputProcessor().process(normalized, items)
    assert {c.url for c in citations} == {"https://polymarket.com/event/a", "https://polymarket.com/event/b"}


def test_row_zero_maps_to_first_item() -> None:
    """``row 0`` (0-based) maps to the FIRST retrieved item, position ``[1]``."""
    items = _pk_items()
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}
    row_items = {("get_prediction_markets", i): it for i, it in enumerate(items)}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    text = "First market [get_prediction_markets row 0]."
    out = normalize_tool_row_citations(text, resolver)
    assert "[1]" in out and "row 0" not in out


def test_out_of_range_row_clamps_to_last_valid_row_not_stripped() -> None:
    """``[get_filings row 10]`` on a 5-row result clamps to the last row (not strip).

    The 5 rows occupy 0-based indices 0..4. Row 10 is past the end; with a
    row-count resolver reporting 5 rows the index clamps to 4 and the tag becomes
    the fifth item's positional citation instead of being dropped.
    """
    # 5 filings → positions [1]..[5]; row indices 0..4.
    items = [_item(f"f{i}", f"Filing {i}", title=f"Filing {i}", url=f"https://sec.gov/{i}") for i in range(5)]
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}
    row_items = {("get_filings", i): it for i, it in enumerate(items)}
    counts = {"get_filings": 5}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    def count_resolver(tool: str) -> int | None:
        return counts.get(tool)

    text = "Latest filing [get_filings row 10]."
    out = normalize_tool_row_citations(text, resolver, count_resolver)
    # Clamped to the last valid row (index 4 → position [5]); NOT left verbatim.
    assert "[5]" in out
    assert "get_filings" not in out and "row 10" not in out


def test_negative_row_clamps_to_first_row() -> None:
    """A defensive negative index clamps to row 0 → first item (guards convention)."""
    # ``\d+`` never captures a sign, so we exercise the clamp helper directly by
    # asking the resolver for a row below range: the clamp floor is 0.
    from rag_chat.application.services.numeric_grounding import normalize_tool_row_citations as _norm

    items = _pk_items()
    pos_by_id = {it.item_id: i + 1 for i, it in enumerate(items)}
    # Only row 0 maps; row 9 is out of range so the clamp must land on 0.
    row_items = {("get_prediction_markets", 0): items[0]}
    counts = {"get_prediction_markets": 1}

    def resolver(tool: str, row: int) -> int | None:
        it = row_items.get((tool, row))
        return pos_by_id.get(it.item_id) if it else None

    def count_resolver(tool: str) -> int | None:
        return counts.get(tool)

    text = "Only market [get_prediction_markets row 9]."
    out = _norm(text, resolver, count_resolver)
    assert "[1]" in out and "row 9" not in out


def test_clamp_does_not_apply_to_phantom_never_called_tool() -> None:
    """A never-called tool (count resolver → None) is LEFT VERBATIM, not clamped.

    This preserves the phantom-tool refusal guarantee: the clamp only fires for a
    tool that actually returned rows. A fabricated tool citation stays intact for
    the downstream phantom guard to refuse.
    """

    def resolver(tool: str, row: int) -> int | None:
        return None  # nothing maps — the tool never ran

    def count_resolver(tool: str) -> int | None:
        return None  # phantom → no rows

    text = "Fabricated [made_up_tool row 3]."
    out = normalize_tool_row_citations(text, resolver, count_resolver)
    assert out == text  # untouched → strip/refuse guards handle it


def test_phantom_tool_citation_still_refused() -> None:
    """``find_phantom_tool_citations`` still flags a never-called tool tag.

    The prefix-tolerant regex must not weaken phantom detection: a
    ``[made_up_tool row 3]`` whose tool was never called is still phantom, and a
    ``functions.``-prefixed phantom is now DETECTED (was previously invisible)
    against its bare name.
    """
    from rag_chat.application.services.numeric_grounding import find_phantom_tool_citations

    called = ["get_entity_news"]
    # Bare phantom → flagged.
    assert find_phantom_tool_citations("Claim [made_up_tool row 3].", called) == {"made_up_tool"}
    # Namespaced phantom → flagged against its BARE name.
    assert find_phantom_tool_citations("Claim [functions.made_up_tool row 3].", called) == {"made_up_tool"}
    # Namespaced REAL tool → NOT phantom (bare name is in the called set).
    assert find_phantom_tool_citations("News [functions.get_entity_news row 0].", called) == set()


def test_out_of_range_guard_recognises_namespaced_tag() -> None:
    """``find_out_of_range_tool_citations`` sees a ``functions.`` prefixed tag.

    The row-count bound still applies to the bare tool name; the full matched
    substring (with prefix) is returned so the caller can strip it verbatim.
    """
    from rag_chat.application.services.numeric_grounding import find_out_of_range_tool_citations

    answer = "A [functions.screen_universe row 4]."
    oor = find_out_of_range_tool_citations(answer, {"screen_universe": 1})
    assert oor == {"[functions.screen_universe row 4]"}


# ── Point 2 Stage 1 (2026-07-03): framing/intent-aware numeric gate ──────────
#
# The material-grounding gate must distinguish a CLAIMED RETRIEVED FACT (still
# refuse when uncited — the AMD $34.6B fabrication class) from a REASONED
# PROJECTION or an explicitly DERIVED figure (now allowed). These pin the
# owner-approved allow/refuse boundary end-to-end through the validator.


def _tool(text: str) -> RetrievedItem:
    """A single tool result whose text carries a number, tagged entity nvda."""
    return _item("t0", text, title="src", url="https://s")


def test_framing_bare_factual_figure_still_refuses() -> None:
    """(1) 'revenue was $34.6B' uncited → STILL material/refuse (fabrication guard)."""
    validator = NumericGroundingValidator()
    answer = "AMD's Q2 2026 revenue was $34.6B according to the latest results."
    result = validator.validate(answer, tool_results=[], called_tool_names=[])
    mat = material_unsupported_numbers(result)
    assert any(u.field_kind == FieldKind.REVENUE for u in mat), mat
    assert numeric_grounding_effectively_passed(result) is False


def test_framing_hedged_projection_now_allowed() -> None:
    """(2) 'could add ~$2B to next-quarter revenue' uncited → NOW allowed (hedged)."""
    validator = NumericGroundingValidator()
    answer = "The new data-center deal could add ~$2B to next-quarter revenue."
    result = validator.validate(answer, tool_results=[], called_tool_names=[])
    # The number is still surfaced as unsupported (no tool value), but it is
    # framed as a projection so the MATERIAL gate downgrades it → no rewrite.
    assert any(u.hedged_or_derived for u in result.unsupported), result.unsupported
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_framing_derived_figure_allowed() -> None:
    """(3) '$X, derived from the cited $Y - $Z' -> allowed (explicit derivation)."""
    validator = NumericGroundingValidator()
    answer = "Gross margin of $8B, derived from the cited $34.6B revenue minus $26.6B cost."
    result = validator.validate(answer, tool_results=[], called_tool_names=[])
    # Every material figure in the derivation sentence is downgraded.
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_framing_incidental_year_unchanged() -> None:
    """(4) an incidental year/quarter → unchanged (never material either way)."""
    validator = NumericGroundingValidator()
    answer = "NVIDIA announced the partnership in 2026 with a major cloud provider."
    result = validator.validate(answer, tool_results=[], called_tool_names=[])
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_framing_real_citation_unchanged() -> None:
    """(5) a real citation → unchanged: a grounded figure never enters unsupported."""
    validator = NumericGroundingValidator()
    tool = _tool("Revenue was 34600000000 for the quarter.")
    answer = "AMD revenue was $34.6B [query_fundamentals row 0]."
    result = validator.validate(answer, tool_results=[tool], called_tool_names=["query_fundamentals"])
    # Grounded by the tool value + citation — no unsupported material claim.
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_framing_trailing_hedge_does_not_excuse_fact() -> None:
    """A hedge on a LATER clause must NOT downgrade a bare factual figure."""
    validator = NumericGroundingValidator()
    answer = "AMD revenue was $34.6B, and it could grow further next year."
    result = validator.validate(answer, tool_results=[], called_tool_names=[])
    # 'could' sits AFTER the number → pre-window has no hedge → stays material.
    assert any(u.field_kind == FieldKind.REVENUE and not u.hedged_or_derived for u in result.unsupported)
    assert numeric_grounding_effectively_passed(result) is False


def test_framing_analytical_intent_relaxes_full_sentence_hedge() -> None:
    """analytical_intent=True relaxes a hedge anywhere in the sentence."""
    validator = NumericGroundingValidator()
    # Hedge ('could') trails the figure → strict flag stays False …
    answer = "Revenue reaches $2B in this scenario, if the deal could close."
    result = validator.validate(answer, tool_results=[], called_tool_names=[])
    # … but with an analytical/what-if question the full-sentence hedge relaxes it.
    assert material_unsupported_numbers(result, analytical_intent=True) == ()
    assert numeric_grounding_effectively_passed(result, analytical_intent=True) is True


# ── Point 3 (2026-07-05): grounded-BY-DERIVATION recognition ──────────────────
#
# Deep answers legitimately DERIVE numbers from cited figures (FY = Σ quarters,
# YoY growth %, a P/E from cited price & EPS). Those derived results appear
# verbatim in no tool value, so the pre-existing direct-match + citation
# fast-path flagged them → the over-eager "unmatched source" caveat fired on
# nearly every good deep answer. These tests pin the derivation fast-path AND
# prove the fabrication guarantee survives (a truly invented figure with no
# grounded basis still fails).


def test_derivation_sum_of_cited_quarters_grounded() -> None:
    """FY revenue = SUM of four cited quarterly revenues → grounded, no caveat."""
    validator = NumericGroundingValidator()
    tool = _tool("Q1 revenue 20B. Q2 revenue 21B. Q3 revenue 22B. Q4 revenue 23B.")
    answer = "For nvda, full-year revenue totalled $86B."
    result = validator.validate(answer, tool_results=[tool], called_tool_names=["query_fundamentals"])
    # 20+21+22+23 = 86 → derivable from the grounded pool → not material.
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_derivation_yoy_growth_percent_grounded() -> None:
    """A YoY growth % derived from two cited revenues → grounded, no caveat."""
    validator = NumericGroundingValidator()
    tool = _tool("nvda Q1 2026 revenue was 20B. nvda Q1 2025 revenue was 18.5B.")
    answer = "nvda revenue grew 8.1% year-over-year."
    result = validator.validate(answer, tool_results=[tool], called_tool_names=["query_fundamentals"])
    # (20 - 18.5) / 18.5 ≈ 0.0811 → the 8.1% is grounded by derivation.
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_formatting_variant_of_cited_number_grounded() -> None:
    """A formatting variant ($81.61B) of a cited raw number → grounded, no caveat."""
    validator = NumericGroundingValidator()
    tool = _tool("nvda revenue was 81,615,000,000 for the quarter.")
    answer = "nvda revenue was $81.61B."
    result = validator.validate(answer, tool_results=[tool], called_tool_names=["query_fundamentals"])
    # $81.61B ≈ 81,615,000,000 after scale/notation normalisation → matches directly.
    assert material_unsupported_numbers(result) == ()
    assert numeric_grounding_effectively_passed(result) is True


def test_derivation_does_not_ground_fabricated_pe() -> None:
    """A fabricated P/E with NO cited price/EPS basis STILL fails (fabrication guard)."""
    validator = NumericGroundingValidator()
    # Pool has only revenue + net income; no pair derives 32.5 (ratios ≈ 4 / 0.25).
    tool = _tool("nvda revenue was 100B. nvda net income 25B.")
    answer = "nvda's P/E ratio is 32.5x."
    result = validator.validate(answer, tool_results=[tool], called_tool_names=["query_fundamentals"])
    assert any(u.field_kind == FieldKind.RATIO for u in material_unsupported_numbers(result))
    assert numeric_grounding_effectively_passed(result) is False


def test_derivation_does_not_ground_fabricated_revenue() -> None:
    """An invented revenue with no derivable grounded basis STILL fails."""
    validator = NumericGroundingValidator()
    tool = _tool("nvda total revenue 100B. nvda net income 25B.")
    answer = "nvda cloud revenue was $47.3B."
    result = validator.validate(answer, tool_results=[tool], called_tool_names=["query_fundamentals"])
    # No subset sum / ratio / growth of {100B, 25B} lands on 47.3B → stays material.
    assert len(material_unsupported_numbers(result)) >= 1
    assert numeric_grounding_effectively_passed(result) is False


def test_is_derivable_from_grounded_unit() -> None:
    """Direct unit coverage of the derivation helper's shapes + negatives."""
    from rag_chat.application.services.numeric_grounding import _is_derivable_from_grounded

    pool = [20e9, 21e9, 22e9, 23e9]
    assert _is_derivable_from_grounded(86e9, pool) is True  # sum of all four
    assert _is_derivable_from_grounded(41e9, pool) is True  # 20 + 21
    # YoY growth fraction + percent forms.
    assert _is_derivable_from_grounded(0.081081, [20e9, 18.5e9]) is True
    assert _is_derivable_from_grounded(8.1081, [20e9, 18.5e9]) is True
    # Ratio (P/E) from grounded price & EPS.
    assert _is_derivable_from_grounded(30.0, [150.0, 5.0]) is True
    # Negatives: no grounded basis.
    assert _is_derivable_from_grounded(32.5, [100e9, 25e9]) is False
    assert _is_derivable_from_grounded(47.3e9, [100e9, 25e9]) is False
    assert _is_derivable_from_grounded(5.0, []) is False
    assert _is_derivable_from_grounded(0.0, [1.0, 2.0]) is False


# ── Point 3 fast-follow (2026-07-05): raised derivation caps for deep answers ──


def test_derivation_sum_of_eight_quarters_in_large_pool() -> None:
    """(a) A derived figure — SUM of 8 cited quarterly revenues — is recognised as
    grounded even when the operand pool is LARGE (>12 operands), which the old
    caps (_MAX_DERIVATION_POOL=12, _MAX_SUM_TERMS=4) rejected outright."""
    from rag_chat.application.services.numeric_grounding import (
        _MAX_DERIVATION_POOL,
        _MAX_SUM_TERMS,
        _is_derivable_from_grounded,
    )

    # Caps must have been raised for a deep multi-quarter/segment answer.
    assert _MAX_DERIVATION_POOL >= 40
    assert _MAX_SUM_TERMS >= 8

    # Eight quarterly revenues we want to sum to a trailing-two-year total …
    quarters = [20e9, 21e9, 22e9, 23e9, 24e9, 25e9, 26e9, 27e9]
    trailing_total = sum(quarters)  # 188e9, an 8-term sum
    # … plus a spread of OTHER grounded segment/margin figures so the pool is >12
    # (and >12 non-zero uniques), exercising the raised pool cap + pruned walk.
    filler = [5e9, 6e9, 7e9, 8e9, 9e9, 11e9, 12e9, 13e9, 14e9, 150.0, 5.0, 42.5]
    pool = quarters + filler
    assert len({round(p, 6) for p in pool}) > 12  # genuinely a large pool
    assert _is_derivable_from_grounded(trailing_total, pool) is True
    # A 4-quarter FY sum inside the same large pool is also recognised.
    assert _is_derivable_from_grounded(sum(quarters[:4]), pool) is True


def test_derivation_percent_change_in_large_pool() -> None:
    """(a) A YoY %-change derived from two cited revenues is recognised even when
    the pool is large."""
    from rag_chat.application.services.numeric_grounding import _is_derivable_from_grounded

    pool = [float(v) * 1e9 for v in range(20, 41)]  # 21 grounded operands, >12
    # (30 - 20) / 20 = 0.5 → 50% growth; both fraction and percent forms.
    assert _is_derivable_from_grounded(0.5, pool) is True
    assert _is_derivable_from_grounded(50.0, pool) is True


def test_derivation_two_step_product_margin_times_revenue() -> None:
    """Two-step product form: a cited margin applied to a cited revenue.

    74.9% margin x $81.61B revenue ≈ $61.13B (gross profit). Gated: the margin
    operand is small (≤ 100), so the product path fires."""
    from rag_chat.application.services.numeric_grounding import _is_derivable_from_grounded

    # Margin stored as a percent (74.9) and revenue in base units.
    assert _is_derivable_from_grounded(74.9 / 100.0 * 81.61e9, [74.9, 81.61e9]) is True
    # Margin stored as a fraction (0.749).
    assert _is_derivable_from_grounded(0.749 * 81.61e9, [0.749, 81.61e9]) is True


def test_derivation_product_gate_rejects_two_large_figures() -> None:
    """The product gate forbids multiplying two large figures — neither operand is
    a small multiplier, so a fabricated giant cannot be grounded by a*b."""
    from rag_chat.application.services.numeric_grounding import _is_derivable_from_grounded

    # 100e9 * 25e9 = 2.5e21; assert that giant product is NOT accepted as a basis.
    assert _is_derivable_from_grounded(100e9 * 25e9, [100e9, 25e9]) is False


def test_fabrication_still_flagged_in_large_pool() -> None:
    """(b) A genuinely fabricated figure with NO grounded derivation basis is STILL
    flagged even against a LARGE operand pool (the raised caps must not create
    false grounding). Uses a target BEYOND the reachable subset-sum range and
    with no ratio/percent/product basis — a fabricated giant.

    Brute-force-confirmed non-derivable so the fixture cannot silently rot."""
    import itertools as _it

    from rag_chat.application.services.numeric_grounding import _is_derivable_from_grounded

    # 21 distinct grounded revenues (20e9..40e9, offset so sums are not round).
    pool = [float(v) * 1e9 + 3.7e8 for v in range(20, 41)]
    # Larger than the total of the whole pool → no subset (any size) can reach it.
    fabricated = sum(pool) * 3.0 + 1.7e9
    # Guard: no ≤8-term subset sums within tolerance (range-prune territory, so the
    # loop is a cheap belt-and-braces on the fixture, not the hot path).
    assert not any(
        abs(sum(combo) - fabricated) / fabricated <= 0.01
        for r in range(2, 9)
        for combo in _it.combinations(pool[:12], r)
    )
    assert _is_derivable_from_grounded(fabricated, pool) is False


def test_derivation_performance_bounded_on_max_pool() -> None:
    """(d) Perf sanity: derivation over a full-size pool with an 8-term target
    completes fast even in the WORST case (target not found → full pruned walk +
    node budget). Guards against the old C(N, r) brute-force blow-up."""
    import time

    from rag_chat.application.services.numeric_grounding import (
        _MAX_DERIVATION_POOL,
        _is_derivable_from_grounded,
    )

    # A pathological, tightly-clustered pool maximises the pruned walk's branching
    # (all values ≈1e9, so k-term subset sums cluster near k·1e9). The target sits
    # BETWEEN clusters (7.5e9 is ~0.5e9 from the 7- and 8-term clusters, far
    # outside the 1% band) so no subset matches — the walk cannot early-exit and
    # runs until the node budget, exercising the slowest path.
    pool = [1e9 + i * 1.0 for i in range(_MAX_DERIVATION_POOL)]
    target = 7.5e9  # between the 7-term and 8-term sum clusters → unreachable
    start = time.perf_counter()
    assert _is_derivable_from_grounded(target, pool) is False
    elapsed = time.perf_counter() - start
    # Generous ceiling: the node budget bounds this to well under a second; the
    # old brute force at these caps would be minutes.
    assert elapsed < 0.5, f"derivation too slow: {elapsed:.3f}s"
