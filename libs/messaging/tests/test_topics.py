"""Tests for topic name constants (topics.py)."""

from __future__ import annotations

from typing import ClassVar

import pytest

import messaging.topics as topics


class TestTopicConstants:
    """All topic constants must be non-empty strings following the naming convention."""

    ALL_TOPICS: ClassVar[list[str]] = [
        "PORTFOLIO_EVENTS",
        "MARKET_DATASET_FETCHED",
        "MARKET_INSTRUMENT_CREATED",
        "MARKET_INSTRUMENT_UPDATED",
        "CONTENT_ARTICLE_RAW",
        "CONTENT_ARTICLE_STORED",
        "NLP_ARTICLE_ENRICHED",
        "NLP_SIGNAL_DETECTED",
    ]

    @pytest.mark.parametrize("attr", ALL_TOPICS)
    def test_constant_exists(self, attr: str) -> None:
        assert hasattr(topics, attr), f"Missing topic constant: {attr}"

    @pytest.mark.parametrize("attr", ALL_TOPICS)
    def test_constant_is_string(self, attr: str) -> None:
        value = getattr(topics, attr)
        assert isinstance(value, str)
        assert len(value) > 0

    @pytest.mark.parametrize("attr", ALL_TOPICS)
    def test_no_whitespace(self, attr: str) -> None:
        value = getattr(topics, attr)
        assert " " not in value
        assert "\t" not in value

    def test_all_unique(self) -> None:
        values = [getattr(topics, attr) for attr in self.ALL_TOPICS]
        assert len(values) == len(set(values)), "Duplicate topic names found"

    def test_portfolio_topic(self) -> None:
        assert topics.PORTFOLIO_EVENTS == "portfolio.events.v1"

    def test_market_dataset_fetched(self) -> None:
        assert topics.MARKET_DATASET_FETCHED == "market.dataset.fetched"

    def test_content_topics_versioned(self) -> None:
        assert "v1" in topics.CONTENT_ARTICLE_RAW
        assert "v1" in topics.CONTENT_ARTICLE_STORED

    def test_nlp_topics_versioned(self) -> None:
        assert "v1" in topics.NLP_ARTICLE_ENRICHED
        assert "v1" in topics.NLP_SIGNAL_DETECTED
