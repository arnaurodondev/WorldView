"""Unit tests for prompts.classification.market_polarity — PLAN-0056 Wave C3."""

from __future__ import annotations

import pytest
from prompts.classification.market_polarity import MARKET_POLARITY_CLASSIFIER


class TestMarketPolarityClassifier:
    def test_render_returns_text(self) -> None:
        # No parameters — render() resolves cleanly and un-escapes the {{ → { JSON.
        result = MARKET_POLARITY_CLASSIFIER.render()
        assert "prediction-market analyst" in result
        assert '{"polarity":' in result
        assert '"confidence":' in result

    def test_advertises_all_three_polarity_values(self) -> None:
        result = MARKET_POLARITY_CLASSIFIER.render()
        # The classifier validates the LLM response against these exact three values.
        for polarity in ("bullish", "bearish", "neutral"):
            assert f'"{polarity}"' in result

    def test_contains_direction_examples(self) -> None:
        result = MARKET_POLARITY_CLASSIFIER.render()
        # The semantics (YES-for-entity direction) must survive future edits.
        assert "miss Q3 earnings" in result
        assert "bearish" in result
        assert "approved by the FDA" in result
        assert "bullish" in result

    def test_render_with_dynamic_trailer(self) -> None:
        # Mirrors the call site: static block + Question/Entity trailer appended.
        rendered = MARKET_POLARITY_CLASSIFIER.render()
        prompt = rendered + "\nQuestion: Will Company X miss Q3 earnings?\nEntity: Company X"
        assert "Will Company X miss Q3 earnings?" in prompt
        assert "Company X" in prompt

    def test_version_is_semver(self) -> None:
        assert MARKET_POLARITY_CLASSIFIER.version == "1.0"

    def test_identifier_includes_hash(self) -> None:
        ident = MARKET_POLARITY_CLASSIFIER.identifier()
        assert ident.startswith("market_polarity_classifier@1.0#")
        assert len(ident.split("#")[-1]) == 12

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            MARKET_POLARITY_CLASSIFIER.name = "changed"  # type: ignore[misc]
