"""Unit tests for contracts.canonical.sentiment."""

from __future__ import annotations

import dataclasses

import pytest

from contracts.canonical.sentiment import CanonicalSentiment
from contracts.versions import SENTIMENT_SCHEMA_VERSION


class TestCanonicalSentiment:
    def _make_sentiment(self) -> CanonicalSentiment:
        return CanonicalSentiment(
            article_id="01JPXYZ123ABC",
            label="positive",
            score=0.82,
            model_name="finbert",
            model_version="1.0.0",
        )

    def test_schema_version(self) -> None:
        assert self._make_sentiment().schema_version == SENTIMENT_SCHEMA_VERSION

    def test_schema_version_is_1(self) -> None:
        assert SENTIMENT_SCHEMA_VERSION == 1

    def test_roundtrip(self) -> None:
        s = self._make_sentiment()
        restored = CanonicalSentiment.from_dict(s.to_dict())
        assert restored.article_id == s.article_id
        assert restored.label == s.label
        assert restored.score == s.score
        assert restored.model_name == s.model_name
        assert restored.model_version == s.model_version

    def test_frozen(self) -> None:
        s = self._make_sentiment()
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.label = "negative"  # type: ignore[misc]

    def test_labels(self) -> None:
        for label in ("positive", "negative", "neutral"):
            s = CanonicalSentiment(
                article_id="x",
                label=label,
                score=0.5,
                model_name="finbert",
                model_version="1.0",
            )
            assert s.label == label

    def test_score_range(self) -> None:
        s = self._make_sentiment()
        assert 0.0 <= s.score <= 1.0

    def test_score_boundary_zero(self) -> None:
        s = CanonicalSentiment(article_id="x", label="neutral", score=0.0, model_name="finbert", model_version="1.0")
        assert s.score == 0.0

    def test_score_boundary_one(self) -> None:
        s = CanonicalSentiment(article_id="x", label="positive", score=1.0, model_name="finbert", model_version="1.0")
        assert s.score == 1.0

    def test_to_dict_keys(self) -> None:
        d = self._make_sentiment().to_dict()
        expected_keys = {
            "article_id",
            "label",
            "score",
            "model_name",
            "model_version",
            "schema_version",
        }
        assert set(d.keys()) == expected_keys
