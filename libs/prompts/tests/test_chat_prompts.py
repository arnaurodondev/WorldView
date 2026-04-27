"""Render tests for all chat intent prompts migrated from S8."""

from __future__ import annotations

import pytest
from prompts._safety import SAFETY_FOOTER
from prompts.chat.intent import (
    COMPARISON,
    FACTUAL_LOOKUP,
    FINANCIAL_DATA,
    GENERAL,
    PORTFOLIO,
    REASONING,
    RELATIONSHIP,
    SIGNAL_INTEL,
    get_system_prompt,
)

_ALL_PROMPTS = [FACTUAL_LOOKUP, RELATIONSHIP, SIGNAL_INTEL, FINANCIAL_DATA, COMPARISON, REASONING, PORTFOLIO, GENERAL]


class TestChatPrompts:
    def test_all_render_with_safety(self) -> None:
        for pt in _ALL_PROMPTS:
            result = pt.render(safety=SAFETY_FOOTER)
            assert len(result) > 50

    def test_safety_in_all(self) -> None:
        for pt in _ALL_PROMPTS:
            result = pt.render(safety=SAFETY_FOOTER)
            assert "Never speculate" in result

    def test_get_system_prompt_all_intents(self) -> None:
        intents = [
            "FACTUAL_LOOKUP",
            "RELATIONSHIP",
            "SIGNAL_INTEL",
            "FINANCIAL_DATA",
            "COMPARISON",
            "REASONING",
            "PORTFOLIO",
            "GENERAL",
        ]
        for intent in intents:
            result = get_system_prompt(intent)
            assert isinstance(result, str)
            assert len(result) > 50

    def test_get_system_prompt_unknown_fallback(self) -> None:
        result = get_system_prompt("NONEXISTENT")
        expected = FACTUAL_LOOKUP.render(safety=SAFETY_FOOTER)
        assert result == expected

    def test_all_prompts_distinct(self) -> None:
        rendered = [pt.render(safety=SAFETY_FOOTER) for pt in _ALL_PROMPTS]
        assert len(rendered) == len(set(rendered)), "Two prompts rendered identically"

    @pytest.mark.parametrize(
        ("template", "keyword"),
        [
            (FACTUAL_LOOKUP, "citation"),
            (RELATIONSHIP, "hop"),
            (SIGNAL_INTEL, "recency"),
            (FINANCIAL_DATA, "structured"),
            (COMPARISON, "sub-section"),
            (REASONING, "causal"),
            (PORTFOLIO, "holdings"),
            (GENERAL, "follow-up"),
        ],
    )
    def test_each_prompt_contains_key_instruction(self, template, keyword) -> None:  # type: ignore[no-untyped-def]
        result = template.render(safety=SAFETY_FOOTER)
        assert keyword.lower() in result.lower()
