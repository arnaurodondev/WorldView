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
        # v1.3: few-shot examples + predicate inline descriptions added (QW-5/QW-6)
        assert DEEP_EXTRACTION.version == "1.3"

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            DEEP_EXTRACTION.name = "changed"  # type: ignore[misc]
