"""Unit tests for prompts.extraction — deep extraction prompt template."""

from __future__ import annotations

import pytest
from prompts.extraction.deep import DEEP_EXTRACTION


class TestDeepExtraction:
    def test_render(self) -> None:
        result = DEEP_EXTRACTION.render(entities="AAPL, MSFT", text="Apple announced...")
        assert "AAPL, MSFT" in result
        assert "Apple announced..." in result

    def test_contains_json_instruction(self) -> None:
        result = DEEP_EXTRACTION.render(entities="none identified", text="sample text")
        # v1.1 changed "Return JSON" to "Return the JSON object above" (more specific)
        assert "Return the JSON object" in result
        assert "Output the JSON object only" in result

    def test_missing_entities_raises(self) -> None:
        with pytest.raises(ValueError, match="entities"):
            DEEP_EXTRACTION.render(text="some text")

    def test_missing_text_raises(self) -> None:
        with pytest.raises(ValueError, match="text"):
            DEEP_EXTRACTION.render(entities="AAPL")

    def test_version_is_semver(self) -> None:
        # v1.7: type-annotated entity allow-list — entities carry [type] tags and
        # the prompt has ENTITY TYPE RULES for precision + direction.
        assert DEEP_EXTRACTION.version == "1.7"

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            DEEP_EXTRACTION.name = "changed"  # type: ignore[misc]

    def test_contains_assertion_and_comention_rules(self) -> None:
        """v1.6 precision rules must be present (folded into v1.7)."""
        result = DEEP_EXTRACTION.render(entities="Apple Inc. [organization]", text="x")
        assert "RELATION ASSERTION TEST" in result
        assert "CO-MENTION IS NOT A RELATION" in result

    def test_contains_type_tag_guidance(self) -> None:
        """v1.7: the prompt must explain the [type] tags and how to use them
        for relation precision + direction (the type-annotated allow-list)."""
        result = DEEP_EXTRACTION.render(
            entities="Apple Inc. [organization], S&P 500 [index]",
            text="sample text",
        )
        # The tagged allow-list must be rendered verbatim.
        assert "Apple Inc. [organization], S&P 500 [index]" in result
        # The type-usage section and key precision/direction rules must be present.
        assert "ENTITY TYPE RULES" in result
        assert "DROP the [type] tag" in result
        # PRECISION: index/currency/etc. must never be a company-relation endpoint.
        assert "[index]" in result
        assert "[currency]" in result
        assert "NEVER use one as the subject OR object of a company relation" in result
        # DIRECTION: person is object, organization is subject.
        assert "[person]" in result
        assert "ALWAYS the object" in result
