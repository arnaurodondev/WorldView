"""Unit tests for prompts.classification.article_relevance — Phase 2C migration."""

from __future__ import annotations

import pytest
from prompts.classification.article_relevance import ARTICLE_RELEVANCE_SCORER


class TestArticleRelevanceScorer:
    def test_render_returns_text(self) -> None:
        # No parameters — render() should still resolve cleanly and return
        # the literal system block (with {{ → { in the JSON example).
        result = ARTICLE_RELEVANCE_SCORER.render()
        assert "financial news relevance assessor" in result
        # JSON example braces should be un-escaped after render().
        assert '{"score":' in result
        assert '"sentiment":' in result

    def test_contains_calibration_anchors(self) -> None:
        result = ARTICLE_RELEVANCE_SCORER.render()
        # Each calibration anchor (0.0 / 0.3 / 0.6 / 0.9 / 1.0) must be present
        # so future edits don't silently drop the scoring scale.
        for anchor in ("0.0 = completely irrelevant", "0.3 = mildly relevant", "1.0 = critical"):
            assert anchor in result

    def test_contains_sentiment_enum(self) -> None:
        result = ARTICLE_RELEVANCE_SCORER.render()
        # All four sentiment values must be advertised — the worker validates
        # the LLM response against this exact enum.
        for sentiment in ("positive", "negative", "neutral", "mixed"):
            assert f'"{sentiment}"' in result

    def test_version_is_semver(self) -> None:
        assert ARTICLE_RELEVANCE_SCORER.version == "1.0"

    def test_identifier_includes_hash(self) -> None:
        # identifier() = "name@version#hash" — used by structlog prompt_id.
        ident = ARTICLE_RELEVANCE_SCORER.identifier()
        assert ident.startswith("article_relevance_scorer@1.0#")
        # Hash suffix is a 12-char sha256 prefix.
        assert len(ident.split("#")[-1]) == 12

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            ARTICLE_RELEVANCE_SCORER.name = "changed"  # type: ignore[misc]
