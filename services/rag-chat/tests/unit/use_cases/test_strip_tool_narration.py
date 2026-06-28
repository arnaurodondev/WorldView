"""Tests for `_strip_tool_narration` (PLAN-0107 follow-up Fix #4).

The function is defense-in-depth: when Fixes #1-#3 work, it is a no-op.
When they don't, it guarantees the persisted answer artefact is clean.
Each test pins one regex's behaviour and the clean-input no-op case.
"""

from __future__ import annotations

import pytest
from rag_chat.application.use_cases.chat_orchestrator import (
    _is_tool_call_stub,
    _strip_tool_narration,
)

pytestmark = pytest.mark.unit

_REGISTRY = frozenset({"get_fundamentals_history", "get_price_history", "search_documents"})


def test_strip_leading_will_fetch_sentence() -> None:
    """'I will fetch ... .' opening line is removed; rest preserved."""
    text = "I will fetch the latest news on MSTR for you. Revenue was $24.7B."
    out = _strip_tool_narration(text)
    assert out == "Revenue was $24.7B."


def test_strip_leading_ill_pull_contraction() -> None:
    """Contracted 'I'll pull ...' is also stripped."""
    text = "I'll pull the data. The answer is 42."
    out = _strip_tool_narration(text)
    assert out == "The answer is 42."


def test_strip_let_me_check() -> None:
    """'Let me check ...' opening is stripped."""
    text = "Let me check the fundamentals.\nMSTR closed at $1,420."
    out = _strip_tool_narration(text)
    assert "Let me check" not in out
    assert "MSTR closed at $1,420." in out


def test_strip_im_fetching() -> None:
    """Progressive 'I'm fetching ...' opening is stripped."""
    text = "I'm fetching the quote now. Price is $1,420."
    out = _strip_tool_narration(text)
    assert out == "Price is $1,420."


def test_strip_first_ill() -> None:
    """'First, I'll ...' transition is stripped."""
    text = "First, I'll retrieve the data. Done."
    out = _strip_tool_narration(text)
    assert out == "Done."


def test_strip_tool_calls_markdown_block() -> None:
    """'**Tool calls:**' header + bullets are removed; surrounding answer kept."""
    text = (
        "The company reported $24.7B in revenue.\n"
        "**Tool calls:**\n"
        "- get_fundamentals(ticker=MSTR)\n"
        "- search_documents(query=earnings)\n"
        "\nThis was a 12% YoY increase."
    )
    out = _strip_tool_narration(text)
    assert "Tool calls" not in out
    assert "get_fundamentals" not in out
    assert "The company reported $24.7B in revenue." in out
    assert "This was a 12% YoY increase." in out


def test_strip_function_calls_xml() -> None:
    """<function_calls><invoke>...</invoke></function_calls> tags removed."""
    text = (
        'Here is the answer. <function_calls> <invoke name="get_entity_news"> '
        '<parameter name="ticker">MSTR</parameter> </invoke> </function_calls>'
    )
    out = _strip_tool_narration(text)
    assert "<function_calls>" not in out
    assert "<invoke" not in out
    assert "<parameter" not in out
    assert "Here is the answer." in out


def test_strip_tool_call_tags() -> None:
    """<tool_call>, <tool_name> tags removed."""
    text = "The result: <tool_call>foo</tool_call> some text <tool_name>bar</tool_name>"
    out = _strip_tool_narration(text)
    assert "<tool_call" not in out
    assert "<tool_name" not in out
    assert "The result:" in out


def test_clean_answer_passes_through_unchanged() -> None:
    """No-op on a clean answer (modulo strip())."""
    text = "MSTR closed at $1,420 on 2026-06-05 [get_fundamentals row 0]. "
    out = _strip_tool_narration(text)
    assert out == text.strip()


def test_only_strips_leading_narration_not_mid_answer() -> None:
    """A legitimate mid-answer 'I'll' phrase is NOT stripped — only the leading sentence."""
    text = "The data shows revenue rose 12%. I'll note this is unaudited."
    out = _strip_tool_narration(text)
    # The leading regex anchors with ^ so the middle "I'll note" survives.
    assert "I'll note this is unaudited." in out


def test_empty_input_returns_empty() -> None:
    assert _strip_tool_narration("") == ""


def test_full_live_bug_reproduction() -> None:
    """End-to-end check on the exact pattern from the live MSTR test report."""
    text = (
        "I'll pull the latest news on MicroStrategy (MSTR) for you.\n"
        '<function_calls> <invoke name="get_entity_news"> '
        '<parameter name="ticker" string="true">MSTR</parameter> '
        "</invoke> </function_calls>\n"
    )
    out = _strip_tool_narration(text)
    assert "I'll pull" not in out
    assert "<function_calls>" not in out
    assert "<invoke" not in out
    assert "<parameter" not in out


# ── Chat-eval #3 (2026-06-12): {"<tool_name>": {…}} single-key leak shape ─────
# The ``ru_nvda_amd_compare_qtr`` degenerate answer was raw tool-call JSON:
#   {"get_fundamentals_history": {"ticker": "NVDA", "periods": }}
# The BP-675 ``{"name":…, "arguments":…}`` detector does NOT match this; the
# scrubber must take the live registry tool names to strip it.


def test_named_single_key_tool_call_stub_stripped_with_registry() -> None:
    """{"<tool_name>": {…}} is stripped when the key is a known tool name."""
    text = '{"get_fundamentals_history": {"ticker": "NVDA", "periods": }}'
    out = _strip_tool_narration(text, _REGISTRY)
    assert out == ""


def test_named_single_key_stub_left_when_no_registry() -> None:
    """Without registry names the named shape is NOT stripped (legacy no-op)."""
    text = '{"get_fundamentals_history": {"ticker": "NVDA"}}'
    out = _strip_tool_narration(text)  # no tool_names passed
    assert out == text


def test_named_single_key_unknown_key_is_preserved() -> None:
    """A legitimate single-key JSON answer (non-tool key) is never stripped."""
    text = '{"revenue": {"q1": 24700000000}}'
    out = _strip_tool_narration(text, _REGISTRY)
    assert out == text


def test_fenced_named_tool_call_stub_stripped() -> None:
    """A fenced ```json {"<tool_name>": {…}}``` block is stripped too."""
    text = '```json\n{"search_documents": {"query": "AAPL competitors"}}\n```'
    out = _strip_tool_narration(text, _REGISTRY)
    assert out.strip() == ""


def test_is_tool_call_stub_detects_named_shape() -> None:
    """The degenerate named-shape answer is flagged as a stub (for fall-through)."""
    text = '{"get_fundamentals_history": {"ticker": "NVDA", "periods": }}'
    assert _is_tool_call_stub(text, _REGISTRY) is True
    # Without the registry it is NOT detectable as the named shape.
    assert _is_tool_call_stub(text) is False


def test_is_tool_call_stub_clean_answer_not_flagged() -> None:
    """A real prose answer that merely quotes JSON is not a stub."""
    text = 'NVDA reported revenue of $26.0B. The raw row was {"revenue": 26000000000}.'
    assert _is_tool_call_stub(text, _REGISTRY) is False


# ── Theme D: plan-only synthesis stub (2026-06-12 root-cause audit) ───────────
#
# VERBATIM artifact from chain_nvda_competitor_growth_rank
# (run_20260612T183758Z): the shipped answer was a future-tense PLAN with
# ``**Step N:**`` headers and no substantive payload — a degenerate non-answer.
_NVDA_PLAN_ONLY_ANSWER = (
    "I'll start by identifying NVIDIA's main competitors and then check their revenue growth.\n\n"
    "**Step 1: Find NVIDIA's competitors**\n\n"
    "I'll search for relationships and entity paths for NVIDIA.\n\n"
    "**Step 2: Get competitor revenue data**\n\n"
    "Let me first get the entity intelligence for NVIDIA to identify competitors, "
    "then fetch fundamentals for those competitors."
)


def test_step_header_lead_extends_narration_lead() -> None:
    """'I'll start by ...' opening is now stripped as a narration lead (Theme D)."""
    text = "I'll start by identifying NVIDIA's competitors. NVDA revenue was $26.0B."
    out = _strip_tool_narration(text)
    assert "I'll start by" not in out
    assert "$26.0B" in out


def test_let_me_first_lead_stripped() -> None:
    """'Let me first ...' plan-prose lead is stripped (Theme D)."""
    text = "Let me first get the entity intelligence.\nThe answer is 42% market share."
    out = _strip_tool_narration(text)
    assert "Let me first" not in out
    assert "42% market share" in out


def test_step_headers_stripped() -> None:
    """``**Step N:**`` plan headers are removed."""
    text = "**Step 1: Find competitors**\nAMD and Intel compete with NVIDIA in GPUs."
    out = _strip_tool_narration(text)
    assert "Step 1" not in out
    assert "AMD and Intel compete" in out


def test_nvda_plan_only_answer_is_stub() -> None:
    """The verbatim chain_nvda plan-only answer is flagged as a tool-call/planning stub."""
    assert _is_tool_call_stub(_NVDA_PLAN_ONLY_ANSWER) is True


def test_plan_with_substantive_content_not_stub() -> None:
    """A plan-lead answer that DOES carry real content (a number) is NOT a stub."""
    # Opens with a plan lead but contains a substantive numeric claim → real answer.
    text = (
        "I'll summarise the competitor revenues.\n\n"
        "**Step 1: Competitors**\n\n"
        "AMD reported $22.7B and Intel reported $54.2B last year."
    )
    assert _is_tool_call_stub(text) is False


def test_plan_only_table_answer_not_stub() -> None:
    """A markdown table (pipe present) is substantive, never a plan-only stub."""
    text = "**Step 1: Compare**\n\n| Company | Revenue |\n|---|---|\n| AMD | $22.7B |"
    assert _is_tool_call_stub(text) is False


# ── RC-3 follow-up (2026-06-28): the RAW-ARGUMENTS leak shape ─────────────────
#
# The live ``iter3_tesla_revenue_since_2023`` smoke shipped a fenced block of the
# planner's query_fundamentals ARGUMENTS verbatim as the answer:
#   ```json
#   {"ticker": "TSLA", "periods": , "period_type": "quarterly"}
#   ```
# plus the canonical "Note: some figures …" disclaimer. The object is INVALID JSON
# (empty ``"periods":``) and has neither a ``name``/``arguments`` wrapper nor a
# ``{"<tool_name>": …}`` wrapper, so the prior detectors missed it.

_RAW_ARGS_LEAK = (
    "```json\n"
    '{\n "ticker": "TSLA",\n "periods": ,\n "period_type": "quarterly"\n}\n'
    "```\n\n"
    "Note: some figures or names above could not be matched to a retrieved source."
)


def test_raw_tool_args_object_leak_is_stub() -> None:
    """The verbatim raw-arguments leak (incl. trailing disclaimer) is a stub."""
    assert _is_tool_call_stub(_RAW_ARGS_LEAK, _REGISTRY) is True


def test_raw_tool_args_object_stripped() -> None:
    """``_strip_tool_narration`` removes the bare-arguments object, leaving only
    the (non-answer) disclaimer line."""
    out = _strip_tool_narration(_RAW_ARGS_LEAK, _REGISTRY)
    assert "ticker" not in out
    assert "period_type" not in out
    assert "could not be matched" in out  # disclaimer survives (it is not a stub)


def test_raw_tool_args_object_detected_without_registry() -> None:
    """The raw-args detector is registry-INDEPENDENT (keyword-gated) — it fires
    even when no tool_names are supplied."""
    assert _is_tool_call_stub(_RAW_ARGS_LEAK) is True


def test_real_answer_with_disclaimer_not_stub() -> None:
    """A genuine multi-quarter table answer that carries the SAME trailing
    disclaimer must NOT be flagged (the disclaimer is discounted, not the answer)."""
    text = (
        "**Tesla (TSLA) Quarterly Revenue**\n\n"
        "| Year | Q1 | Q2 |\n|---|---|---|\n"
        "| 2023 | - | $24.93B |\n| 2024 | $21.30B | $25.50B |\n\n"
        "Revenue trended upward [get_fundamentals_history row 0].\n\n"
        "Note: some figures or names above could not be matched to a retrieved source."
    )
    assert _is_tool_call_stub(text, _REGISTRY) is False


def test_single_field_data_object_not_stub() -> None:
    """A one-field data object (``{"revenue": …}``) is not an arguments stub —
    too few keys and ``revenue`` is not a tool-argument name."""
    assert _is_tool_call_stub('{"revenue": 25000000000}', _REGISTRY) is False


def test_args_object_with_answer_key_not_stub() -> None:
    """An object mixing a tool-arg key with a NON-arg key (e.g. ``verdict``) is a
    real answer object, not a pure arguments stub."""
    text = '{"ticker": "TSLA", "verdict": "revenue grew steadily"}'
    assert _is_tool_call_stub(text, _REGISTRY) is False
