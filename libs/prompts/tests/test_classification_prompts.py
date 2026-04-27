"""Render tests for classification prompt."""

from __future__ import annotations

from prompts.classification.intent import INTENT_CLASSIFICATION


class TestClassificationPrompt:
    def test_render(self) -> None:
        result = INTENT_CLASSIFICATION.render(message="What is Apple?", history="[]", entities="[]")
        assert "Apple" in result
        assert "FACTUAL_LOOKUP" in result

    def test_format_matches_original(self) -> None:
        result = INTENT_CLASSIFICATION.render(message="test query", history='[{"role": "user"}]', entities="[]")
        assert "Query: test query" in result
        assert "Conversation context:" in result
        assert "Resolved entities:" in result

    def test_contains_all_intent_types(self) -> None:
        result = INTENT_CLASSIFICATION.render(message="test", history="[]", entities="[]")
        for intent_name in [
            "FACTUAL_LOOKUP",
            "RELATIONSHIP",
            "SIGNAL_INTEL",
            "FINANCIAL_DATA",
            "COMPARISON",
            "REASONING",
            "PORTFOLIO",
            "GENERAL",
        ]:
            assert intent_name in result

    def test_contains_json_output_instruction(self) -> None:
        result = INTENT_CLASSIFICATION.render(message="test", history="[]", entities="[]")
        assert "Respond with JSON only" in result
