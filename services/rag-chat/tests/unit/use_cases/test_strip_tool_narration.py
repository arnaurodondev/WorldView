"""Tests for `_strip_tool_narration` (PLAN-0107 follow-up Fix #4).

The function is defense-in-depth: when Fixes #1-#3 work, it is a no-op.
When they don't, it guarantees the persisted answer artefact is clean.
Each test pins one regex's behaviour and the clean-input no-op case.
"""

from __future__ import annotations

import pytest
from rag_chat.application.use_cases.chat_orchestrator import _strip_tool_narration

pytestmark = pytest.mark.unit


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
