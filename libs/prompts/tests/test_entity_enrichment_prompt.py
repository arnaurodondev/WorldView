"""Unit tests for entity enrichment prompt helpers (PRD-0073 §11, T-C-1-04)."""

from __future__ import annotations

import pytest
from prompts.knowledge.entity_enrichment import (
    SYSTEM_PROMPT,
    build_entity_enrichment_prompt,
    sanitize_entity_name,
)

pytestmark = pytest.mark.unit


class TestSanitizeEntityName:
    def test_strips_angle_brackets(self) -> None:
        assert "<" not in sanitize_entity_name("<script>alert(1)</script>")
        assert ">" not in sanitize_entity_name("<script>alert(1)</script>")

    def test_strips_control_chars(self) -> None:
        assert "\x00" not in sanitize_entity_name("\x00hello\x1f")
        assert "\x1f" not in sanitize_entity_name("\x00hello\x1f")

    def test_strips_del_char(self) -> None:
        assert "\x7f" not in sanitize_entity_name("foo\x7fbar")

    def test_caps_at_200_chars(self) -> None:
        long_name = "A" * 300
        assert len(sanitize_entity_name(long_name)) == 200

    def test_normal_name_unchanged(self) -> None:
        assert sanitize_entity_name("Apple Inc.") == "Apple Inc."


class TestBuildEntityEnrichmentPrompt:
    def test_includes_sanitized_entity_name(self) -> None:
        prompt = build_entity_enrichment_prompt("<Apple Inc.>", "company")
        # angle brackets stripped by sanitize_entity_name
        assert "Apple Inc." in prompt
        assert "<Apple" not in prompt

    def test_wraps_name_in_entity_tags(self) -> None:
        prompt = build_entity_enrichment_prompt("Tesla, Inc.", "financial_instrument")
        assert "<entity>Tesla, Inc.</entity>" in prompt

    def test_includes_entity_type(self) -> None:
        prompt = build_entity_enrichment_prompt("Tim Cook", "person")
        assert "person" in prompt

    def test_includes_context_hint_when_provided(self) -> None:
        prompt = build_entity_enrichment_prompt("NVDA", "financial_instrument", "sector: Technology")
        assert "sector: Technology" in prompt

    def test_no_context_hint_when_empty(self) -> None:
        prompt = build_entity_enrichment_prompt("NVDA", "financial_instrument")
        assert "Context:" not in prompt

    def test_system_prompt_contains_few_shot_examples(self) -> None:
        assert "Apple Inc." in SYSTEM_PROMPT
        assert "JPMorgan" in SYSTEM_PROMPT
